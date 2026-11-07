"""Record an operator's explicit proof for one uncertain invocation; never guess it."""

import argparse
import asyncio
import os
from uuid import UUID

from kairo_core.orchestration.queue import Queue
from kairo_core.persistence.repository import RunRepository


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", type=UUID)
    parser.add_argument("invocation_id", type=UUID)
    parser.add_argument("--reason", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--not-executed", action="store_true")
    group.add_argument("--completed-output", help="JSON output that matches the tool's schema")
    args = parser.parse_args()
    repo = RunRepository.from_url(os.environ["KAIRO_DATABASE_URL"])
    try:
        await Queue(repo).reconcile(
            args.run_id,
            args.invocation_id,
            reason=args.reason,
            completed_output=args.completed_output,
            not_executed=args.not_executed,
        )
        print("Resolution recorded; the reaper must verify cleanup before recovery.")
    finally:
        await repo.close()


if __name__ == "__main__":
    asyncio.run(main())
