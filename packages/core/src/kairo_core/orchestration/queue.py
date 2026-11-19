"""Short PostgreSQL queue transactions; each execution is fenced by a lease token."""

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from kairo_core.checkpoints import KernelSnapshot
from kairo_core.events import RuntimeEvent, event_now
from kairo_core.orchestration.spec import JobSpec
from kairo_core.persistence.redaction import redact_object
from kairo_core.persistence.repository import RecordConflict, RunRepository
from kairo_core.persistence.tables import JobRow, RunRow, ToolRow, WorkerRow
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
        async with self.repo.sessions.begin() as session:
            return await self.enqueue_in_transaction(session, spec)

    async def enqueue_in_transaction(self, session: AsyncSession, spec: JobSpec) -> UUID:
        payload = spec.model_dump(mode="json")
        if "[REDACTED]" in json.dumps(redact_object(payload)):
            raise ValueError(
                "Credential-bearing jobs are unsupported; do not persist secrets for replay"
            )
        run_id, attempt_id = uuid4(), uuid4()
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
                max_attempts=spec.max_attempts,
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

    async def claim(self, worker_id: UUID, run_id: UUID | None = None) -> Claim | None:
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
                .where(
                    JobRow.state == "QUEUED",
                    JobRow.available_at <= now,
                    *([JobRow.run_id == run_id] if run_id is not None else []),
                )
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
            if job.state in {"QUEUED", "BLOCKED"}:
                await self.repo.record_in_transaction(
                    session,
                    event_now(
                        run.id,
                        run.current_attempt_id,
                        "state_transition",
                        json.dumps({"source": run.status, "target": "CANCELLED"}),
                    ),
                )
                job.state = "CANCELLED"
            else:
                await self.repo.record_in_transaction(
                    session, event_now(run.id, run.current_attempt_id, "cancel_requested", "{}")
                )
            return True

    async def expired(self, run_id: UUID | None = None) -> list[Claim]:
        async with self.repo.sessions.begin() as session:
            now = await database_now(session)
            jobs = await session.scalars(
                select(JobRow)
                .where(
                    ((JobRow.state == "CLAIMED") & (JobRow.lease_until <= now))
                    | (JobRow.state == "REAPING"),
                    *([JobRow.run_id == run_id] if run_id is not None else []),
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

    async def finish_abandoned(self, claim: Claim, *, workspace_exists: bool = True) -> None:
        from kairo_core.orchestration.recovery import recover

        await recover(self, claim, workspace_exists=workspace_exists)

    async def block_owned(self, claim: Claim, reason: str) -> None:
        from kairo_core.orchestration.recovery import control_event

        async with self.repo.sessions.begin() as session:
            job = await self.owned(session, claim)
            run = await session.scalar(
                select(RunRow).where(RunRow.id == job.run_id).with_for_update()
            )
            assert run is not None
            job.state, job.blocked_reason = "BLOCKED", reason
            await control_event(
                session,
                run,
                run.current_attempt_id,
                "recovery_blocked",
                {"reason": reason},
                await database_now(session),
            )

    async def workspace_required(self, claim: Claim) -> bool:
        async with self.repo.sessions.begin() as session:
            job = await self.owned(session, claim)
            run = await session.get(RunRow, job.run_id)
            assert run is not None
            # A claimant can die before ever allocating or starting its workspace.
            return run.started_at is not None

    async def continuation(self, claim: Claim) -> KernelSnapshot | None:
        async with self.repo.sessions.begin() as session:
            job = await self.owned(session, claim)
            if job.resume_state is None:
                return None
            state = KernelSnapshot.model_validate_json(json.dumps(job.resume_state))
            run = await session.get(RunRow, job.run_id)
            assert run is not None
            remaining = state.remaining_seconds
            if run.started_at is not None:
                end = run.started_at + timedelta(seconds=claim.spec.run_timeout_seconds)
                remaining = min(
                    remaining, max(0, (end - await database_now(session)).total_seconds())
                )
            return state.model_copy(update={"remaining_seconds": remaining})

    async def reconcile(
        self,
        run_id: UUID,
        invocation_id: UUID,
        *,
        reason: str,
        completed_output: str | None = None,
        not_executed: bool = False,
    ) -> None:
        from kairo_core.orchestration.recovery import control_event
        from kairo_core.tools import builtin_registry

        if (
            not reason.strip()
            or len(reason) > 4096
            or (completed_output is not None) == not_executed
        ):
            raise ValueError("Provide a reason and exactly one resolution")
        async with self.repo.sessions.begin() as session:
            job = await session.scalar(
                select(JobRow).where(JobRow.run_id == run_id).with_for_update()
            )
            if job is None or job.state != "BLOCKED" or job.blocked_reason != "UNCERTAIN_TOOL":
                raise RecordConflict("Run is not awaiting uncertain-tool reconciliation")
            run = await session.scalar(select(RunRow).where(RunRow.id == run_id).with_for_update())
            tool = await session.get(ToolRow, invocation_id)
            if (
                run is None
                or tool is None
                or tool.run_id != run_id
                or tool.attempt_id != run.current_attempt_id
                or not tool.outcome_uncertain
            ):
                raise RecordConflict("Invocation is not uncertain in this run")
            output = (
                None
                if completed_output is None
                else builtin_registry().validate_output(tool.tool_name, completed_output)
            )
            now = await database_now(session)
            tool.status = "FAILED" if not_executed else "COMPLETED"
            tool.error_code = "RECONCILED_NOT_EXECUTED" if not_executed else None
            tool.output_json = (
                str(redact_object({"value": output})["value"]) if output is not None else None
            )
            tool.completed_at, tool.outcome_uncertain = now, False
            payload: dict[str, object] = {
                "id": str(tool.id),
                "name": tool.tool_name,
                "status": tool.status,
                "output_json": tool.output_json,
                "error_code": tool.error_code,
                "outcome_uncertain": False,
                "retry": not_executed,
                "reason": reason,
            }
            await control_event(
                session, run, run.current_attempt_id, "tool_reconciled", redact_object(payload), now
            )
            job.state, job.blocked_reason = "REAPING", None

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
                "max_attempts": job.max_attempts,
                "blocked_reason": job.blocked_reason,
                "available_at": job.available_at,
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
            run = await session.get(RunRow, run_id)
            assert run is not None
            # A worker may inject an Ollama adapter instead of the scripted template.
            run.model_configuration = {**run.model_configuration, "adapter": model_name}

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
