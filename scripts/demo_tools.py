"""Scripted model, real file tools, disposable workspace; no inference."""

import asyncio
import json
import tempfile
from pathlib import Path

from kairo_core.models import Final, ScriptedModel, ToolRequest
from kairo_core.runtime import run_agent
from kairo_core.state import RunStatus
from kairo_core.tools import builtin_registry
from kairo_core.tools.registry import ToolContext


async def demo() -> int:
    with tempfile.TemporaryDirectory(prefix="kairo-tools-") as directory:
        workspace = Path(directory)
        model = ScriptedModel(
            (
                ToolRequest("write_file", '{"path":"hello.txt","content":"hello kairo"}'),
                ToolRequest("read_file", '{"path":"hello.txt"}'),
                Final("Script finished; inspect recorded tool results for evidence."),
            )
        )
        result = await run_agent(
            "Write and read hello.txt",
            model,
            tools=builtin_registry(),
            tool_context=ToolContext(workspace, frozenset({"workspace.read", "workspace.write"})),
        )
        print(
            json.dumps(
                {
                    "mode": "scripted_model_real_file_tools",
                    "status": result.status,
                    "tool_results": [
                        {"name": item.name, "status": item.status, "output": item.output_json}
                        for item in result.tool_executions
                    ],
                },
                indent=2,
            )
        )
        return 0 if result.status is RunStatus.COMPLETED else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(demo()))
