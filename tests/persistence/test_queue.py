"""Real PostgreSQL claims/fencing; worker integration also uses actual Docker."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from kairo_core.events import event_now
from kairo_core.models import Final, ModelRequest
from kairo_core.orchestration.queue import LeaseLost, LeaseRecorder, Queue
from kairo_core.orchestration.spec import FinalStep, JobSpec, ToolStep
from kairo_core.orchestration.worker import Worker, WorkspaceBusy, WorkspaceLock
from kairo_core.persistence.repository import RecordConflict, RunRepository
from kairo_core.state import RunStatus
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.postgres


def storage(url: str) -> RunRepository:
    return RunRepository(create_async_engine(url, poolclass=NullPool))


def spec() -> JobSpec:
    return JobSpec(task="explicit scripted job", steps=[FinalStep(kind="final", text="done")])


def test_competing_claims_are_unique_and_capacity_limited(database_url: str) -> None:
    async def scenario() -> None:
        repo = storage(database_url)
        queue = Queue(repo)
        ids = [await queue.enqueue(spec()) for _ in range(4)]
        workers = [uuid4(), uuid4()]
        for worker in workers:
            await queue.register(worker, 2)
        claims = await asyncio.gather(*(queue.claim(workers[index % 2]) for index in range(8)))
        actual = [claim for claim in claims if claim is not None]
        assert len(actual) == 4
        assert {claim.binding.run_id for claim in actual} == set(ids)
        assert len({claim.token for claim in actual}) == 4
        assert sum(claim.worker_id == workers[0] for claim in actual) == 2
        await repo.close()

    asyncio.run(scenario())


def test_queued_cancellation_and_recording_bypass_are_rejected(database_url: str) -> None:
    async def scenario() -> None:
        repo = storage(database_url)
        queue = Queue(repo)
        identity = await queue.enqueue(spec())
        run = await repo.get_run(identity)
        assert run is not None
        from uuid import UUID

        attempt = run["current_attempt_id"]
        assert isinstance(attempt, UUID)
        with pytest.raises(RecordConflict, match="lease recorder"):
            await repo.record(event_now(identity, attempt, "model_request", "{}"))
        assert await queue.cancel(identity)
        assert not await queue.cancel(identity)
        worker = uuid4()
        await queue.register(worker, 1)
        assert await queue.claim(worker) is None
        row = await repo.get_run(identity)
        assert row is not None and row["status"] == "CANCELLED"
        await repo.close()

    asyncio.run(scenario())


def test_stale_lease_is_fenced_before_reaping(database_url: str) -> None:
    async def scenario() -> None:
        repo = storage(database_url)
        queue = Queue(repo, 0.2)
        identity = await queue.enqueue(spec().model_copy(update={"max_attempts": 1}))
        worker = uuid4()
        await queue.register(worker, 1)
        claim = await queue.claim(worker)
        assert claim is not None
        await asyncio.sleep(0.3)
        with pytest.raises(LeaseLost):
            await queue.heartbeat(claim)
        abandoned = await queue.expired()
        assert len(abandoned) == 1 and abandoned[0].token == claim.token
        with pytest.raises(LeaseLost):
            await LeaseRecorder(queue, claim).record(
                event_now(identity, claim.binding.attempt_id, "model_request", "{}")
            )
        assert await queue.claim(worker) is None
        await queue.finish_abandoned(claim)
        row = await repo.get_run(identity)
        assert row is not None and row["status"] == "FAILED"
        await repo.close()

    asyncio.run(scenario())


def test_secrets_are_rejected_in_durable_work_spec(database_url: str) -> None:
    async def scenario() -> None:
        repo = storage(database_url)
        with pytest.raises(ValueError, match="secrets"):
            await Queue(repo).enqueue(
                JobSpec(task="password=never_store", steps=[FinalStep(kind="final", text="x")])
            )
        assert not await repo.list_runs()
        await repo.close()

    asyncio.run(scenario())


def test_workspace_lock_is_exclusive(tmp_path: Path) -> None:
    identity = uuid4()
    with WorkspaceLock(tmp_path, identity):
        with pytest.raises(WorkspaceBusy):
            with WorkspaceLock(tmp_path, identity):
                pass
    with WorkspaceLock(tmp_path, identity):
        pass


def require_docker() -> None:
    if os.environ.get("KAIRO_TEST_DOCKER") != "1":
        pytest.skip("Set KAIRO_TEST_DOCKER=1 for actual worker container integration")


@pytest.mark.docker
def test_two_workers_complete_separate_tasks(database_url: str, tmp_path: Path) -> None:
    require_docker()

    async def scenario() -> None:
        repo = storage(database_url)
        queue = Queue(repo)
        job = JobSpec(
            task="real workspace write",
            steps=[
                ToolStep(
                    kind="tool",
                    name="write_file",
                    arguments_json='{"path":"answer.txt","content":"actual file"}',
                ),
                FinalStep(kind="final", text="done"),
            ],
        )
        ids = [await queue.enqueue(job), await queue.enqueue(job)]
        workers = [Worker(queue, tmp_path), Worker(queue, tmp_path)]
        results = await asyncio.gather(*(worker.work_once() for worker in workers))
        assert all(
            result is not None and result.status is RunStatus.COMPLETED for result in results
        )
        for identity in ids:
            assert (tmp_path / str(identity) / "answer.txt").read_text() == "actual file"
            state = await queue.get(identity)
            assert state is not None and state["state"] == "DONE" and state["attempts"] == 1
        await repo.close()

    asyncio.run(asyncio.wait_for(scenario(), timeout=15))


@pytest.mark.docker
def test_running_cancellation_is_acknowledged_by_worker(database_url: str, tmp_path: Path) -> None:
    require_docker()

    async def scenario() -> None:
        started = asyncio.Event()

        class BlockingModel:
            async def generate(self, request: ModelRequest) -> Final:
                started.set()
                await asyncio.Event().wait()
                return Final("unreachable")

        repo = storage(database_url)
        queue = Queue(repo, 0.6)
        identity = await queue.enqueue(spec())
        worker = Worker(queue, tmp_path, model_factory=lambda submitted: BlockingModel())
        task = asyncio.create_task(worker.work_once())
        await started.wait()
        assert await queue.cancel(identity)
        result = await task
        assert result is not None and result.status is RunStatus.CANCELLED
        state = await queue.get(identity)
        assert state is not None and state["state"] == "CANCELLED"
        await repo.close()

    asyncio.run(asyncio.wait_for(scenario(), timeout=10))


def test_queue_and_worker_http_contract(database_url: str) -> None:
    from httpx import ASGITransport, AsyncClient
    from kairo_api.main import create_app

    async def scenario() -> None:
        repo = storage(database_url)
        queue = Queue(repo)
        identity = await queue.enqueue(spec())
        worker_id = uuid4()
        await queue.register(worker_id, 2)
        app = create_app(repo)
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(f"/api/v1/runs/{identity}/queue")
                assert response.status_code == 200 and response.json()["state"] == "QUEUED"
                response = await client.post(f"/api/v1/runs/{identity}/cancel")
                assert response.status_code == 202 and response.json()["accepted"]
                assert (await client.get(f"/api/v1/runs/{identity}")).json()[
                    "status"
                ] == "CANCELLED"
                assert (await client.get(f"/api/v1/workers/{worker_id}")).json()["capacity"] == 2
                assert len((await client.get("/api/v1/workers")).json()) == 1
                assert (await client.get(f"/api/v1/workers/{uuid4()}")).status_code == 404

    asyncio.run(scenario())


@pytest.mark.docker
def test_worker_executes_an_explicitly_approved_container_command(
    database_url: str, tmp_path: Path
) -> None:
    import json

    require_docker()

    async def scenario() -> None:
        repo = storage(database_url)
        queue = Queue(repo, 2)
        command = [
            "python",
            "-c",
            "from pathlib import Path; Path('from-container').write_text('real')",
        ]
        identity = await queue.enqueue(
            JobSpec(
                task="container job",
                approved_commands=[command],
                steps=[
                    ToolStep(
                        kind="tool",
                        name="execute_command",
                        arguments_json=json.dumps({"argv": command}),
                    ),
                    ToolStep(
                        kind="tool", name="read_file", arguments_json='{"path":"from-container"}'
                    ),
                    FinalStep(kind="final", text="done"),
                ],
            )
        )
        result = await Worker(queue, tmp_path).work_once()
        assert result is not None and result.status is RunStatus.COMPLETED
        assert (tmp_path / str(identity) / "from-container").read_text() == "real"
        assert len(await repo.tools(identity)) == 2
        await repo.close()

    asyncio.run(asyncio.wait_for(scenario(), timeout=15))


@pytest.mark.docker
def test_killed_worker_is_fenced_and_its_container_is_removed(
    database_url: str, tmp_path: Path
) -> None:
    import json
    import subprocess
    import sys
    import time
    from datetime import UTC, datetime, timedelta

    from kairo_core.execution.sandbox import docker
    from kairo_core.persistence.tables import JobRow

    require_docker()
    repo = storage(database_url)
    queue = Queue(repo, 0.8)
    root = tmp_path / "managed"
    command = [
        "python",
        "-c",
        "from pathlib import Path; import time; "
        "Path('started').write_text('ready'); time.sleep(60)",
    ]
    job = JobSpec(
        task="worker termination test",
        approved_commands=[command],
        steps=[
            ToolStep(
                kind="tool", name="execute_command", arguments_json=json.dumps({"argv": command})
            ),
            FinalStep(kind="final", text="must not reach in M5"),
        ],
    )
    identity = asyncio.run(queue.enqueue(job))
    process = subprocess.Popen(
        [
            sys.executable,
            "scripts/worker.py",
            "--once",
            "--root",
            str(root),
            "--lease-seconds",
            "0.8",
        ],
        env={**os.environ, "KAIRO_DATABASE_URL": database_url},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 15
        marker = root / str(identity) / "started"
        while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists(), "Child worker did not start its real container command"
        process.kill()
        process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)

    async def scenario() -> None:
        async with repo.sessions.begin() as session:
            row = await session.get(JobRow, identity)
            assert row is not None and row.token is not None
            token = row.token
            row.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        assert await Worker(queue, root).reap_expired() == 1
        snapshot = await repo.get_run(identity)
        assert snapshot is not None and snapshot["status"] == "WAITING_FOR_TOOL"
        state = await queue.get(identity)
        assert state is not None and state["state"] == "BLOCKED"
        remaining = await docker("ps", "-aq", "--filter", f"label=kairo.execution={token}")
        assert not remaining.stdout.strip()
        assert len(await repo.tools(identity)) == 1
        await repo.close()

    asyncio.run(scenario())
