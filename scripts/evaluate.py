"""Run or compare fixed local benchmarks; scripted infrastructure and Ollama are labelled."""

import argparse
import asyncio
import json
import os
from pathlib import Path
from uuid import UUID

from kairo_core.evaluation import EvaluationConfig, Evaluations, compare
from kairo_core.persistence.repository import RunRepository


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["run", "execute", "inspect", "compare"])
    parser.add_argument("identities", nargs="*")
    parser.add_argument("--root", type=Path, default=Path(".kairo/evaluations"))
    parser.add_argument("--strategy", choices=["recent", "compact"], default="recent")
    parser.add_argument("--mode", choices=["single", "multi"], default="single")
    parser.add_argument("--no-recovery", action="store_true")
    parser.add_argument("--ollama", metavar="INSTALLED_MODEL")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--cases", nargs="+")
    args = parser.parse_args()
    repo = RunRepository.from_url(os.environ["KAIRO_DATABASE_URL"])
    evaluations = Evaluations(repo, args.root)
    try:
        if args.action == "run":
            config = {
                "strategy": args.strategy,
                "mode": args.mode,
                "recovery": not args.no_recovery,
                "backend": "ollama" if args.ollama else "scripted",
                "model": args.ollama or "",
                "repetitions": args.repetitions,
            }
            if args.cases:
                config["cases"] = args.cases
            identity = await evaluations.submit(EvaluationConfig.model_validate(config))
            print(f"Evaluation {identity}", flush=True)
            await evaluations.run(identity)
            result = await evaluations.get(identity)
        elif args.action == "execute":
            identity = UUID(args.identities[0])
            await evaluations.run(identity)
            result = await evaluations.get(identity)
        elif args.action == "inspect":
            result = await evaluations.get(UUID(args.identities[0]))
        else:
            left = await evaluations.get(UUID(args.identities[0]))
            right = await evaluations.get(UUID(args.identities[1]))
            if left is None or right is None:
                raise SystemExit("Evaluation not found")
            result = compare(left, right)
        print(json.dumps(result, default=str, indent=2))
    finally:
        await repo.close()


if __name__ == "__main__":
    asyncio.run(main())
