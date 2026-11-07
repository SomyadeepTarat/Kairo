"""Real process/DB/container fault injection: no blind replay of confirmed writes."""

import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from kairo_core.events import event_now
from kairo_core.orchestration.queue import LeaseRecorder, Queue
from kairo_core.orchestration.spec import FinalStep, JobSpec, ToolStep
from kairo_core.orchestration.worker import Worker, WorkspaceLock
from kairo_core.persistence.repository import RunRepository
from kairo_core.persistence.tables import AttemptRow, CheckpointRow, JobRow, RunRow
from kairo_core.state import RunStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.postgres

CHILD = """
import asyncio, os, sys
from pathlib import Path
from kairo_core.orchestration.queue import Queue, LeaseRecorder
from kairo_core.orchestration.worker import Worker, WorkspaceLock
from kairo_core.persistence.repository import RunRepository

stage, ready = sys.argv[1], Path(sys.argv[2])
original = LeaseRecorder.record
async def intercepted(self, event):
    await original(self, event)
    hit = (
        (stage == 'before_checkpoint' and event.kind == 'tool_finished')
        or (stage == 'after_dispatch' and event.kind == 'tool_started')
        or (stage == 'after_final' and event.kind == 'model_response')
    )
    if hit:
        ready.write_text('ready')
        await asyncio.Event().wait()
LeaseRecorder.record = intercepted

class BlockSecond:
    def __init__(self, spec):
        self.model = spec.build_model()
    async def generate(self, request):
        if stage == 'after_checkpoint' and request.step == 2:
            ready.write_text('ready')
            await asyncio.Event().wait()
        return await self.model.generate(request)

async def main():
    repo = RunRepository.from_url(os.environ['KAIRO_DATABASE_URL'])
    await Worker(Queue(repo, 0.8),Path(sys.argv[3]),model_factory=BlockSecond).work_once()
asyncio.run(main())
"""


def storage(url: str) -> RunRepository:
    return RunRepository(create_async_engine(url, poolclass=NullPool))


def command_job() -> JobSpec:
    command = [
        "python",
        "-c",
        "from pathlib import Path; p=Path('counter'); "
        "p.write_text((p.read_text() if p.exists() else '')+'x')",
    ]
    return JobSpec(
        task="append exactly once",
        max_steps=2,
        approved_commands=[command],
        steps=[
            ToolStep(
                kind="tool", name="execute_command", arguments_json=json.dumps({"argv": command})
            ),
            FinalStep(kind="final", text="finished"),
        ],
    )


def kill_at(url: str, root: Path, job: JobSpec, stage: str) -> UUID:
    if os.environ.get("KAIRO_TEST_DOCKER") != "1":
        pytest.skip("Enable real Docker for process recovery tests")

    async def submit() -> UUID:
        repo = storage(url)
        identity = await Queue(repo).enqueue(job)
        await repo.close()
        return identity

    identity = asyncio.run(submit())
    ready = (
        (root / str(identity) / "started")
        if stage == "in_tool"
        else root.parent / f"ready-{uuid4()}"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", CHILD, stage, str(ready), str(root)],
        env={**os.environ, "KAIRO_DATABASE_URL": url},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        if not ready.exists():
            process.kill()
            _, error = process.communicate(timeout=5)
            pytest.fail(f"Child failed before controlled crash: {error}")
        process.kill()
        process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
    return identity


async def expire(repo: RunRepository, identity: UUID) -> None:
    async with repo.sessions.begin() as session:
        job = await session.get(JobRow, identity)
        assert job is not None
        job.lease_until = datetime.now(UTC) - timedelta(seconds=1)


async def ready_now(repo: RunRepository, identity: UUID) -> None:
    async with repo.sessions.begin() as session:
        job = await session.get(JobRow, identity)
        assert job is not None
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)


@pytest.mark.docker
@pytest.mark.parametrize("stage", ["after_checkpoint", "before_checkpoint"])
def test_recovery_never_repeats_a_confirmed_write(
    database_url: str, tmp_path: Path, stage: str
) -> None:
    root = tmp_path / "managed"
    identity = kill_at(database_url, root, command_job(), stage)

    async def scenario() -> None:
        repo = storage(database_url)
        queue = Queue(repo, 0.8)
        await expire(repo, identity)
        assert (root / str(identity) / "counter").read_text() == "x"
        worker = Worker(queue, root)
        assert await worker.reap_expired() == 1
        state = await queue.get(identity)
        assert state is not None and state["state"] == "QUEUED"
        await ready_now(repo, identity)
        result = await worker.work_once()
        assert result is not None and result.status is RunStatus.COMPLETED
        assert result.steps[0].request.step == 2
        assert (root / str(identity) / "counter").read_text() == "x"
        assert len(await repo.tools(identity)) == 1
        async with repo.sessions() as session:
            attempts = list(
                await session.scalars(select(AttemptRow).where(AttemptRow.run_id == identity))
            )
            assert {item.status for item in attempts} == {"FAILED", "COMPLETED"}
            assert all(
                item.started_at is not None and item.ended_at is not None for item in attempts
            )
            checkpoints = list(
                await session.scalars(select(CheckpointRow).where(CheckpointRow.run_id == identity))
            )
            assert len(checkpoints) >= 3
        await repo.close()

    asyncio.run(asyncio.wait_for(scenario(), timeout=15))


@pytest.mark.docker
def test_unknown_mutation_requires_explicit_reconciliation(
    database_url: str, tmp_path: Path
) -> None:
    root = tmp_path / "managed"
    identity = kill_at(database_url, root, command_job(), "after_dispatch")

    async def scenario() -> None:
        repo = storage(database_url)
        queue = Queue(repo, 0.8)
        worker = Worker(queue, root)
        await expire(repo, identity)
        await worker.reap_expired()
        state = await queue.get(identity)
        assert (
            state is not None
            and state["state"] == "BLOCKED"
            and state["blocked_reason"] == "UNCERTAIN_TOOL"
        )
        assert await worker.work_once() is None
        assert not (root / str(identity) / "counter").exists()
        tool = (await repo.tools(identity))[0]
        invocation = tool["id"]
        assert isinstance(invocation, UUID)
        with pytest.raises(ValueError):
            await queue.reconcile(
                identity, invocation, reason="invalid output test", completed_output="{}"
            )
        await queue.reconcile(
            identity,
            invocation,
            reason="Controlled test proves handler never entered",
            not_executed=True,
        )
        await worker.reap_expired()
        await ready_now(repo, identity)
        result = await worker.work_once()
        assert result is not None and result.status is RunStatus.COMPLETED
        assert (root / str(identity) / "counter").read_text() == "x"
        history = await repo.events(identity, limit=1000)
        assert any(item["event_type"] == "tool_reconciled" for item in history)
        await repo.close()

    asyncio.run(asyncio.wait_for(scenario(), timeout=15))


@pytest.mark.docker
def test_recorded_final_response_needs_no_second_model_call(
    database_url: str, tmp_path: Path
) -> None:
    root = tmp_path / "managed"
    identity = kill_at(
        database_url,
        root,
        JobSpec(task="final reply test", steps=[FinalStep(kind="final", text="known final")]),
        "after_final",
    )

    async def scenario() -> None:
        repo = storage(database_url)
        queue = Queue(repo, 0.8)
        await expire(repo, identity)
        worker = Worker(queue, root)
        await worker.reap_expired()
        await ready_now(repo, identity)
        result = await worker.work_once()
        assert result is not None and result.output == "known final" and not result.steps
        events = await repo.events(identity, limit=1000)
        assert sum(item["event_type"] == "model_request" for item in events) == 1
        await repo.close()

    asyncio.run(scenario())


def test_retry_limit_and_absolute_deadline(database_url: str) -> None:
    async def scenario() -> None:
        repo = storage(database_url)
        queue = Queue(repo, 0.2)
        worker = uuid4()
        await queue.register(worker, 1)
        identity = await queue.enqueue(
            JobSpec(
                task="bounded retry", max_attempts=2, steps=[FinalStep(kind="final", text="unused")]
            )
        )
        for _ in range(2):
            claim = await queue.claim(worker)
            assert claim is not None
            await expire(repo, identity)
            assert len(await queue.expired()) == 1
            await queue.finish_abandoned(claim)
            await ready_now(repo, identity)
        row = await repo.get_run(identity)
        assert row is not None and row["status"] == "FAILED"
        assert row["error"] == {"code": "RETRY_EXHAUSTED", "detail": "Recovery stopped"}
        assert await queue.claim(worker) is None
        deadline_id = await queue.enqueue(
            JobSpec(task="deadline", steps=[FinalStep(kind="final", text="unused")])
        )
        claim = await queue.claim(worker)
        assert claim is not None
        await LeaseRecorder(queue, claim).record(
            event_now(
                deadline_id,
                claim.binding.attempt_id,
                "state_transition",
                '{"source":"QUEUED","target":"RUNNING"}',
            )
        )
        async with repo.sessions.begin() as session:
            run = await session.get(RunRow, deadline_id)
            assert run is not None
            run.started_at = datetime.now(UTC) - timedelta(seconds=121)
        await expire(repo, deadline_id)
        await queue.expired()
        await queue.finish_abandoned(claim)
        row = await repo.get_run(deadline_id)
        assert row is not None and row["status"] == "FAILED"
        assert isinstance(row["error"], dict) and row["error"]["code"] == "RUN_DEADLINE"
        await repo.close()

    asyncio.run(scenario())


@pytest.mark.docker
@pytest.mark.parametrize("problem", ["missing_workspace", "redacted_context", "invalid_context"])
def test_unusable_recovery_state_blocks_instead_of_silently_restarting(
    database_url: str, tmp_path: Path, problem: str
) -> None:
    import shutil

    root = tmp_path / "managed"
    identity = kill_at(database_url, root, command_job(), "after_checkpoint")
    if problem == "missing_workspace":
        shutil.rmtree(root / str(identity))  # Only the owned disposable test workspace.

    async def scenario() -> None:
        repo = storage(database_url)
        queue = Queue(repo, 0.8)
        await expire(repo, identity)
        if problem != "missing_workspace":
            async with repo.sessions.begin() as session:
                checkpoint = await session.scalar(
                    select(CheckpointRow)
                    .where(CheckpointRow.run_id == identity)
                    .order_by(CheckpointRow.event_sequence.desc())
                    .limit(1)
                )
                assert checkpoint is not None
                changed = dict(checkpoint.state)
                if problem == "invalid_context":
                    changed["version"] = 999
                else:
                    changed["final_output"] = "[REDACTED]"
                checkpoint.state = changed
        worker = Worker(queue, root)
        await worker.reap_expired()
        row = await queue.get(identity)
        assert row is not None and row["state"] == "BLOCKED"
        assert await worker.work_once() is None
        if problem == "missing_workspace":
            assert not (root / str(identity)).exists()
        assert await queue.cancel(identity)
        run = await repo.get_run(identity)
        assert run is not None and run["status"] == "CANCELLED"
        await repo.close()

    asyncio.run(scenario())


@pytest.mark.docker
def test_operator_can_record_a_proven_result_without_repeating_mutation(
    database_url: str, tmp_path: Path
) -> None:
    from httpx import ASGITransport, AsyncClient
    from kairo_api.main import create_app

    command = [
        "python",
        "-c",
        "from pathlib import Path; import time; "
        "p=Path('counter'); p.write_text((p.read_text() if p.exists() else '')+'x'); "
        "Path('started').write_text('ready'); time.sleep(60)",
    ]
    job = JobSpec(
        task="observed mutation",
        approved_commands=[command],
        steps=[
            ToolStep(
                kind="tool", name="execute_command", arguments_json=json.dumps({"argv": command})
            ),
            FinalStep(kind="final", text="known partial result accepted"),
        ],
    )
    root = tmp_path / "managed"
    identity = kill_at(database_url, root, job, "in_tool")

    async def scenario() -> None:
        repo = storage(database_url)
        queue = Queue(repo, 0.8)
        worker = Worker(queue, root)
        await expire(repo, identity)
        await worker.reap_expired()
        assert (root / str(identity) / "counter").read_text() == "x"
        invocation = (await repo.tools(identity))[0]["id"]
        app = create_app(repo)
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                checkpoints = await client.get(f"/api/v1/runs/{identity}/checkpoints")
                assert checkpoints.status_code == 200 and checkpoints.json()
                rejected = await client.post(
                    f"/api/v1/runs/{identity}/reconcile",
                    json={
                        "invocation_id": str(uuid4()),
                        "reason": "wrong identity",
                        "not_executed": True,
                    },
                )
                assert rejected.status_code == 409
                response = await client.post(
                    f"/api/v1/runs/{identity}/reconcile",
                    json={
                        "invocation_id": str(invocation),
                        "reason": "Observed append and confirmed forced container termination",
                        "completed_output": '{"stdout":"","stderr":"","returncode":137}',
                    },
                )
                assert response.status_code == 202
                await worker.reap_expired()
                await ready_now(repo, identity)
                result = await worker.work_once()
                assert result is not None and result.status is RunStatus.COMPLETED
                assert result.steps[0].request.step == 2
                assert (root / str(identity) / "counter").read_text() == "x"
                assert len(await repo.tools(identity)) == 1
                blocked_again = await client.post(
                    f"/api/v1/runs/{identity}/reconcile",
                    json={
                        "invocation_id": str(invocation),
                        "reason": "terminal run",
                        "not_executed": True,
                    },
                )
                assert blocked_again.status_code == 409

    asyncio.run(asyncio.wait_for(scenario(), timeout=15))


@pytest.mark.docker
def test_expiry_cannot_reassign_a_workspace_still_locked_by_an_old_owner(
    database_url: str, tmp_path: Path
) -> None:
    if os.environ.get("KAIRO_TEST_DOCKER") != "1":
        pytest.skip("Enable real Docker for reaper ownership validation")

    async def scenario() -> None:
        repo = storage(database_url)
        queue = Queue(repo, 0.8)
        identity = await queue.enqueue(
            JobSpec(task="lock fence", steps=[FinalStep(kind="final", text="done")])
        )
        old_worker = uuid4()
        await queue.register(old_worker, 1)
        claim = await queue.claim(old_worker)
        assert claim is not None
        await expire(repo, identity)
        reaper = Worker(queue, tmp_path)
        with WorkspaceLock(tmp_path, identity):
            assert await reaper.reap_expired() == 0
            assert await Worker(queue, tmp_path).work_once() is None
            state = await queue.get(identity)
            assert state is not None and state["state"] == "REAPING"
        assert await reaper.reap_expired() == 1
        await ready_now(repo, identity)
        result = await reaper.work_once()
        assert result is not None and result.status is RunStatus.COMPLETED
        await repo.close()

    asyncio.run(scenario())


@pytest.mark.docker
def test_workspace_removed_during_backoff_is_not_recreated(
    database_url: str, tmp_path: Path
) -> None:
    import shutil

    root = tmp_path / "managed"
    identity = kill_at(database_url, root, command_job(), "after_checkpoint")

    async def scenario() -> None:
        repo = storage(database_url)
        queue = Queue(repo, 0.8)
        await expire(repo, identity)
        worker = Worker(queue, root)
        await worker.reap_expired()
        shutil.rmtree(root / str(identity))  # Deliberately remove only the owned test workspace.
        await ready_now(repo, identity)
        assert await worker.work_once() is None
        row = await queue.get(identity)
        assert (
            row is not None
            and row["state"] == "BLOCKED"
            and row["blocked_reason"] == "WORKSPACE_MISSING"
        )
        assert not (root / str(identity)).exists()
        await repo.close()

    asyncio.run(scenario())
