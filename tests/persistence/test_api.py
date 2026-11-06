"""Inspection uses real PostgreSQL data, including after application recreation."""

import asyncio
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from kairo_api.main import create_app
from kairo_core.models import Final, ScriptedModel
from kairo_core.persistence.repository import RunRepository
from kairo_core.runtime import run_agent
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.postgres


def test_inspection_api_and_restart(database_url: str) -> None:
    def repo() -> RunRepository:
        return RunRepository(create_async_engine(database_url, poolclass=NullPool))

    async def scenario() -> None:
        storage = repo()
        result = await run_agent(
            "API test", ScriptedModel((Final("stored answer"),)), recorder=storage
        )
        await storage.close()
        run_id = str(result.run_id)
        for _ in range(2):
            app = create_app(repo())
            async with app.router.lifespan_context(app):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.get(f"/api/v1/runs/{run_id}")
                    assert response.status_code == 200
                    assert response.json()["output"] == "stored answer"
                    assert response.json()["status"] == "COMPLETED"
                    assert (await client.get("/api/v1/runs")).json()[0]["id"] == run_id
                    events = (await client.get(f"/api/v1/runs/{run_id}/events?limit=2")).json()
                    assert [item["sequence_number"] for item in events] == [1, 2]
                    next_events = (await client.get(f"/api/v1/runs/{run_id}/events?after=2")).json()
                    assert next_events[0]["sequence_number"] == 3
                    assert (await client.get(f"/api/v1/runs/{run_id}/tools")).json() == []
                    assert (await client.get(f"/api/v1/runs/{uuid4()}")).status_code == 404
                    assert (await client.get(f"/api/v1/runs/{uuid4()}/events")).status_code == 404
                    assert (await client.get("/api/v1/runs/not-a-uuid")).status_code == 422
                    assert (await client.get("/api/v1/runs?limit=101")).status_code == 422
                    assert (
                        await client.get(f"/api/v1/runs/{run_id}/events?after=-1")
                    ).status_code == 422
                    assert (await client.post("/api/v1/runs")).status_code == 405

    asyncio.run(scenario())
