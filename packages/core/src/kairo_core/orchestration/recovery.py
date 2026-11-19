"""Recover only proven continuation state; unknown mutations require reconciliation."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairo_core.checkpoints import KernelSnapshot
from kairo_core.events import event_now
from kairo_core.models import Message
from kairo_core.persistence.tables import (
    AttemptRow,
    CheckpointRow,
    EventRow,
    JobRow,
    RunRow,
    ToolRow,
)

if TYPE_CHECKING:
    from kairo_core.orchestration.queue import Claim, Queue


class RecoveryBlocked(ValueError):
    pass


def project(state: KernelSnapshot, events: list[EventRow], remaining: float) -> KernelSnapshot:
    """Close the tool-finished/checkpoint gap without invoking a tool or model."""
    request: dict[str, object] | None = None
    response: dict[str, object] | None = None
    outcome: dict[str, object] | None = None
    for event in events:
        if event.event_type == "model_request":
            request, response, outcome = event.payload, None, None
        elif event.event_type == "model_response":
            response = event.payload
        elif event.event_type in {"tool_finished", "tool_reconciled"}:
            outcome = None if event.payload.get("retry") else event.payload
        elif event.event_type == "model_failed":
            raise RecoveryBlocked("RECORDED_MODEL_FAILURE")
    if request is None:
        return state.model_copy(update={"remaining_seconds": remaining})
    raw_messages = request.get("history_messages", request.get("messages"))
    if not isinstance(raw_messages, list):
        raise RecoveryBlocked("INVALID_RECORDED_CONTEXT")
    messages = TypeAdapter(tuple[Message, ...]).validate_json(json.dumps(raw_messages))
    step = int(str(request["step"]))
    final: str | None = None
    if response is not None:
        if response["type"] == "Continue":
            messages += (Message("assistant", str(response["text"])),)
            step += 1
        elif response["type"] == "Final":
            final = str(response["text"])
        elif response["type"] == "ToolRequest" and outcome is not None:
            if outcome.get("outcome_uncertain"):
                raise RecoveryBlocked("UNCERTAIN_TOOL")
            messages += (
                Message(
                    "assistant",
                    json.dumps({"tool": response["name"], "arguments": response["arguments_json"]}),
                ),
                Message(
                    "tool",
                    json.dumps(
                        {
                            "name": outcome["name"],
                            "status": outcome["status"],
                            "output": json.loads(str(outcome["output_json"]))
                            if outcome.get("output_json")
                            else None,
                            "error_code": outcome.get("error_code"),
                        }
                    ),
                ),
            )
            step += 1
    return KernelSnapshot(
        messages=messages, next_step=step, remaining_seconds=remaining, final_output=final
    )


async def control_event(
    session: AsyncSession,
    run: RunRow,
    attempt_id: UUID,
    kind: str,
    payload: dict[str, object],
    now: datetime,
) -> None:
    run.event_sequence += 1
    session.add(
        EventRow(
            id=uuid4(),
            run_id=run.id,
            attempt_id=attempt_id,
            sequence_number=run.event_sequence,
            event_type=kind,
            payload=payload,
            occurred_at=now,
        )
    )


async def recover(queue: Queue, claim: Claim, *, workspace_exists: bool = True) -> None:
    from kairo_core.orchestration.queue import LeaseLost, database_now

    async with queue.repo.sessions.begin() as session:
        job = await session.scalar(
            select(JobRow).where(JobRow.run_id == claim.binding.run_id).with_for_update()
        )
        if job is None or job.state != "REAPING" or job.token != claim.token:
            raise LeaseLost("Abandoned execution was already handled")
        run = await session.scalar(select(RunRow).where(RunRow.id == job.run_id).with_for_update())
        assert run is not None
        if run.current_attempt_id != claim.binding.attempt_id:
            raise LeaseLost("Attempt changed while reclaiming")
        now = await database_now(session)

        async def fail(code: str, cancelled: bool = False) -> None:
            target = "CANCELLED" if cancelled else "FAILED"
            await queue.repo.record_in_transaction(
                session,
                event_now(
                    run.id,
                    run.current_attempt_id,
                    "state_transition",
                    json.dumps(
                        {
                            "source": run.status,
                            "target": target,
                            "failure": None
                            if cancelled
                            else {"code": code, "detail": "Recovery stopped"},
                        }
                    ),
                ),
            )
            job.state = target
            job.blocked_reason = code

        async def block(reason: str) -> None:
            job.state, job.blocked_reason = "BLOCKED", reason
            await control_event(
                session, run, run.current_attempt_id, "recovery_blocked", {"reason": reason}, now
            )

        if job.cancel_requested:
            await fail("CANCEL_REQUESTED", True)
            return
        unknown = await session.scalar(
            select(ToolRow.id)
            .where(ToolRow.run_id == run.id, ToolRow.outcome_uncertain.is_(True))
            .limit(1)
        )
        if unknown is not None:
            await block("UNCERTAIN_TOOL")
            return
        if run.started_at is not None and not workspace_exists:
            await block("WORKSPACE_MISSING")
            return
        if job.attempts >= job.max_attempts:
            await fail("RETRY_EXHAUSTED")
            return
        remaining = claim.spec.run_timeout_seconds
        if run.started_at is not None:
            remaining = max(
                0, (run.started_at + timedelta(seconds=remaining) - now).total_seconds()
            )
        if remaining <= 0:
            await fail("RUN_DEADLINE")
            return
        checkpoint = await session.scalar(
            select(CheckpointRow)
            .where(CheckpointRow.run_id == run.id)
            .order_by(CheckpointRow.event_sequence.desc())
            .limit(1)
        )
        try:
            if checkpoint is None:
                state = KernelSnapshot(
                    messages=(
                        Message("system", claim.spec.system_prompt),
                        Message("user", claim.spec.task),
                    ),
                    next_step=1,
                    remaining_seconds=remaining,
                )
                after = 0
            else:
                if "[REDACTED]" in json.dumps(checkpoint.state):
                    await block("REDACTED_CONTEXT")
                    return
                if checkpoint.workspace_reference != str(run.id):
                    raise RecoveryBlocked("WORKSPACE_REFERENCE_MISMATCH")
                state = KernelSnapshot.model_validate_json(json.dumps(checkpoint.state))
                remaining = min(remaining, state.remaining_seconds)
                after = checkpoint.event_sequence
            events = list(
                await session.scalars(
                    select(EventRow)
                    .where(EventRow.run_id == run.id, EventRow.sequence_number > after)
                    .order_by(EventRow.sequence_number)
                )
            )
            state = project(state, events, remaining)
            if state.next_step > claim.spec.max_steps + 1:
                raise RecoveryBlocked("INVALID_STEP_POSITION")
        except (RecoveryBlocked, ValueError, KeyError, TypeError):
            await block("INVALID_OR_FAILED_RECORDED_CONTEXT")
            return
        payload = state.model_dump(mode="json")
        if "[REDACTED]" in json.dumps(payload):
            await block("REDACTED_CONTEXT")
            return
        old_attempt = await session.get(AttemptRow, run.current_attempt_id)
        assert old_attempt is not None
        old_attempt.status, old_attempt.ended_at, old_attempt.failure_reason = (
            "FAILED",
            now,
            "LEASE_EXPIRED",
        )
        new_attempt = uuid4()
        session.add(AttemptRow(id=new_attempt, run_id=run.id, status="QUEUED"))
        await session.flush()
        previous = run.status
        run.status, run.current_attempt_id = "QUEUED", new_attempt
        job.state, job.token, job.worker_id, job.lease_until = "QUEUED", None, None, None
        job.resume_state, job.blocked_reason = payload, None
        job.available_at = now + timedelta(seconds=min(2 ** (job.attempts - 1), 30))
        await control_event(
            session,
            run,
            new_attempt,
            "attempt_recovered",
            {
                "previous_status": previous,
                "previous_attempt_id": str(old_attempt.id),
                "next_step": state.next_step,
                "remaining_seconds": state.remaining_seconds,
            },
            now,
        )
        session.add(
            CheckpointRow(
                id=uuid4(),
                run_id=run.id,
                attempt_id=new_attempt,
                event_sequence=run.event_sequence,
                state=payload,
                workspace_reference=str(run.id),
                created_at=now,
            )
        )
