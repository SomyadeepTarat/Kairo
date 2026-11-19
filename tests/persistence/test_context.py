"""Real persisted context views remain distinct from checkpoint/history content."""

import asyncio
import json
from datetime import UTC, datetime

import pytest
from kairo_core.checkpoints import KernelSnapshot
from kairo_core.models import Continue, Final, Message, ScriptedModel
from kairo_core.orchestration.recovery import project
from kairo_core.persistence.tables import EventRow
from kairo_core.runtime import AgentConfig, run_agent

from tests.persistence.test_repository import repository

pytestmark = pytest.mark.postgres


def test_context_records_and_gap_projection(database_url: str) -> None:
    async def scenario() -> None:
        repo = repository(database_url)
        result = await run_agent(
            "task",
            ScriptedModel((Continue("x" * 1000), Final("ok"))),
            AgentConfig(context_budget_bytes=300),
            recorder=repo,
        )
        events = await repo.events(result.run_id, limit=1000)
        views = [e["payload"] for e in events if e["event_type"] == "context_assembled"]
        assert all(isinstance(p, dict) and p["supplied_bytes"] <= 300 for p in views)
        requests = [e for e in events if e["event_type"] == "model_request"]
        payload = requests[-1]["payload"]
        assert isinstance(payload, dict)
        assert len(payload["messages"]) == 2
        assert len(payload["history_messages"]) == 3
        state = KernelSnapshot(
            messages=(Message("system", "s"), Message("user", "t")),
            next_step=1,
            remaining_seconds=30,
        )
        projected = project(
            state,
            [EventRow(event_type="model_request", payload=payload, occurred_at=datetime.now(UTC))],
            20,
        )
        assert len(projected.messages) == 3
        assert json.dumps(projected.model_dump(mode="json")).count("x" * 1000) == 1
        await repo.close()

    asyncio.run(scenario())
