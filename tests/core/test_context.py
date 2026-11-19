"""Context behavior uses deterministic models, never model-dependent claims."""

import asyncio

import pytest
from kairo_core.context import ContextOverflow, ContextPolicy, assemble, size
from kairo_core.models import Continue, Final, Message, ScriptedModel
from kairo_core.runtime import AgentConfig, FailureCode, run_agent

BASE = (Message("system", "instructions"), Message("user", "task"))


@pytest.mark.parametrize("strategy", ["recent", "compact"])
def test_budget_unicode_and_pairs(strategy: str) -> None:
    from typing import Literal, cast

    history = BASE + tuple(
        m
        for _ in range(30)
        for m in (Message("assistant", "tool request"), Message("tool", "界" * 300))
    )
    view = assemble(
        history, "[]", ContextPolicy(600, 100, cast(Literal["recent", "compact"], strategy))
    )
    assert view.supplied_bytes == size(view.messages) <= 600
    assert view.messages[:2] == BASE
    assert view.trimmed_tools == 30 and view.omitted_messages > 0
    assert history[-1].content == "界" * 300
    for i, m in enumerate(view.messages):
        if m.role == "tool":
            assert view.messages[i - 1].role == "assistant"
    assert view.history_sha256 == assemble(history, "[]", ContextPolicy()).history_sha256


def test_schema_cost_and_pinned_overflow() -> None:
    with pytest.raises(ContextOverflow):
        assemble(BASE, "x" * 300, ContextPolicy(256))
    with pytest.raises(ValueError, match="Orphan"):
        assemble(BASE + (Message("tool", "orphan"),), "[]", ContextPolicy())


@pytest.mark.parametrize(
    "kwargs",
    [{"budget_bytes": True}, {"budget_bytes": 255}, {"tool_bytes": 63}, {"strategy": "invented"}],
)
def test_invalid_policy(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        ContextPolicy(**kwargs)  # type: ignore[arg-type]


def test_long_run_and_explicit_failure() -> None:
    async def scenario() -> None:
        result = await run_agent(
            "task",
            ScriptedModel(tuple([Continue("x" * 250)] * 20 + [Final("ok")])),
            AgentConfig(max_steps=21, context_budget_bytes=600),
        )
        assert result.output == "ok"
        assert all(size(s.request.messages) <= 600 for s in result.steps)
        result = await run_agent(
            "x" * 1000,
            ScriptedModel((Final("unreachable"),)),
            AgentConfig(context_budget_bytes=256),
        )
        assert result.failure and result.failure.code == FailureCode.CONTEXT_LIMIT
        assert not result.steps

    asyncio.run(scenario())
