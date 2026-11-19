"""Submit/inspect/advance a durable workflow; run drives local workers too."""

import argparse
import asyncio
import json
import os
from pathlib import Path
from time import monotonic
from uuid import UUID

from kairo_core.orchestration.queue import Queue
from kairo_core.orchestration.worker import Worker
from kairo_core.orchestration.workflows import Workflows, WorkflowSpec
from kairo_core.persistence.repository import RunRepository


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["submit", "advance", "inspect", "run"])
    parser.add_argument("target", help="JSON path for submit/run; workflow UUID otherwise")
    parser.add_argument("--root", type=Path, default=Path(".kairo/workspaces"))
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    repo = RunRepository.from_url(os.environ["KAIRO_DATABASE_URL"])
    queue = Queue(repo)
    workflows = Workflows(queue)
    try:
        if args.action in {"submit", "run"}:
            identity = await workflows.submit(
                WorkflowSpec.model_validate_json(Path(args.target).read_text())
            )
        else:
            identity = UUID(args.target)
        if args.action == "run":
            worker = Worker(queue, args.root)
            deadline = monotonic() + args.timeout
            while monotonic() < deadline:
                await workflows.advance(identity)
                row = await workflows.get(identity)
                assert row is not None
                if row["status"] in {"COMPLETED", "FAILED"}:
                    break
                await worker.work_once()
                await asyncio.sleep(0.05)
            else:
                raise TimeoutError(f"Workflow {identity} remains durable; inspect or advance later")
        elif args.action == "advance":
            await workflows.advance(identity)
        print(json.dumps(await workflows.get(identity), default=str, indent=2))
    finally:
        await repo.close()


if __name__ == "__main__":
    asyncio.run(main())
