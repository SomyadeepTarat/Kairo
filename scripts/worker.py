"""Run one local worker; Ctrl-C cancels and cleans up its current executions."""

import argparse
import asyncio
import os
import signal
from pathlib import Path

from kairo_core.orchestration.queue import Queue
from kairo_core.orchestration.worker import Worker
from kairo_core.persistence.repository import RunRepository


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(".kairo/workspaces"))
    parser.add_argument("--capacity", type=int, default=1)
    parser.add_argument("--lease-seconds", type=float, default=30)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    repo = RunRepository.from_url(os.environ["KAIRO_DATABASE_URL"])
    worker = Worker(Queue(repo, args.lease_seconds), args.root, capacity=args.capacity)
    try:
        if args.once:
            await worker.work_once()
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
