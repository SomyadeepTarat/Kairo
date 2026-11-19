"""Real durable coordination; all role models here are explicitly scripted."""

import asyncio
import json
from pathlib import Path
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from kairo_api.main import create_app
from kairo_core.orchestration.queue import Queue
from kairo_core.orchestration.spec import JobSpec
from kairo_core.orchestration.worker import Worker
from kairo_core.orchestration.workflows import Plan, Workflows, WorkflowSpec

from tests.persistence.test_repository import repository

pytestmark = pytest.mark.postgres


def job(text: str) -> JobSpec:
    return JobSpec.model_validate({"task": "role task", "steps": [{"kind": "final", "text": text}]})


def specification(accepted: bool = True, max_revisions: int = 1) -> WorkflowSpec:
    return WorkflowSpec(
        planner=job(
            json.dumps({"tasks": [{"key": "write"}, {"key": "consume", "depends_on": ["write"]}]})
        ),
        executors={
            "write": JobSpec.model_validate(
                {
                    "task": "write and read actual artifact",
                    "steps": [
                        {
                            "kind": "tool",
                            "name": "write_file",
                            "arguments_json": '{"path":"artifact.txt","content":"real artifact"}',
                        },
                        {
                            "kind": "tool",
                            "name": "read_file",
                            "arguments_json": '{"path":"artifact.txt"}',
                        },
                        {"kind": "final", "text": "artifact produced"},
                    ],
                }
            ),
            "consume": job("dependency received"),
        },
        reviewer=job(json.dumps({"accepted": accepted, "feedback": "checked supplied evidence"})),
        max_revisions=max_revisions,
    )


@pytest.mark.parametrize(
    "tasks",
    [
        [{"key": "a", "depends_on": ["b"]}, {"key": "b", "depends_on": ["a"]}],
        [{"key": "a", "depends_on": ["absent"]}],
        [{"key": "a"}, {"key": "a"}],
    ],
)
def test_invalid_graph(tasks: list[dict[str, object]]) -> None:
    with pytest.raises(ValueError):
        Plan.model_validate({"tasks": tasks})


def test_restart_concurrent_ticks_handoffs_and_files(database_url: str, tmp_path: Path) -> None:
    async def scenario() -> None:
        repo = repository(database_url)
        queue, coordinator = Queue(repo), Workflows(Queue(repo))
        identity = await coordinator.submit(specification())
        worker = Worker(queue, tmp_path)
        for _ in range(15):
            # New coordinators represent a restarted process; concurrent ticks serialize.
            await asyncio.gather(*(Workflows(queue).advance(identity) for _ in range(3)))
            row = await coordinator.get(identity)
            assert row is not None
            if row["status"] in {"COMPLETED", "FAILED"}:
                break
            await worker.work_once()
        assert row is not None
        assert row["status"] == "COMPLETED"
        state = row["state"]
        assert isinstance(state, dict)
        events = state["events"]
        assert isinstance(events, list)
        delegated = [e for e in events if e["kind"] == "delegated"]
        assert len(delegated) == 4
        assert len({e["run_id"] for e in delegated}) == 4
        write = next(e for e in delegated if e["role"] == "executor:write")
        assert (tmp_path / write["run_id"] / "artifact.txt").read_text() == "real artifact"
        consume = next(e for e in delegated if e["role"] == "executor:consume")
        assert "real artifact" in consume["handoff"]
        assert not (tmp_path / consume["run_id"] / "artifact.txt").exists()
        async with AsyncClient(
            transport=ASGITransport(app=create_app(repo)), base_url="http://test"
        ) as c:
            response = await c.get(f"/api/v1/workflows/{identity}")
            assert response.json()["status"] == "COMPLETED"
            assert (await c.post(f"/api/v1/workflows/{identity}/advance")).status_code == 202
        await repo.close()

    asyncio.run(scenario())


def test_review_rejection_is_bounded(database_url: str, tmp_path: Path) -> None:
    async def scenario() -> None:
        repo = repository(database_url)
        queue = Queue(repo)
        workflows, worker = Workflows(queue), Worker(queue, tmp_path)
        identity = await workflows.submit(specification(False))
        for _ in range(30):
            await workflows.advance(identity)
            row = await workflows.get(identity)
            assert row is not None
            if row["status"] == "FAILED":
                break
            await worker.work_once()
        assert row is not None
        assert row["status"] == "FAILED"
        state = row["state"]
        assert isinstance(state, dict) and state["round"] == 1
        assert "REVISION_LIMIT" in json.dumps(state)
        assert json.dumps(state).count("revision_scheduled") == 1
        await repo.close()

    asyncio.run(scenario())


def test_invalid_plan_and_child_failure(database_url: str, tmp_path: Path) -> None:
    async def scenario() -> None:
        repo = repository(database_url)
        q = Queue(repo)
        workflows, worker = Workflows(q), Worker(q, tmp_path)
        spec = specification().model_copy(update={"planner": job("not a plan")})
        identity = await workflows.submit(spec)
        await worker.work_once()
        await workflows.advance(identity)
        row = await workflows.get(identity)
        assert row and row["status"] == "FAILED" and "INVALID_PLAN" in json.dumps(row["state"])
        other = await workflows.submit(specification())
        row = await workflows.get(other)
        assert row and isinstance(row["state"], dict)
        await q.cancel(UUID(str(row["state"]["planner"])))
        await workflows.advance(other)
        row = await workflows.get(other)
        assert row and row["status"] == "FAILED"
        await repo.close()

    asyncio.run(scenario())


def test_reviewer_can_accept_correction(database_url: str, tmp_path: Path) -> None:
    from kairo_core.models import Final, ScriptedModel

    async def scenario() -> None:
        repo = repository(database_url)
        q = Queue(repo)
        workflows = Workflows(q)
        seen = 0

        def model(spec: JobSpec) -> ScriptedModel:
            nonlocal seen
            if '"accepted"' in str(spec.steps):
                seen += 1
                return ScriptedModel(
                    (Final(json.dumps({"accepted": seen > 1, "feedback": "correction review"})),)
                )
            return spec.build_model()

        worker = Worker(q, tmp_path, model_factory=model)
        identity = await workflows.submit(specification(False))
        for _ in range(30):
            await workflows.advance(identity)
            row = await workflows.get(identity)
            if row and row["status"] in {"COMPLETED", "FAILED"}:
                break
            await worker.work_once()
        assert row and row["status"] == "COMPLETED" and seen == 2
        await repo.close()

    asyncio.run(scenario())
