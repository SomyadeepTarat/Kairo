"""Real stored diagnostics and actual OTel SDK export; no collector/network."""

import asyncio
import json
import logging
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from kairo_api.main import create_app
from kairo_core.models import Continue, Final, ModelRequest, ScriptedModel, ToolRequest
from kairo_core.observability import TraceRecorder, inspect_trace
from kairo_core.runtime import AgentConfig, run_agent
from kairo_core.tools import builtin_registry
from kairo_core.tools.registry import ToolContext
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from tests.persistence.test_repository import repository

pytestmark = pytest.mark.postgres


def test_failed_run_correlated_spans_logs_and_api(
    database_url: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async def scenario() -> None:
        repo = repository(database_url)
        provider, exporter = TracerProvider(), InMemorySpanExporter()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        recorder = TraceRecorder(repo, provider.get_tracer("test"))
        with caplog.at_level(logging.INFO, logger="kairo.execution"):
            result = await run_agent(
                "private task content",
                ScriptedModel(
                    (ToolRequest("read_file", '{"path":"absent.txt"}'), Continue("still working"))
                ),
                AgentConfig(max_steps=2),
                tools=builtin_registry(),
                tool_context=ToolContext(tmp_path, frozenset({"workspace.read"})),
                recorder=recorder,
            )
        assert result.status == "FAILED"
        view = await inspect_trace(repo, result.run_id)
        assert view and view["trace_id"] == result.run_id.hex
        metrics = view["metrics"]
        assert isinstance(metrics, dict)
        assert metrics["model_calls"] == 2 and metrics["failed_tool_calls"] == 1
        assert metrics["token_usage"] is None and metrics["duration_seconds"] > 0
        assert view["failures"] and view["incomplete_span_count"] == 0
        observed_spans = view["spans"]
        assert isinstance(observed_spans, list)
        assert {s["step"] for s in observed_spans if s["name"] == "model"} == {1, 2}
        assert view["step_operation_seconds"]
        spans = exporter.get_finished_spans()
        assert {s.name for s in spans} == {"attempt", "model", "tool"}
        assert all(s.context and s.context.trace_id == result.run_id.int for s in spans)
        root = next(s for s in spans if s.name == "attempt")
        assert root.context
        assert all(
            s.parent and s.parent.span_id == root.context.span_id
            for s in spans
            if s.name != "attempt"
        )
        assert root.status.status_code.name == "ERROR"
        log = next(json.loads(r.message) for r in caplog.records if '"event"' in r.message)
        assert log["run_id"] == str(result.run_id)
        assert all("private task content" not in r.message for r in caplog.records)
        async with AsyncClient(
            transport=ASGITransport(app=create_app(repo)), base_url="http://test"
        ) as c:
            response = await c.get(f"/api/v1/runs/{result.run_id}/trace")
            assert response.status_code == 200 and response.json()["status"] == "FAILED"
        provider.shutdown()
        await repo.close()

    asyncio.run(scenario())


def test_cancelled_model_span_is_not_successful(database_url: str) -> None:
    async def scenario() -> None:
        repo = repository(database_url)
        cancellation = asyncio.Event()

        class SlowModel:
            async def generate(self, request: ModelRequest) -> Final:
                cancellation.set()
                await asyncio.sleep(10)
                return Final("unreachable")

        result = await run_agent("t", SlowModel(), recorder=repo, cancellation=cancellation)
        view = await inspect_trace(repo, result.run_id)
        assert view and view["incomplete_span_count"] == 0
        assert view["status"] == "CANCELLED"
        spans = view["spans"]
        assert isinstance(spans, list)
        assert any(s["name"] == "model" and s["status"] == "ERROR" for s in spans)
        await repo.close()

    asyncio.run(scenario())


def test_unfinished_recorded_prefix_stays_incomplete(database_url: str) -> None:
    from uuid import uuid4

    from kairo_core.events import event_now

    async def scenario() -> None:
        repo = repository(database_url)
        recorder = TraceRecorder(repo)
        run, attempt = uuid4(), uuid4()
        await recorder.start(run, attempt, "task", "{}", "controlled-prefix-test")
        for source, target in [("CREATED", "QUEUED"), ("QUEUED", "RUNNING")]:
            await recorder.record(
                event_now(
                    run,
                    attempt,
                    "state_transition",
                    json.dumps({"source": source, "target": target}),
                )
            )
        await recorder.record(event_now(run, attempt, "model_request", '{"step":1}'))
        # SDK cleanup cannot fabricate durable completion events after interruption.
        recorder.close()
        view = await inspect_trace(repo, run)
        assert view and view["incomplete_span_count"] == 2 and view["status"] == "RUNNING"
        await repo.close()

    asyncio.run(scenario())
