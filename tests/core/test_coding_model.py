"""Staged application contract uses labelled model fixtures; never live inference in unit tests."""

import asyncio
import json

import pytest
from kairo_core.coding_model import CodingWorkflowModel
from kairo_core.models import Final, Message, ModelRequest, ToolRequest
from kairo_core.ollama import OllamaModel


def test_collects_evidence_then_delegates_patch_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: list[dict[str, object] | None] = []

    async def fixture_generate(self: OllamaModel, request: ModelRequest) -> ToolRequest:
        observed.append(self.response_schema)
        return ToolRequest(
            "write_file",
            json.dumps({"path": "calculator.py", "content": "fixture generated source"}),
        )

    monkeypatch.setattr(OllamaModel, "generate", fixture_generate)

    async def scenario() -> None:
        model = CodingWorkflowModel("fixture-only")
        messages = (Message("system", "execute"), Message("user", "repair"))
        first = await model.generate(ModelRequest(messages, 1))
        assert isinstance(first, ToolRequest) and first.name == "read_file"
        patch = await model.generate(ModelRequest(messages, 5))
        assert isinstance(patch, ToolRequest) and "fixture generated source" in patch.arguments_json
        assert observed[0] and "write_file" in json.dumps(observed[0])

    asyncio.run(scenario())


def test_review_is_reached_only_after_recorded_passing_test(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fixture_generate(self: OllamaModel, request: ModelRequest) -> Final:
        assert self.response_schema
        assert '"const": "final"' in json.dumps(self.response_schema)
        return Final("fixture review")

    monkeypatch.setattr(OllamaModel, "generate", fixture_generate)

    async def scenario() -> None:
        messages = (
            Message("system", "s"),
            Message("user", "u"),
            Message("tool", json.dumps({"name": "execute_command", "output": {"returncode": 0}})),
        )
        result = await CodingWorkflowModel("fixture-only").generate(ModelRequest(messages, 8))
        assert isinstance(result, Final)

    asyncio.run(scenario())
