"""Submit an explicit scripted job JSON file to the durable local queue."""

import argparse
import asyncio
import os
from pathlib import Path

from kairo_core.orchestration.queue import Queue
from kairo_core.orchestration.spec import JobSpec
from kairo_core.persistence.repository import RunRepository


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    args = parser.parse_args()
    spec = JobSpec.model_validate_json(args.spec.read_text())
    repo = RunRepository.from_url(os.environ["KAIRO_DATABASE_URL"])
    try:
        print(await Queue(repo).enqueue(spec))
    finally:
        await repo.close()


if __name__ == "__main__":
    asyncio.run(main())
