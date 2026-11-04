"""Configuration and model-boundary validation."""

import asyncio
from typing import cast

import pytest
from kairo_core.models import Continue, Final, Message, ModelRequest, ScriptedModel, ScriptExhausted
from kairo_core.runtime import AgentConfig


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "3"])
def test_invalid_step_count(value: object) -> None:
    with pytest.raises(ValueError):
        AgentConfig(max_steps=cast(int, value))


@pytest.mark.parametrize("value", [0, -1, True, float("nan"), float("inf"), "30"])
@pytest.mark.parametrize("field", ["step_timeout_seconds", "run_timeout_seconds"])
def test_invalid_time_budget(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        if field == "step_timeout_seconds":
            AgentConfig(step_timeout_seconds=cast(float, value))
        else:
            AgentConfig(run_timeout_seconds=cast(float, value))


def test_empty_system_prompt() -> None:
    with pytest.raises(ValueError):
        AgentConfig(system_prompt=" ")


@pytest.mark.parametrize("value", ["", "  ", None, 42])
def test_invalid_response_text(value: object) -> None:
    with pytest.raises(ValueError):
        Final(cast(str, value))
    with pytest.raises(ValueError):
        Continue(cast(str, value))


def test_script_exhaustion_is_an_error() -> None:
    model = ScriptedModel(())
    with pytest.raises(ScriptExhausted):
        asyncio.run(model.generate(ModelRequest((Message("user", "task"),), 1)))
