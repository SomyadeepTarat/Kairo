"""A decision binds one immutable action to one invocation/current leased attempt."""

import asyncio
import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import select

from kairo_core.orchestration.queue import Claim, Queue, database_now
from kairo_core.orchestration.recovery import control_event
from kairo_core.persistence.redaction import redact_object
from kairo_core.persistence.repository import RecordConflict
from kairo_core.persistence.tables import ApprovalRow, JobRow, RunRow


def action_digest(name: str, arguments_json: str) -> tuple[dict[str, object], str]:
    action: dict[str, object] = {"tool": name, "arguments": json.loads(arguments_json)}
    canonical = json.dumps(action, sort_keys=True, separators=(",", ":"))
    if "[REDACTED]" in json.dumps(redact_object(action)):
        raise ValueError("Credential-bearing approvals are unsupported")
    return action, hashlib.sha256(canonical.encode()).hexdigest()


class Approvals:
    def __init__(self, queue: Queue) -> None:
        self.queue = queue

    async def request(
        self, claim: Claim, invocation: UUID, name: str, arguments: str, risk: str
    ) -> UUID:
        action, digest = action_digest(name, arguments)
        async with self.queue.repo.sessions.begin() as session:
            await self.queue.owned(session, claim)
            run = await session.scalar(
                select(RunRow).where(RunRow.id == claim.binding.run_id).with_for_update()
            )
            assert run is not None
            if run.status != "WAITING_FOR_APPROVAL":
                raise RecordConflict("Run must be waiting for approval")
            identity, now = uuid4(), await database_now(session)
            session.add(
                ApprovalRow(
                    id=identity,
                    run_id=run.id,
                    attempt_id=claim.binding.attempt_id,
                    invocation_id=invocation,
                    fingerprint=digest,
                    action=action,
                    risk=risk,
                    agent=str(run.model_configuration.get("adapter", "unknown")),
                    status="PENDING",
                    requested_at=now,
                )
            )
            await control_event(
                session,
                run,
                run.current_attempt_id,
                "approval_requested",
                {
                    "approval_id": str(identity),
                    "invocation_id": str(invocation),
                    "fingerprint": digest,
                    "action": action,
                    "risk": risk,
                },
                now,
            )
            return identity

    async def decide(self, identity: UUID, approved: bool, reason: str) -> None:
        if not reason.strip() or len(reason) > 4096:
            raise ValueError("A decision requires a short reason")
        async with self.queue.repo.sessions.begin() as session:
            initial = await session.get(ApprovalRow, identity)
            if initial is None:
                raise KeyError("Unknown approval")
            # Same lock order as worker: job -> run -> approval.
            job = await session.scalar(
                select(JobRow).where(JobRow.run_id == initial.run_id).with_for_update()
            )
            run = await session.scalar(
                select(RunRow).where(RunRow.id == initial.run_id).with_for_update()
            )
            row = await session.scalar(
                select(ApprovalRow).where(ApprovalRow.id == identity).with_for_update()
            )
            now = await database_now(session)
            assert row is not None
            if (
                job is None
                or run is None
                or job.state != "CLAIMED"
                or job.cancel_requested
                or job.lease_until is None
                or job.lease_until <= now
                or row.attempt_id != run.current_attempt_id
                or run.status != "WAITING_FOR_APPROVAL"
                or row.status != "PENDING"
            ):
                raise RecordConflict("Approval is stale, terminal or already resolved")
            row.status, row.reason, row.resolved_at = (
                ("APPROVED" if approved else "DENIED"),
                str(redact_object({"text": reason})["text"]),
                now,
            )
            await control_event(
                session,
                run,
                run.current_attempt_id,
                "approval_resolved",
                {"approval_id": str(identity), "approved": approved, "reason": row.reason},
                now,
            )

    async def wait(
        self, claim: Claim, invocation: UUID, name: str, arguments: str, risk: str
    ) -> bool:
        identity = await self.request(claim, invocation, name, arguments, risk)
        _, fingerprint = action_digest(name, arguments)
        while True:
            async with self.queue.repo.sessions.begin() as session:
                await self.queue.owned(session, claim)
                row = await session.scalar(
                    select(ApprovalRow).where(ApprovalRow.id == identity).with_for_update()
                )
                assert row is not None
                if row.fingerprint != fingerprint or row.invocation_id != invocation:
                    raise RecordConflict("Approval action mismatch")
                if row.status == "DENIED":
                    return False
                if row.status == "APPROVED":
                    row.status = "CONSUMED"
                    return True
            await asyncio.sleep(0.1)

    async def list(self, run_id: UUID | None = None) -> list[dict[str, object]]:
        async with self.queue.repo.sessions() as session:
            now = await database_now(session)
            rows = await session.execute(
                select(ApprovalRow, RunRow, JobRow)
                .join(RunRow, ApprovalRow.run_id == RunRow.id)
                .join(JobRow, ApprovalRow.run_id == JobRow.run_id)
                .where(*([ApprovalRow.run_id == run_id] if run_id else []))
                .order_by(ApprovalRow.requested_at.desc())
                .limit(100)
            )
            return [
                {
                    "id": r.id,
                    "run_id": r.run_id,
                    "attempt_id": r.attempt_id,
                    "invocation_id": r.invocation_id,
                    "fingerprint": r.fingerprint,
                    "action": r.action,
                    "risk": r.risk,
                    "agent": r.agent,
                    "status": r.status,
                    "reason": r.reason,
                    "requested_at": r.requested_at,
                    "resolved_at": r.resolved_at,
                    "actionable": r.status == "PENDING"
                    and run.current_attempt_id == r.attempt_id
                    and run.status == "WAITING_FOR_APPROVAL"
                    and job.state == "CLAIMED"
                    and not job.cancel_requested
                    and job.lease_until is not None
                    and job.lease_until > now,
                }
                for r, run, job in rows
            ]
