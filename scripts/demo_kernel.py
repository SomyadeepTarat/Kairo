"""Run a three-step scripted mock demonstration. No inference or tools."""

import asyncio
import json

from kairo_core.models import Continue, Final, ScriptedModel
from kairo_core.runtime import AgentConfig, run_agent
from kairo_core.state import RunStatus


async def demo() -> int:
    model = ScriptedModel(
        (
            Continue("Scripted phase 1 of 3."),
            Continue("Scripted phase 2 of 3."),
            Final("Scripted workflow completed. No inference or external work was performed."),
        )
    )
    result = await run_agent(
        "Follow a three-response development script.", model, AgentConfig(max_steps=3)
    )
    print(
        json.dumps(
            {
                "mode": "scripted_mock_no_inference",
                "run_id": str(result.run_id),
                "status": result.status,
                "model_calls": len(result.steps),
                "transitions": [f"{edge.source} -> {edge.target}" for edge in result.transitions],
                "output": result.output,
            },
            indent=2,
        )
    )
    return 0 if result.status is RunStatus.COMPLETED else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(demo()))
