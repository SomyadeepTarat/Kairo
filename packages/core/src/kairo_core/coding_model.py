"""Application-orchestrated coding workflow: deterministic evidence collection, real model patch."""

import json
from dataclasses import replace

from kairo_core.models import ModelRequest, ModelResponse, ToolRequest
from kairo_core.ollama import OllamaModel, ProviderTool
from kairo_core.orchestration.spec import ContinueStep, FinalStep

TEST_ARGV = ["python", "-m", "unittest", "-v"]


class CodingWorkflowModel:
    """A staged application adapter, explicitly not an unconstrained autonomous model.

    No repair content is supplied by this class. The local model generates the full
    replacement source; unchanged external tests decide whether it is correct.
    """

    def __init__(self, model: str) -> None:
        self.model = model
        self.last_usage: dict[str, int] | None = None

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.last_usage = None
        if request.step in {1, 2}:
            return ToolRequest(
                "read_file",
                json.dumps(
                    {"path": "calculator.py" if request.step == 1 else "test_calculator.py"}
                ),
            )
        if request.step == 3 or (request.step >= 5 and (request.step - 5) % 3 == 1):
            return ToolRequest("execute_command", json.dumps({"argv": TEST_ARGV}))
        if request.step >= 5 and (request.step - 5) % 3 == 2:
            return ToolRequest("git_diff", "{}")
        passed = False
        for message in reversed(request.messages):
            if message.role == "tool":
                try:
                    record = json.loads(message.content)
                except ValueError:
                    continue
                if record.get("name") == "execute_command":
                    output = record.get("output")
                    passed = isinstance(output, dict) and output.get("returncode") == 0
                    break
        if request.step == 4:
            schema = ContinueStep.model_json_schema()
            instruction = (
                "Propose a concise repair based on actual source and failing tests. "
                "Return kind continue."
            )
        elif request.step > 5 and passed:
            schema = FinalStep.model_json_schema()
            instruction = (
                "Review the actual patch and passing test evidence. Return a concise final result."
            )
        else:
            schema = ProviderTool.model_json_schema()
            schema["properties"]["name"] = {"type": "string", "const": "write_file"}
            schema["properties"]["arguments"] = {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "const": "calculator.py"},
                    "content": {"type": "string", "minLength": 1},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            }
            instruction = (
                "Generate the complete corrected calculator.py now, preserving its public API "
                "and CLI. Return kind tool, name write_file, and arguments as an OBJECT "
                "containing path calculator.py and content with the full source. "
                "Do not merely describe the fix. Do not modify tests. Use failing test evidence to "
                "correct the logic. No source/patch is pre-supplied by the harness."
            )
        from kairo_core.models import Message

        messages = (
            Message(
                "system", request.messages[0].content + "\nCurrent workflow phase: " + instruction
            ),
        ) + request.messages[1:]
        adapter = OllamaModel(self.model, response_schema=schema)
        response = await adapter.generate(replace(request, messages=messages))
        self.last_usage = adapter.last_usage
        return response
