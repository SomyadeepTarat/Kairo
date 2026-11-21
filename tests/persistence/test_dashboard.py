"""Real PostgreSQL/worker approval enforcement and SSE cursor replay."""

import asyncio
from pathlib import Path
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from kairo_api.main import create_app
from kairo_core.approvals import Approvals, action_digest
from kairo_core.orchestration.queue import Queue
from kairo_core.orchestration.spec import FinalStep, JobSpec, ToolStep
from kairo_core.orchestration.worker import Worker

from tests.persistence.test_repository import repository

pytestmark = [pytest.mark.postgres, pytest.mark.docker]


@pytest.mark.parametrize("approve", [True, False])
def test_approval_controls_real_write_and_replay(
    database_url: str, tmp_path: Path, approve: bool
) -> None:
    async def scenario() -> None:
        repo = repository(database_url)
        q = Queue(repo)
        spec = JobSpec(
            task="approval test",
            require_approval=True,
            steps=[
                ToolStep(
                    kind="tool",
                    name="write_file",
                    arguments_json='{"path":"result.txt","content":"approved"}',
                ),
                FinalStep(kind="final", text="done"),
            ],
        )
        async with AsyncClient(
            transport=ASGITransport(app=create_app(repo)), base_url="http://test"
        ) as c:
            submitted = await c.post("/api/v1/runs", json=spec.model_dump(mode="json"))
            assert submitted.status_code == 201
            identity = UUID(submitted.json()["run_id"])
            execution = asyncio.create_task(Worker(q, tmp_path).work_once(identity))
            try:
                for _ in range(100):
                    rows = (await c.get(f"/api/v1/approvals?run_id={identity}")).json()
                    if rows:
                        break
                    await asyncio.sleep(0.02)
                assert rows and rows[0]["status"] == "PENDING"
                assert not (tmp_path / str(identity) / "result.txt").exists()
                approval = rows[0]
                step = spec.steps[0]
                assert isinstance(step, ToolStep)
                assert (
                    approval["fingerprint"] == action_digest("write_file", step.arguments_json)[1]
                )
                endpoint = f"/api/v1/approvals/{approval['id']}/decision"
                assert (
                    await c.post(endpoint, json={"approved": approve, "reason": "test evidence"})
                ).status_code == 200
                assert (
                    await c.post(endpoint, json={"approved": not approve, "reason": "replay"})
                ).status_code == 409
                result = await execution
                assert result and result.status == ("COMPLETED" if approve else "FAILED")
                assert (tmp_path / str(identity) / "result.txt").exists() == approve
                overview = (await c.get("/api/v1/overview")).json()
                assert overview["total"] == 1
                replay = await c.get(
                    f"/api/v1/runs/{identity}/stream", headers={"Last-Event-ID": "3"}
                )
                assert replay.status_code == 200 and "event: finished" in replay.text
                assert "id: 3\n" not in replay.text and "id: 4\n" in replay.text
                assert len((await c.get("/api/v1/tasks")).json()) == 1
                task_id = submitted.json()["task_id"]
                assert (await c.get(f"/api/v1/tasks/{task_id}")).status_code == 200
            finally:
                execution.cancel()
                await asyncio.gather(execution, return_exceptions=True)
        await repo.close()

    asyncio.run(scenario())


def test_cancel_invalidates_pending_decision(database_url: str, tmp_path: Path) -> None:
    async def scenario() -> None:
        repo = repository(database_url)
        q = Queue(repo)
        identity = await q.enqueue(
            JobSpec(
                task="cancel",
                require_approval=True,
                steps=[
                    ToolStep(
                        kind="tool",
                        name="write_file",
                        arguments_json='{"path":"never","content":"no"}',
                    )
                ],
            )
        )
        worker = Worker(q, tmp_path)
        task = asyncio.create_task(worker.work_once(identity))
        approvals = Approvals(q)
        try:
            for _ in range(100):
                rows = await approvals.list(identity)
                if rows:
                    break
                await asyncio.sleep(0.02)
            assert rows
            await q.cancel(identity)
            from kairo_core.persistence.repository import RecordConflict

            with pytest.raises(RecordConflict):
                await approvals.decide(UUID(str(rows[0]["id"])), True, "too late")
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            assert not (tmp_path / str(identity) / "never").exists()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await repo.close()

    asyncio.run(scenario())


def test_cross_origin_mutation_and_untrusted_host_rejected(database_url: str) -> None:
    async def scenario() -> None:
        repo = repository(database_url)
        try:
            async with AsyncClient(
                transport=ASGITransport(app=create_app(repo)), base_url="http://test"
            ) as c:
                spec = JobSpec(task="must not queue", steps=[FinalStep(kind="final", text="x")])
                response = await c.post(
                    "/api/v1/runs",
                    json=spec.model_dump(mode="json"),
                    headers={"Origin": "https://untrusted.example"},
                )
                assert response.status_code == 403
                assert (
                    await c.get("/api/v1/overview", headers={"Host": "untrusted.example"})
                ).status_code == 400
                assert (await c.get("/api/v1/overview")).json()["total"] == 0
        finally:
            await repo.close()

    asyncio.run(scenario())
