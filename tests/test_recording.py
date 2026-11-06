"""Recording failure is fail-closed; redaction limits and API outage are explicit."""

import asyncio
import json
from pathlib import Path
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from kairo_api.main import create_app
from kairo_core.events import RuntimeEvent
from kairo_core.models import ScriptedModel, ToolRequest
from kairo_core.persistence.redaction import redact_object
from kairo_core.persistence.repository import RunRepository
from kairo_core.runtime import run_agent
from kairo_core.tools import builtin_registry
from kairo_core.tools.registry import ToolContext
from sqlalchemy.exc import SQLAlchemyError


class FailedRecorder:
    async def start(
        self, run_id: UUID, attempt_id: UUID, task: str, config_json: str, model_name: str
    ) -> None:
        pass  # Deliberate recording test double; never presented as durable storage.

    async def record(self, event: RuntimeEvent) -> None:
        if event.kind == "tool_started":
            raise OSError("injected storage failure")


def test_storage_failure_prevents_tool_side_effect(tmp_path: Path) -> None:
    with pytest.raises(OSError, match="injected storage failure"):
        asyncio.run(
            run_agent(
                "task",
                ScriptedModel((ToolRequest("write_file", '{"path":"x","content":"x"}'),)),
                tools=builtin_registry(),
                tool_context=ToolContext(tmp_path, frozenset({"workspace.write"})),
                recorder=FailedRecorder(),
            )
        )
    assert not (tmp_path / "x").exists()


def test_nested_json_redaction() -> None:
    payload: dict[str, object] = {
        "password": "one",
        "input_json": '{"api_key":"two","content":"Bearer abc123"}',
        "messages": [{"content": "token=three"}],
    }
    encoded = json.dumps(redact_object(payload))
    assert all(secret not in encoded for secret in ("one", "two", "abc123", "three"))
    assert "REDACTED" in encoded


def test_api_reports_storage_failure_without_database_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = RunRepository.from_url("postgresql+psycopg://unused:unused@127.0.0.1:1/unused")

    async def unavailable(limit: int = 100, offset: int = 0) -> list[dict[str, object]]:
        raise SQLAlchemyError("secret database connection detail")

    monkeypatch.setattr(repo, "list_runs", unavailable)

    async def scenario() -> None:
        app = create_app(repo)
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/v1/runs")
                assert response.status_code == 503
                assert response.json() == {"detail": "Execution storage unavailable"}

    asyncio.run(scenario())


def test_api_requires_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KAIRO_DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="KAIRO_DATABASE_URL"):
        create_app()
