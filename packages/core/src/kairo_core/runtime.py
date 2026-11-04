"""Single-agent, in-memory execution. No tool dispatch or durable recovery."""

import asyncio
import json
import math
from collections.abc import Coroutine
from dataclasses import dataclass
from enum import StrEnum
from time import monotonic
from uuid import UUID, uuid4

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
from kairo_core.state import RunStatus, transition
from kairo_core.tools.registry import ToolContext, ToolExecution, ToolRegistry


@dataclass(frozen=True)
class AgentConfig:
    max_steps: int = 16
    step_timeout_seconds: float = 30.0
    run_timeout_seconds: float = 120.0
    system_prompt: str = "Complete the task within the supplied execution limits."

    def __post_init__(self) -> None:
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


class FailureCode(StrEnum):
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


async def run_agent(
    task: str,
    model: Model,
    config: AgentConfig | None = None,
    *,
    cancellation: asyncio.Event | None = None,
    tools: ToolRegistry | None = None,
    tool_context: ToolContext | None = None,
) -> RunResult:
    """Execute a fresh run. Invalid caller inputs raise; execution failures return FAILED.

    Event cancellation returns CANCELLED. Cancelling the caller's asyncio Task
    propagates CancelledError after child cleanup, following Python's convention.
    Adapters must be cooperative; this is not process isolation.
    """
    require_text(task, "task")
    if tools is not None and tool_context is None:
        raise ValueError("A tool registry requires a workspace context")
    config = config if config is not None else AgentConfig()
    cancellation = cancellation if cancellation is not None else asyncio.Event()
    run_id, attempt_id = uuid4(), uuid4()
    status = RunStatus.CREATED
    changes: list[StateChange] = []
    steps: list[StepRecord] = []
    executions: list[ToolExecution] = []
    messages: tuple[Message, ...] = (Message("system", config.system_prompt), Message("user", task))
    deadline = monotonic() + config.run_timeout_seconds

    def move(target: RunStatus) -> None:
        nonlocal status
        source = status
        status = transition(source, target)
        changes.append(StateChange(source, target))

    def finish(
        target: RunStatus, failure: Failure | None = None, output: str | None = None
    ) -> RunResult:
        move(target)
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

    if cancellation.is_set():
        return finish(RunStatus.CANCELLED)
    move(RunStatus.QUEUED)
    move(RunStatus.RUNNING)
    for number in range(1, config.max_steps + 1):
        if cancellation.is_set():
            return finish(RunStatus.CANCELLED)
        remaining = deadline - monotonic()
        if remaining <= 0:
            return finish(
                RunStatus.FAILED, Failure(FailureCode.RUN_DEADLINE, "Run deadline exhausted")
            )
        request = ModelRequest(messages, number, tools.schemas_json() if tools else "[]")
        started = monotonic()
        failure: Failure | None = None
        try:
            response = await _await_operation(
                model.generate(request), min(remaining, config.step_timeout_seconds), cancellation
            )
        except _RunCancelled:
            steps.append(StepRecord(request, None, cancelled=True))
            return finish(RunStatus.CANCELLED)
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
            return finish(RunStatus.FAILED, failure)
        # Reject responses returned after budget expiry, including delayed cleanup.
        if monotonic() >= deadline:
            failure = Failure(FailureCode.RUN_DEADLINE, "Run deadline exhausted")
        elif monotonic() - started >= config.step_timeout_seconds:
            failure = Failure(FailureCode.STEP_TIMEOUT, "Step deadline exhausted")
        elif not isinstance(response, (Continue, Final, ToolRequest)):
            failure = Failure(FailureCode.INVALID_RESPONSE, "Expected a structured model response")
        if failure is not None:
            steps.append(StepRecord(request, None, failure))
            return finish(RunStatus.FAILED, failure)
        if isinstance(response, ToolRequest):
            if tools is None or tool_context is None:
                failure = Failure(FailureCode.UNSUPPORTED_TOOL, "No tool registry was supplied")
                steps.append(StepRecord(request, response, failure))
                return finish(RunStatus.FAILED, failure)
            steps.append(StepRecord(request, response))
            move(RunStatus.WAITING_FOR_TOOL)

            # Capture validated context before entering the child coroutine.
            async def invoke(
                registry: ToolRegistry, context: ToolContext, tool_response: ToolRequest
            ) -> ToolExecution:
                record = await registry.invoke(
                    tool_response.name, tool_response.arguments_json, context
                )
                executions.append(record)
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
                return finish(RunStatus.FAILED, Failure(code, "Tool budget exhausted"))
            try:
                record = await _await_operation(
                    invoke(tools, tool_context, response), budget, cancellation
                )
            except _RunCancelled:
                return finish(RunStatus.CANCELLED)
            except _CallTimedOut:
                code = (
                    FailureCode.RUN_DEADLINE
                    if monotonic() >= deadline
                    else FailureCode.STEP_TIMEOUT
                )
                return finish(RunStatus.FAILED, Failure(code, "Tool budget exhausted"))
            if monotonic() >= deadline:
                return finish(
                    RunStatus.FAILED, Failure(FailureCode.RUN_DEADLINE, "Run deadline exhausted")
                )
            if monotonic() - started >= config.step_timeout_seconds:
                return finish(
                    RunStatus.FAILED, Failure(FailureCode.STEP_TIMEOUT, "Step deadline exhausted")
                )
            if record.outcome_uncertain:
                return finish(
                    RunStatus.FAILED,
                    Failure(FailureCode.TOOL_UNCERTAIN, "Tool side effect requires reconciliation"),
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
            move(RunStatus.RUNNING)
            continue
        steps.append(StepRecord(request, response))
        messages += (Message("assistant", response.text),)
        if isinstance(response, Final):
            return finish(RunStatus.COMPLETED, output=response.text)
    return finish(RunStatus.FAILED, Failure(FailureCode.STEP_LIMIT, "Maximum model calls reached"))
