"""Deterministic kernel behavior; no live model, service, tool or network."""

import asyncio
from dataclasses import FrozenInstanceError
from typing import cast

import pytest
from kairo_core.models import (
    Continue,
    Final,
    ModelRequest,
    ModelResponse,
    ScriptedModel,
    ToolRequest,
)
from kairo_core.runtime import AgentConfig, FailureCode, RunResult, run_agent
from kairo_core.state import RunStatus


class BlockingModel:
    """Controlled test double with observable start and cancellation cleanup."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.stopped = asyncio.Event()
        self.calls = 0

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.stopped.set()
        raise AssertionError("unreachable")


def assert_failed(result: RunResult, code: FailureCode) -> None:
    assert result.status is RunStatus.FAILED
    assert result.output is None
    assert result.failure is not None
    assert result.failure.code is code


def test_multistep_execution_and_reproduction() -> None:
    model = ScriptedModel((Continue("phase one"), Continue("phase two"), Final("done")))
    config = AgentConfig(max_steps=3, system_prompt="test instructions")
    first = asyncio.run(run_agent("scripted task", model, config))
    second = asyncio.run(run_agent("scripted task", model, config))
    assert first.status is RunStatus.COMPLETED
    assert first.output == "done"
    assert first.failure is None
    assert first.run_id != second.run_id
    assert first.attempt_id != second.attempt_id
    assert first.steps == second.steps
    assert first.transitions == second.transitions
    assert [step.request.step for step in first.steps] == [1, 2, 3]
    assert [message.content for message in first.steps[2].request.messages] == [
        "test instructions",
        "scripted task",
        "phase one",
        "phase two",
    ]
    assert [change.target for change in first.transitions] == [
        RunStatus.QUEUED,
        RunStatus.RUNNING,
        RunStatus.COMPLETED,
    ]
    # A terminal result cannot be resumed or have its status edited.
    with pytest.raises(FrozenInstanceError):
        first.status = RunStatus.RUNNING  # type: ignore[misc]  # Deliberate mutation attempt.


def test_step_limit_stops_before_another_call() -> None:
    model = ScriptedModel((Continue("more"), Final("must not reach")))
    result = asyncio.run(run_agent("task", model, AgentConfig(max_steps=1)))
    assert_failed(result, FailureCode.STEP_LIMIT)
    assert len(result.steps) == 1
    assert result.steps[0].response == Continue("more")


def test_final_response_stops_before_unused_script_entries() -> None:
    result = asyncio.run(run_agent("task", ScriptedModel((Final("done"), Continue("unused")))))
    assert result.status is RunStatus.COMPLETED
    assert len(result.steps) == 1


def test_unsupported_tools_fail_without_entering_tool_state() -> None:
    result = asyncio.run(run_agent("task", ScriptedModel((ToolRequest("shell", "{}"),))))
    assert_failed(result, FailureCode.UNSUPPORTED_TOOL)
    assert all(change.target is not RunStatus.WAITING_FOR_TOOL for change in result.transitions)
    assert result.steps[0].response == ToolRequest("shell", "{}")


def test_exhausted_script_does_not_fabricate_success() -> None:
    result = asyncio.run(run_agent("task", ScriptedModel((Continue("more"),))))
    assert_failed(result, FailureCode.MODEL_ERROR)
    assert result.failure is not None
    assert result.failure.detail == "ScriptExhausted"
    assert len(result.steps) == 2
    assert result.steps[-1].failure == result.failure


def test_invalid_adapter_response_is_rejected() -> None:
    class InvalidModel:
        async def generate(self, request: ModelRequest) -> ModelResponse:
            return cast(ModelResponse, {"text": "not a structured response"})

    result = asyncio.run(run_agent("task", InvalidModel()))
    assert_failed(result, FailureCode.INVALID_RESPONSE)


def test_model_exception_is_reported_without_sensitive_exception_text() -> None:
    class BrokenModel:
        async def generate(self, request: ModelRequest) -> ModelResponse:
            raise RuntimeError("secret=must-not-appear")

    result = asyncio.run(run_agent("task", BrokenModel()))
    assert_failed(result, FailureCode.MODEL_ERROR)
    assert "must-not-appear" not in repr(result)


def test_pre_cancelled_run_never_invokes_model() -> None:
    async def scenario() -> None:
        model = BlockingModel()
        cancelled = asyncio.Event()
        cancelled.set()
        result = await run_agent("task", model, cancellation=cancelled)
        assert result.status is RunStatus.CANCELLED
        assert not result.steps
        assert model.calls == 0
        assert result.transitions[0].source is RunStatus.CREATED

    asyncio.run(scenario())


def test_inflight_cancellation_joins_model_cleanup() -> None:
    async def scenario() -> None:
        model = BlockingModel()
        cancellation = asyncio.Event()
        execution = asyncio.create_task(run_agent("task", model, cancellation=cancellation))
        await model.started.wait()
        cancellation.set()
        result = await execution
        assert result.status is RunStatus.CANCELLED
        assert result.failure is None
        assert result.steps[0].cancelled
        assert model.stopped.is_set()
        assert model.calls == 1
        assert not [task for task in asyncio.all_tasks() if task.get_name().startswith("kairo-")]

    asyncio.run(asyncio.wait_for(scenario(), timeout=2))


def test_cancellation_wins_simultaneous_final_response() -> None:
    async def scenario() -> None:
        cancellation = asyncio.Event()

        class CancellingModel:
            async def generate(self, request: ModelRequest) -> ModelResponse:
                cancellation.set()
                return Final("late result")

        result = await run_agent("task", CancellingModel(), cancellation=cancellation)
        assert result.status is RunStatus.CANCELLED
        assert result.output is None

    asyncio.run(scenario())


def test_caller_task_cancellation_propagates_after_cleanup() -> None:
    async def scenario() -> None:
        model = BlockingModel()
        execution = asyncio.create_task(run_agent("task", model))
        await model.started.wait()
        execution.cancel()
        with pytest.raises(asyncio.CancelledError):
            await execution
        assert model.stopped.is_set()
        assert not [task for task in asyncio.all_tasks() if task.get_name().startswith("kairo-")]

    asyncio.run(asyncio.wait_for(scenario(), timeout=2))


@pytest.mark.parametrize(
    "config, expected",
    [
        (AgentConfig(step_timeout_seconds=0.01, run_timeout_seconds=1), FailureCode.STEP_TIMEOUT),
        (AgentConfig(step_timeout_seconds=1, run_timeout_seconds=0.01), FailureCode.RUN_DEADLINE),
    ],
)
def test_timeout_cancels_and_joins_active_request(
    config: AgentConfig, expected: FailureCode
) -> None:
    async def scenario() -> None:
        model = BlockingModel()
        result = await run_agent("task", model, config)
        assert_failed(result, expected)
        assert model.stopped.is_set()
        assert model.calls == 1
        assert result.steps[0].failure == result.failure
        assert not [task for task in asyncio.all_tasks() if task.get_name().startswith("kairo-")]

    asyncio.run(asyncio.wait_for(scenario(), timeout=2))


def test_overall_budget_is_shared_across_steps() -> None:
    async def scenario() -> None:
        class SecondCallBlocks:
            async def generate(self, request: ModelRequest) -> ModelResponse:
                if request.step == 1:
                    return Continue("next")
                await asyncio.Event().wait()
                raise AssertionError("unreachable")

        result = await run_agent(
            "task",
            SecondCallBlocks(),
            AgentConfig(step_timeout_seconds=1, run_timeout_seconds=0.02),
        )
        assert_failed(result, FailureCode.RUN_DEADLINE)
        assert len(result.steps) == 2

    asyncio.run(asyncio.wait_for(scenario(), timeout=2))


def test_invalid_task_is_a_caller_error() -> None:
    with pytest.raises(ValueError):
        asyncio.run(run_agent(" ", ScriptedModel((Final("unused"),))))


def test_self_cancelled_adapter_is_a_model_failure() -> None:
    class SelfCancellingModel:
        async def generate(self, request: ModelRequest) -> ModelResponse:
            raise asyncio.CancelledError

    result = asyncio.run(run_agent("task", SelfCancellingModel()))
    assert_failed(result, FailureCode.MODEL_ERROR)


def test_shared_deadline_does_not_reset_for_each_step(monkeypatch: pytest.MonkeyPatch) -> None:
    # Advance only the kernel's clock; asyncio's timer clock is left untouched.
    now = 0.0
    monkeypatch.setattr("kairo_core.runtime.monotonic", lambda: now)

    class ClockAdvancingModel:
        async def generate(self, request: ModelRequest) -> ModelResponse:
            nonlocal now
            now += 0.6
            return Continue("next") if request.step == 1 else Final("too late")

    result = asyncio.run(
        run_agent(
            "task",
            ClockAdvancingModel(),
            AgentConfig(run_timeout_seconds=1, step_timeout_seconds=1),
        )
    )
    assert_failed(result, FailureCode.RUN_DEADLINE)
    assert len(result.steps) == 2


def test_late_model_response_is_not_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 0.0
    monkeypatch.setattr("kairo_core.runtime.monotonic", lambda: now)

    class LateModel:
        async def generate(self, request: ModelRequest) -> ModelResponse:
            nonlocal now
            now = 2.0
            return Final("too late")

    result = asyncio.run(
        run_agent("task", LateModel(), AgentConfig(step_timeout_seconds=1, run_timeout_seconds=10))
    )
    assert_failed(result, FailureCode.STEP_TIMEOUT)


def test_cancellation_is_isolated_between_concurrent_runs() -> None:
    async def scenario() -> None:
        blocked = BlockingModel()
        cancellation = asyncio.Event()
        execution = asyncio.create_task(run_agent("cancel me", blocked, cancellation=cancellation))
        await blocked.started.wait()
        completed = await run_agent("finish me", ScriptedModel((Final("done"),)))
        cancellation.set()
        cancelled = await execution
        assert completed.status is RunStatus.COMPLETED
        assert cancelled.status is RunStatus.CANCELLED
        assert completed.run_id != cancelled.run_id

    asyncio.run(asyncio.wait_for(scenario(), timeout=2))
