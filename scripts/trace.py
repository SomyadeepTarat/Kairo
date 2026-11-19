"""Print durable measured trace data; no collector required."""

import argparse
import asyncio
import json
import os
from uuid import UUID

from kairo_core.observability import inspect_trace
from kairo_core.persistence.repository import RunRepository


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", type=UUID)
    args = parser.parse_args()
    repo = RunRepository.from_url(os.environ["KAIRO_DATABASE_URL"])
    try:
        result = await inspect_trace(repo, args.run_id)
        if result is None:
            raise SystemExit("Run not found")
        print(json.dumps(result, default=str, indent=2))
    finally:
        await repo.close()


if __name__ == "__main__":
    asyncio.run(main())
