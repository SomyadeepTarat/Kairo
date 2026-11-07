"""Short PostgreSQL queue transactions; each execution is fenced by a lease token."""

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from kairo_core.events import RuntimeEvent, event_now
from kairo_core.orchestration.spec import JobSpec
from kairo_core.persistence.redaction import redact_object
from kairo_core.persistence.repository import RecordConflict, RunRepository
from kairo_core.persistence.tables import JobRow, RunRow, WorkerRow
from kairo_core.runtime import RunBinding
from kairo_core.state import TERMINAL_STATES, RunStatus


class LeaseLost(RecordConflict):
    pass


@dataclass(frozen=True)
class Claim:
    binding: RunBinding
    worker_id: UUID
    token: UUID
    spec: JobSpec


async def database_now(session: AsyncSession) -> datetime:
    value = await session.scalar(select(func.clock_timestamp()))
    assert isinstance(value, datetime)
    return value


class Queue:
    def __init__(self, repository: RunRepository, lease_seconds: float = 30) -> None:
        if not math.isfinite(lease_seconds) or lease_seconds < 0.2:
            raise ValueError("Lease duration must be finite and at least 0.2 seconds")
        self.repo = repository
        self.lease_seconds = lease_seconds

    async def enqueue(self, spec: JobSpec) -> UUID:
        payload = spec.model_dump(mode="json")
        if "[REDACTED]" in json.dumps(redact_object(payload)):
            raise ValueError(
                "Credential-bearing jobs are unsupported; do not persist secrets for replay"
            )
        run_id, attempt_id = uuid4(), uuid4()
        async with self.repo.sessions.begin() as session:
            now = await database_now(session)
            await self.repo.initialize(
                session,
                run_id,
                attempt_id,
                spec.task,
                json.dumps(asdict(spec.config())),
                "ScriptedModel",
            )
            await self.repo.record_in_transaction(
                session,
                event_now(
                    run_id, attempt_id, "state_transition", '{"source":"CREATED","target":"QUEUED"}'
                ),
            )
            session.add(
                JobRow(
                    run_id=run_id,
                    spec=payload,
                    state="QUEUED",
                    cancel_requested=False,
                    available_at=now,
                    created_at=now,
                    attempts=0,
                )
            )
        return run_id

    async def register(self, worker_id: UUID, capacity: int) -> None:
        if not 1 <= capacity <= 32:
            raise ValueError("Worker capacity must be between 1 and 32")
        async with self.repo.sessions.begin() as session:
            now = await database_now(session)
            statement = insert(WorkerRow).values(id=worker_id, capacity=capacity, heartbeat_at=now)
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[WorkerRow.id], set_={"capacity": capacity, "heartbeat_at": now}
                )
            )

    async def claim(self, worker_id: UUID) -> Claim | None:
        async with self.repo.sessions.begin() as session:
            worker = await session.scalar(
                select(WorkerRow).where(WorkerRow.id == worker_id).with_for_update()
            )
            if worker is None:
                raise ValueError("Register the worker before claiming")
            active = await session.scalar(
                select(func.count())
                .select_from(JobRow)
                .where(JobRow.worker_id == worker_id, JobRow.state.in_(["CLAIMED", "REAPING"]))
            )
            if int(active or 0) >= worker.capacity:
                return None
            now = await database_now(session)
            job = await session.scalar(
                select(JobRow)
                .where(JobRow.state == "QUEUED", JobRow.available_at <= now)
                .order_by(JobRow.available_at, JobRow.run_id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if job is None:
                return None
            run = await session.get(RunRow, job.run_id)
            assert run is not None
            if run.status != RunStatus.QUEUED:
                raise RecordConflict("Queue and run state disagree")
            job.state, job.worker_id, job.token = "CLAIMED", worker_id, uuid4()
            job.lease_until = now + timedelta(seconds=self.lease_seconds)
            job.attempts += 1
            worker.heartbeat_at = now
            return Claim(
                RunBinding(run.id, run.current_attempt_id),
                worker_id,
                job.token,
                JobSpec.model_validate(job.spec),
            )

    async def owned(self, session: AsyncSession, claim: Claim) -> JobRow:
        job = await session.scalar(
            select(JobRow).where(JobRow.run_id == claim.binding.run_id).with_for_update()
        )
        now = await database_now(session)
        if (
            job is None
            or job.state != "CLAIMED"
            or job.worker_id != claim.worker_id
            or job.token != claim.token
            or job.lease_until is None
            or job.lease_until <= now
        ):
            raise LeaseLost("Worker lease is no longer current")
        run = await session.get(RunRow, job.run_id)
        if run is None or run.current_attempt_id != claim.binding.attempt_id:
            raise LeaseLost("Execution attempt has changed")
        return job

    async def heartbeat(self, claim: Claim) -> bool:
        async with self.repo.sessions.begin() as session:
            job = await self.owned(session, claim)
            job.lease_until = await database_now(session) + timedelta(seconds=self.lease_seconds)
            cancel = job.cancel_requested
        # Separate transaction: never take the worker lock while holding a job lock.
        async with self.repo.sessions.begin() as session:
            worker = await session.get(WorkerRow, claim.worker_id)
            if worker is not None:
                worker.heartbeat_at = await database_now(session)
        return cancel

    async def cancel(self, run_id: UUID) -> bool:
        async with self.repo.sessions.begin() as session:
            job = await session.scalar(
                select(JobRow).where(JobRow.run_id == run_id).with_for_update()
            )
            if job is None:
                raise KeyError("Unknown queued run")
            if job.state in {"DONE", "FAILED", "CANCELLED"}:
                return False
            run = await session.get(RunRow, run_id)
            assert run is not None
            job.cancel_requested = True
            if job.state == "QUEUED":
                await self.repo.record_in_transaction(
                    session,
                    event_now(
                        run.id,
                        run.current_attempt_id,
                        "state_transition",
                        '{"source":"QUEUED","target":"CANCELLED"}',
                    ),
                )
                job.state = "CANCELLED"
            else:
                await self.repo.record_in_transaction(
                    session, event_now(run.id, run.current_attempt_id, "cancel_requested", "{}")
                )
            return True

    async def expired(self) -> list[Claim]:
        async with self.repo.sessions.begin() as session:
            now = await database_now(session)
            jobs = await session.scalars(
                select(JobRow)
                .where(
                    ((JobRow.state == "CLAIMED") & (JobRow.lease_until <= now))
                    | (JobRow.state == "REAPING")
                )
                .limit(100)
                .with_for_update(skip_locked=True)
            )
            claims = []
            for job in jobs:
                assert job.worker_id is not None and job.token is not None
                run = await session.get(RunRow, job.run_id)
                assert run is not None
                job.state = "REAPING"  # Fence first; cleanup happens after commit.
                claims.append(
                    Claim(
                        RunBinding(run.id, run.current_attempt_id),
                        job.worker_id,
                        job.token,
                        JobSpec.model_validate(job.spec),
                    )
                )
            return claims

    async def finish_abandoned(self, claim: Claim) -> None:
        """M5 conservatively fails abandoned work; M6 adds explicit safe recovery."""
        async with self.repo.sessions.begin() as session:
            job = await session.scalar(
                select(JobRow).where(JobRow.run_id == claim.binding.run_id).with_for_update()
            )
            if job is None or job.state != "REAPING" or job.token != claim.token:
                raise LeaseLost("Abandoned work was already handled")
            run = await session.get(RunRow, job.run_id)
            assert run is not None
            await self.repo.record_in_transaction(
                session,
                event_now(
                    run.id,
                    run.current_attempt_id,
                    "state_transition",
                    json.dumps(
                        {
                            "source": run.status,
                            "target": "FAILED",
                            "failure": {
                                "code": "LEASE_EXPIRED",
                                "detail": "Owner lost; no automatic retry",
                            },
                        }
                    ),
                ),
            )
            job.state = "FAILED"

    async def get(self, run_id: UUID) -> dict[str, object] | None:
        async with self.repo.sessions() as session:
            job = await session.get(JobRow, run_id)
            if job is None:
                return None
            return {
                "run_id": job.run_id,
                "state": job.state,
                "worker_id": job.worker_id,
                "lease_until": job.lease_until,
                "cancel_requested": job.cancel_requested,
                "attempts": job.attempts,
            }


class LeaseRecorder:
    def __init__(self, queue: Queue, claim: Claim) -> None:
        self.queue, self.claim = queue, claim

    async def start(
        self, run_id: UUID, attempt_id: UUID, task: str, config_json: str, model_name: str
    ) -> None:
        if (run_id, attempt_id) != (self.claim.binding.run_id, self.claim.binding.attempt_id):
            raise LeaseLost("Runtime identity does not match its claimed run")
        if task != self.claim.spec.task or json.loads(config_json) != asdict(
            self.claim.spec.config()
        ):
            raise RecordConflict("Runtime configuration differs from submitted work")
        async with self.queue.repo.sessions.begin() as session:
            await self.queue.owned(session, self.claim)

    async def record(self, event: RuntimeEvent) -> None:
        if (event.run_id, event.attempt_id) != (
            self.claim.binding.run_id,
            self.claim.binding.attempt_id,
        ):
            raise LeaseLost("Event does not belong to this claim")
        async with self.queue.repo.sessions.begin() as session:
            job = await self.queue.owned(session, self.claim)
            await self.queue.repo.record_in_transaction(session, event)
            if event.kind == "state_transition":
                target = RunStatus(str(json.loads(event.payload_json)["target"]))
                if target in TERMINAL_STATES:
                    job.state = "CANCELLED" if target is RunStatus.CANCELLED else "DONE"


async def workers(queue: Queue, identity: UUID | None = None) -> list[dict[str, object]]:
    """Inspection reports measured heartbeat times, not an invented alive status."""
    async with queue.repo.sessions() as session:
        query = select(WorkerRow).order_by(WorkerRow.heartbeat_at.desc()).limit(100)
        if identity is not None:
            query = query.where(WorkerRow.id == identity)
        rows = await session.scalars(query)
        result = []
        for row in rows:
            active = await session.scalar(
                select(func.count())
                .select_from(JobRow)
                .where(JobRow.worker_id == row.id, JobRow.state.in_(["CLAIMED", "REAPING"]))
            )
            result.append(
                {
                    "id": row.id,
                    "capacity": row.capacity,
                    "heartbeat_at": row.heartbeat_at,
                    "active_claims": int(active or 0),
                }
            )
        return result
