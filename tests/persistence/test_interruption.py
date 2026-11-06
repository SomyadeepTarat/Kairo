"""A terminated execution retains history; it is not automatically resumed (M6)."""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from kairo_core.persistence.repository import RunRepository
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.postgres

CHILD = """
import asyncio, os, sys
from pathlib import Path
from kairo_core.models import ScriptedModel, ToolRequest
from kairo_core.persistence.repository import RunRepository
from kairo_core.runtime import run_agent
from kairo_core.tools.registry import Schema, Tool, ToolRegistry, ToolContext, SideEffect

class Input(Schema):
    pass

async def partial(value, context):
    (context.workspace / "partial.txt").write_text("confirmed filesystem change")
    Path(sys.argv[1]).write_text("ready")
    await asyncio.Event().wait()
    return Input()

async def main():
    repo = RunRepository.from_url(os.environ["KAIRO_DATABASE_URL"])
    registry = ToolRegistry()
    registry.register(Tool("partial", "controlled interruption test", Input, Input,
        partial, "workspace.write", SideEffect.WORKSPACE_WRITE))
    await run_agent("interruption test", ScriptedModel((ToolRequest("partial", "{}"),)),
        tools=registry, tool_context=ToolContext(Path(sys.argv[2]), frozenset({"workspace.write"})),
        recorder=repo)

asyncio.run(main())
"""


def test_killed_process_retains_uncertain_tool_and_history(
    database_url: str, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ready = tmp_path / "ready"
    env = {**os.environ, "KAIRO_DATABASE_URL": database_url}
    process = subprocess.Popen(
        [sys.executable, "-c", CHILD, str(ready), str(workspace)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        if not ready.exists():
            process.kill()
            _, errors = process.communicate(timeout=5)
            pytest.fail(f"Controlled child did not reach tool execution: {errors}")
        process.kill()
        process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)

    async def inspect_after_restart() -> None:
        repo = RunRepository(create_async_engine(database_url, poolclass=NullPool))
        runs = await repo.list_runs()
        assert len(runs) == 1
        assert runs[0]["status"] == "WAITING_FOR_TOOL"
        assert runs[0]["completed_at"] is None
        run_id = runs[0]["id"]
        from uuid import UUID

        assert isinstance(run_id, UUID)
        history = await repo.events(run_id)
        assert history[-1]["event_type"] == "tool_started"
        tools = await repo.tools(run_id)
        assert tools[0]["status"] == "STARTED"
        assert tools[0]["outcome_uncertain"] is True
        assert tools[0]["completed_at"] is None
        assert (workspace / "partial.txt").read_text() == "confirmed filesystem change"
        await repo.close()

    asyncio.run(inspect_after_restart())
