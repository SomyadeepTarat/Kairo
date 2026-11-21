"""Run the reference coding demonstration. Live Ollama by default; no hidden downloads."""

import argparse
import asyncio
import os
from pathlib import Path

from kairo_core.coding_demo import run_demo
from kairo_core.persistence.repository import RunRepository


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="qwen3:4b")
    parser.add_argument(
        "--scripted",
        action="store_true",
        help="Explicit infrastructure fixture, not live inference",
    )
    parser.add_argument(
        "--approve-demo-actions",
        action="store_true",
        help="Authorize only calculator.py writes and fixed test argv in this isolated task",
    )
    parser.add_argument("--no-crash", action="store_true")
    parser.add_argument("--root", type=Path, default=Path(".kairo/workspaces"))
    parser.add_argument("--output", type=Path, default=Path(".kairo/coding-reports"))
    args = parser.parse_args()
    repo = RunRepository.from_url(os.environ["KAIRO_DATABASE_URL"])
    try:
        report = await run_demo(
            repo,
            root=args.root,
            output=args.output,
            model=args.model,
            scripted=args.scripted,
            auto_approve=args.approve_demo_actions,
            inject_crash=not args.no_crash,
        )
        return 0 if report["oracle_passed"] else 1
    finally:
        await repo.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
