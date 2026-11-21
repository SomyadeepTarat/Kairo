"""Bounded custom kernel with typed tool dispatch and optional durable continuation."""

import asyncio
import json
import math
from collections.abc import Callable, Coroutine
from dataclasses import asdict, dataclass
from enum import StrEnum
from time import monotonic
from uuid import UUID, uuid4

from kairo_core.checkpoints import KernelSnapshot
from kairo_core.context import ContextOverflow, ContextPolicy, assemble
from kairo_core.events import Recorder, event_now
from kairo_core.models import (
    Continue,
    Final,
    Message,
    Model,
    ModelRequest,
    ModelResponse,
    ToolRequest,
    require_text,
)
from kairo_core.state import TERMINAL_STATES, RunStatus, transition
from kairo_core.tools.registry import ToolContext, ToolExecution, ToolRegistry


@dataclass(frozen=True)
class AgentConfig:
    max_steps: int = 16
    step_timeout_seconds: float = 30.0
    run_timeout_seconds: float = 120.0
    system_prompt: str = "Complete the task within the supplied execution limits."

    context_budget_bytes: int = 65536
    tool_output_bytes: int = 8192
    context_strategy: str = "recent"

    def __post_init__(self) -> None:
        self.context_policy()
        if type(self.max_steps) is not int or self.max_steps <= 0:
            raise ValueError("max_steps must be a positive integer")
        for name, value in (
            ("step_timeout_seconds", self.step_timeout_seconds),
            ("run_timeout_seconds", self.run_timeout_seconds),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name} must be finite and positive")
        require_text(self.system_prompt, "system_prompt")

    def context_policy(self) -> ContextPolicy:
        from typing import Literal, cast

        return ContextPolicy(
            self.context_budget_bytes,
            self.tool_output_bytes,
            cast(Literal["recent", "compact"], self.context_strategy),
        )


type Authorize = Callable[[UUID, str, str, str], Coroutine[object, object, bool]]


class FailureCode(StrEnum):
    APPROVAL_DENIED = "APPROVAL_DENIED"
    CONTEXT_LIMIT = "CONTEXT_LIMIT"
    STEP_LIMIT = "STEP_LIMIT"
    STEP_TIMEOUT = "STEP_TIMEOUT"
    RUN_DEADLINE = "RUN_DEADLINE"
    MODEL_ERROR = "MODEL_ERROR"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    UNSUPPORTED_TOOL = "UNSUPPORTED_TOOL"
    TOOL_UNCERTAIN = "TOOL_UNCERTAIN"


@dataclass(frozen=True)
class Failure:
    code: FailureCode
    detail: str


@dataclass(frozen=True)
class StepRecord:
    request: ModelRequest
    response: ModelResponse | None
    failure: Failure | None = None
    cancelled: bool = False


@dataclass(frozen=True)
class StateChange:
    source: RunStatus
    target: RunStatus


@dataclass(frozen=True)
class RunBinding:
    run_id: UUID
    attempt_id: UUID


@dataclass(frozen=True)
class RunResult:
    run_id: UUID
    attempt_id: UUID
    task: str
    config: AgentConfig
    status: RunStatus
    output: str | None
    failure: Failure | None
    steps: tuple[StepRecord, ...]
    transitions: tuple[StateChange, ...]
    tool_executions: tuple[ToolExecution, ...] = ()


class _RunCancelled(Exception):
    pass


class _CallTimedOut(Exception):
    pass


class _ModelCancelled(RuntimeError):
    pass


async def _await_operation[T](
    operation: Coroutine[object, object, T], timeout: float, cancellation: asyncio.Event
) -> T:
    """Race model I/O against cancellation/time; always join child tasks."""
    response_task = asyncio.create_task(operation, name="kairo-operation")
    cancellation_task = asyncio.create_task(cancellation.wait(), name="kairo-cancellation-wait")
    tasks = (response_task, cancellation_task)
    try:
        done, _ = await asyncio.wait(tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        # Cancellation wins a simultaneous response/cancellation race.
        if cancellation.is_set():
            raise _RunCancelled
        if not done:
            raise _CallTimedOut
        if response_task.cancelled():
            raise _ModelCancelled("Adapter cancelled its own request")
        return response_task.result()
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _run_agent(
    task: str,
    model: Model,
    config: AgentConfig | None = None,
    *,
    cancellation: asyncio.Event | None = None,
    tools: ToolRegistry | None = None,
    tool_context: ToolContext | None = None,
    recorder: Recorder | None = None,
    binding: RunBinding | None = None,
    resume: KernelSnapshot | None = None,
    authorize: Authorize | None = None,
) -> RunResult:
    """Execute a fresh run. Invalid caller inputs raise; execution failures return FAILED.

    Event cancellation returns CANCELLED. Cancelling the caller's asyncio Task
    propagates CancelledError after child cleanup, following Python's convention.
    Adapters must be cooperative; this is not process isolation.
    """
    require_text(task, "task")
    if resume is not None and binding is None:
        raise ValueError("Resume requires an explicitly bound existing attempt")
    if tools is not None and tool_context is None:
        raise ValueError("A tool registry requires a workspace context")
    config = config if config is not None else AgentConfig()
    cancellation = cancellation if cancellation is not None else asyncio.Event()
    if binding is not None and recorder is None:
        raise ValueError("An existing run binding requires a recorder")
    run_id, attempt_id = (binding.run_id, binding.attempt_id) if binding else (uuid4(), uuid4())
    status = RunStatus.QUEUED if binding else RunStatus.CREATED
    changes: list[StateChange] = []
    steps: list[StepRecord] = []
    executions: list[ToolExecution] = []
    messages: tuple[Message, ...] = (Message("system", config.system_prompt), Message("user", task))
    if resume is not None:
        messages = resume.messages
    budget_seconds = (
        min(config.run_timeout_seconds, resume.remaining_seconds)
        if resume
        else config.run_timeout_seconds
    )
    deadline = monotonic() + budget_seconds

    def snapshot(next_step: int, final_output: str | None = None) -> dict[str, object] | None:
        remaining = deadline - monotonic()
        if remaining <= 0:
            return None
        return KernelSnapshot(
            messages=messages,
            next_step=next_step,
            remaining_seconds=remaining,
            final_output=final_output,
        ).model_dump(mode="json")

    async def checkpoint(next_step: int, final_output: str | None = None) -> None:
        state = snapshot(next_step, final_output)
        if state is not None:
            await emit("checkpoint_created", state)

    async def emit(kind: str, payload: dict[str, object]) -> None:
        if recorder is not None:
            await recorder.record(
                event_now(run_id, attempt_id, kind, json.dumps(payload, default=str))
            )

    async def move(target: RunStatus, extra: dict[str, object] | None = None) -> None:
        nonlocal status
        source = status
        validated = transition(source, target)
        await emit("state_transition", {"source": source, "target": target, **(extra or {})})
        status = validated
        changes.append(StateChange(source, target))

    async def finish(
        target: RunStatus, failure: Failure | None = None, output: str | None = None
    ) -> RunResult:
        await move(target, {"output": output, "failure": asdict(failure) if failure else None})
        return RunResult(
            run_id,
            attempt_id,
            task,
            config,
            status,
            output,
            failure,
            tuple(steps),
            tuple(changes),
            tuple(executions),
        )

    if recorder is not None:
        await recorder.start(
            run_id, attempt_id, task, json.dumps(asdict(config)), type(model).__name__
        )
    try:
        if cancellation.is_set():
            return await finish(RunStatus.CANCELLED)
        if status is RunStatus.CREATED:
            await move(RunStatus.QUEUED)
        await move(RunStatus.RUNNING)
        if resume is not None and resume.final_output is not None:
            return await finish(RunStatus.COMPLETED, output=resume.final_output)
        first_step = resume.next_step if resume else 1
        await checkpoint(first_step)
        for number in range(first_step, config.max_steps + 1):
            if cancellation.is_set():
                return await finish(RunStatus.CANCELLED)
            remaining = deadline - monotonic()
            if remaining <= 0:
                return await finish(
                    RunStatus.FAILED, Failure(FailureCode.RUN_DEADLINE, "Run deadline exhausted")
                )
            schemas = tools.schemas_json() if tools else "[]"
            try:
                view = assemble(messages, schemas, config.context_policy())
            except ContextOverflow:
                return await finish(
                    RunStatus.FAILED,
                    Failure(FailureCode.CONTEXT_LIMIT, "Pinned instructions exceed context budget"),
                )
            await emit(
                "context_assembled",
                {
                    "step": number,
                    "unit": "utf8_bytes",
                    "strategy": config.context_strategy,
                    "original_bytes": view.original_bytes,
                    "supplied_bytes": view.supplied_bytes,
                    "omitted_messages": view.omitted_messages,
                    "trimmed_tools": view.trimmed_tools,
                    "history_sha256": view.history_sha256,
                    "history_reference": {"run_id": str(run_id), "through_step": number - 1},
                },
            )
            request = ModelRequest(view.messages, number, schemas)
            started = monotonic()
            failure: Failure | None = None
            await emit(
                "model_request",
                {**asdict(request), "history_messages": [asdict(m) for m in messages]},
            )
            available = min(
                deadline - monotonic(), config.step_timeout_seconds - (monotonic() - started)
            )
            if available <= 0:
                code = (
                    FailureCode.RUN_DEADLINE
                    if monotonic() >= deadline
                    else FailureCode.STEP_TIMEOUT
                )
                return await finish(
                    RunStatus.FAILED, Failure(code, "Request recording exhausted budget")
                )
            try:
                response = await _await_operation(model.generate(request), available, cancellation)
            except _RunCancelled:
                steps.append(StepRecord(request, None, cancelled=True))
                return await finish(RunStatus.CANCELLED)
            except _CallTimedOut:
                code = (
                    FailureCode.RUN_DEADLINE
                    if remaining <= config.step_timeout_seconds
                    else FailureCode.STEP_TIMEOUT
                )
                failure = Failure(code, "Model request exceeded its execution budget")
            except Exception as exc:
                # Do not put arbitrary exception text (which may contain credentials) in records.
                failure = Failure(FailureCode.MODEL_ERROR, type(exc).__name__)
            if failure is not None:
                steps.append(StepRecord(request, None, failure))
                await emit("model_failed", asdict(failure))
                return await finish(RunStatus.FAILED, failure)
            # Reject responses returned after budget expiry, including delayed cleanup.
            if monotonic() >= deadline:
                failure = Failure(FailureCode.RUN_DEADLINE, "Run deadline exhausted")
            elif monotonic() - started >= config.step_timeout_seconds:
                failure = Failure(FailureCode.STEP_TIMEOUT, "Step deadline exhausted")
            elif not isinstance(response, (Continue, Final, ToolRequest)):
                failure = Failure(
                    FailureCode.INVALID_RESPONSE, "Expected a structured model response"
                )
            if failure is not None:
                steps.append(StepRecord(request, None, failure))
                await emit("model_failed", asdict(failure))
                return await finish(RunStatus.FAILED, failure)
            usage = getattr(model, "last_usage", None)
            await emit(
                "model_response",
                {"type": type(response).__name__, **asdict(response), "provider_usage": usage},
            )
            if isinstance(response, ToolRequest):
                if tools is None or tool_context is None:
                    failure = Failure(FailureCode.UNSUPPORTED_TOOL, "No tool registry was supplied")
                    steps.append(StepRecord(request, response, failure))
                    return await finish(RunStatus.FAILED, failure)
                steps.append(StepRecord(request, response))
                invocation_id = uuid4()
                if authorize is not None and tools.side_effect(response.name) != "read_only":
                    await move(RunStatus.WAITING_FOR_APPROVAL)
                    try:
                        granted = await _await_operation(
                            authorize(
                                invocation_id,
                                response.name,
                                response.arguments_json,
                                str(tools.side_effect(response.name)),
                            ),
                            max(0, deadline - monotonic()),
                            cancellation,
                        )
                    except ValueError:
                        return await finish(
                            RunStatus.FAILED,
                            Failure(FailureCode.INVALID_RESPONSE, "Invalid approval action"),
                        )
                    except _RunCancelled:
                        return await finish(RunStatus.CANCELLED)
                    except _CallTimedOut:
                        return await finish(
                            RunStatus.FAILED,
                            Failure(FailureCode.RUN_DEADLINE, "Approval wait exhausted run budget"),
                        )
                    if not granted:
                        return await finish(
                            RunStatus.FAILED,
                            Failure(FailureCode.APPROVAL_DENIED, "Action was denied"),
                        )
                    await move(RunStatus.RUNNING)
                    # Human waiting counts against the run budget, not the tool step budget.
                    started = monotonic()
                await move(RunStatus.WAITING_FOR_TOOL)
                await emit(
                    "tool_requested",
                    {
                        "id": str(invocation_id),
                        "name": response.name,
                        "input_json": response.arguments_json,
                        "side_effect": tools.side_effect(response.name),
                    },
                )

                # Capture validated context before entering the child coroutine.
                async def invoke(
                    registry: ToolRegistry,
                    context: ToolContext,
                    tool_response: ToolRequest,
                    call_id: UUID,
                ) -> ToolExecution:
                    await emit("tool_started", {"id": str(call_id)})
                    record = await registry.invoke(
                        tool_response.name,
                        tool_response.arguments_json,
                        context,
                        invocation_id=call_id,
                    )
                    executions.append(record)
                    await emit("tool_finished", asdict(record))
                    return record

                budget = min(
                    deadline - monotonic(), config.step_timeout_seconds - (monotonic() - started)
                )
                if budget <= 0:
                    code = (
                        FailureCode.RUN_DEADLINE
                        if monotonic() >= deadline
                        else FailureCode.STEP_TIMEOUT
                    )
                    return await finish(RunStatus.FAILED, Failure(code, "Tool budget exhausted"))
                try:
                    record = await _await_operation(
                        invoke(tools, tool_context, response, invocation_id), budget, cancellation
                    )
                except _RunCancelled:
                    return await finish(RunStatus.CANCELLED)
                except _CallTimedOut:
                    code = (
                        FailureCode.RUN_DEADLINE
                        if monotonic() >= deadline
                        else FailureCode.STEP_TIMEOUT
                    )
                    return await finish(RunStatus.FAILED, Failure(code, "Tool budget exhausted"))
                if monotonic() >= deadline:
                    return await finish(
                        RunStatus.FAILED,
                        Failure(FailureCode.RUN_DEADLINE, "Run deadline exhausted"),
                    )
                if monotonic() - started >= config.step_timeout_seconds:
                    return await finish(
                        RunStatus.FAILED,
                        Failure(FailureCode.STEP_TIMEOUT, "Step deadline exhausted"),
                    )
                if record.outcome_uncertain:
                    return await finish(
                        RunStatus.FAILED,
                        Failure(
                            FailureCode.TOOL_UNCERTAIN, "Tool side effect requires reconciliation"
                        ),
                    )
                messages += (
                    Message(
                        "assistant",
                        json.dumps({"tool": response.name, "arguments": response.arguments_json}),
                    ),
                    Message(
                        "tool",
                        json.dumps(
                            {
                                "name": record.name,
                                "status": record.status,
                                "output": json.loads(record.output_json)
                                if record.output_json
                                else None,
                                "error_code": record.error_code,
                            }
                        ),
                    ),
                )
                await move(RunStatus.RUNNING, {"checkpoint": snapshot(number + 1)})
                continue
            steps.append(StepRecord(request, response))
            messages += (Message("assistant", response.text),)
            if isinstance(response, Final):
                await checkpoint(number, response.text)
                return await finish(RunStatus.COMPLETED, output=response.text)
            await checkpoint(number + 1)
        return await finish(
            RunStatus.FAILED, Failure(FailureCode.STEP_LIMIT, "Maximum model calls reached")
        )
    except asyncio.CancelledError:
        if status not in TERMINAL_STATES:
            await finish(RunStatus.CANCELLED)
        raise


async def run_agent(
    task: str,
    model: Model,
    config: AgentConfig | None = None,
    *,
    cancellation: asyncio.Event | None = None,
    tools: ToolRegistry | None = None,
    tool_context: ToolContext | None = None,
    recorder: Recorder | None = None,
    binding: RunBinding | None = None,
    resume: KernelSnapshot | None = None,
    authorize: Authorize | None = None,
) -> RunResult:
    """Instrument a bounded kernel execution without changing its execution contracts."""
    from kairo_core.observability import TraceRecorder

    if binding is not None and recorder is None:
        raise ValueError("An existing run binding requires a recorder")
    traced = recorder if isinstance(recorder, TraceRecorder) else TraceRecorder(recorder)
    try:
        return await _run_agent(
            task,
            model,
            config,
            cancellation=cancellation,
            tools=tools,
            tool_context=tool_context,
            recorder=traced,
            binding=binding,
            resume=resume,
            authorize=authorize,
        )
    finally:
        traced.close()
