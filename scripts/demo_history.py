"""Run a scripted model with real file tools/PostgreSQL, or inspect a prior run."""

import argparse
import asyncio
import json
import os
import tempfile
from pathlib import Path
from uuid import UUID

from kairo_core.models import Final, ScriptedModel, ToolRequest
from kairo_core.persistence.repository import RunRepository
from kairo_core.runtime import run_agent
from kairo_core.state import RunStatus
from kairo_core.tools import builtin_registry
from kairo_core.tools.registry import ToolContext


async def demo(inspect_id: UUID | None = None) -> int:
    url = os.environ.get("KAIRO_DATABASE_URL")
    if not url:
        raise ValueError("Set KAIRO_DATABASE_URL and run alembic upgrade head first")
    repo = RunRepository.from_url(url)
    try:
        if inspect_id is not None:
            row = await repo.get_run(inspect_id)
            if row is None:
                print(json.dumps({"error": "Run not found"}))
                return 1
            print(
                json.dumps(
                    {
                        "run": row,
                        "events": await repo.events(inspect_id, limit=1000),
                        "tools": await repo.tools(inspect_id),
                    },
                    default=str,
                    indent=2,
                )
            )
            return 0
        with tempfile.TemporaryDirectory(prefix="kairo-history-") as directory:
            result = await run_agent(
                "Write and read a file, retaining its execution history",
                ScriptedModel(
                    (
                        ToolRequest("write_file", '{"path":"hello.txt","content":"durable hello"}'),
                        ToolRequest("read_file", '{"path":"hello.txt"}'),
                        Final("Script finished; recorded file results provide evidence."),
                    )
                ),
                tools=builtin_registry(),
                tool_context=ToolContext(
                    Path(directory), frozenset({"workspace.read", "workspace.write"})
                ),
                recorder=repo,
            )
        print(
            json.dumps(
                {
                    "mode": "scripted_model_real_files_real_postgresql",
                    "run_id": str(result.run_id),
                    "status": result.status,
                    "events_recorded": len(await repo.events(result.run_id, limit=1000)),
                    "tool_calls": len(await repo.tools(result.run_id)),
                },
                indent=2,
            )
        )
        return 0 if result.status is RunStatus.COMPLETED else 1
    finally:
        await repo.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inspect", type=UUID, help="Read a previously persisted run in this process"
    )
    arguments = parser.parse_args()
    raise SystemExit(asyncio.run(demo(arguments.inspect)))
