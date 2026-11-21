"""Run one local worker; Ctrl-C cancels and cleans up its current executions."""

import argparse
import asyncio
import os
import signal
from pathlib import Path
from uuid import UUID

from kairo_core.orchestration.queue import Queue
from kairo_core.orchestration.worker import Worker
from kairo_core.persistence.repository import RunRepository


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(".kairo/workspaces"))
    parser.add_argument("--capacity", type=int, default=1)
    parser.add_argument("--lease-seconds", type=float, default=30)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--run-id", type=UUID, help="Target one queued run with --once")
    args = parser.parse_args()
    if args.run_id and not args.once:
        parser.error("--run-id requires --once")
    repo = RunRepository.from_url(os.environ["KAIRO_DATABASE_URL"])
    worker = Worker(Queue(repo, args.lease_seconds), args.root, capacity=args.capacity)
    try:
        if args.once:
            await worker.work_once(args.run_id)
        else:
            stop = asyncio.Event()
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, stop.set)
            await worker.run(stop)
    finally:
        await repo.close()


if __name__ == "__main__":
    asyncio.run(main())
