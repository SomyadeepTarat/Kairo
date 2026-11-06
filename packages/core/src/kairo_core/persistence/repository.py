"""Async PostgreSQL recording: lock a run, mutate its snapshot and append atomically."""

import json
from datetime import UTC, datetime
from typing import Self
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from kairo_core.events import RuntimeEvent
from kairo_core.persistence.redaction import redact_object
from kairo_core.persistence.tables import AttemptRow, EventRow, RunRow, TaskRow, ToolRow
from kairo_core.state import TERMINAL_STATES, RunStatus, transition


class RecordConflict(ValueError):
    """Stale, terminal, unknown, or mismatched execution record."""


def object_json(value: str) -> dict[str, object]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("Expected a JSON object")
    return {str(key): item for key, item in parsed.items()}


def _run_dict(row: RunRow) -> dict[str, object]:
    return {
        "id": row.id,
        "task_id": row.task_id,
        "current_attempt_id": row.current_attempt_id,
        "status": row.status,
        "model_configuration": row.model_configuration,
        "event_sequence": row.event_sequence,
        "output": row.output,
        "error": row.error,
        "created_at": row.created_at,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
    }


class RunRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.sessions = async_sessionmaker(engine, expire_on_commit=False)

    @classmethod
    def from_url(cls, url: str) -> Self:
        if not url.startswith("postgresql+psycopg://"):
            raise ValueError("Kairo requires a postgresql+psycopg:// database URL")
        return cls(
            create_async_engine(
                url, pool_pre_ping=True, pool_timeout=5, connect_args={"connect_timeout": 5}
            )
        )

    async def close(self) -> None:
        await self.engine.dispose()

    async def start(
        self, run_id: UUID, attempt_id: UUID, task: str, config_json: str, model_name: str
    ) -> None:
        now, task_id = datetime.now(UTC), uuid4()
        config = redact_object(object_json(config_json))
        description = str(redact_object({"text": task})["text"])
        async with self.sessions.begin() as session:
            session.add(
                TaskRow(
                    id=task_id,
                    description=description,
                    configuration=config,
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.flush()
            session.add(
                RunRow(
                    id=run_id,
                    task_id=task_id,
                    current_attempt_id=attempt_id,
                    status=RunStatus.CREATED,
                    model_configuration={"adapter": model_name},
                    event_sequence=1,
                    created_at=now,
                )
            )
            await session.flush()
            session.add(AttemptRow(id=attempt_id, run_id=run_id, status=RunStatus.CREATED))
            await session.flush()
            session.add(
                EventRow(
                    id=uuid4(),
                    run_id=run_id,
                    attempt_id=attempt_id,
                    sequence_number=1,
                    event_type="run_created",
                    payload={"task_id": str(task_id)},
                    occurred_at=now,
                )
            )

    async def record(self, event: RuntimeEvent) -> None:
        payload = redact_object(object_json(event.payload_json))
        async with self.sessions.begin() as session:
            row = await session.scalar(
                select(RunRow).where(RunRow.id == event.run_id).with_for_update()
            )
            if row is None or row.current_attempt_id != event.attempt_id:
                raise RecordConflict("Unknown run or mismatched current attempt")
            if RunStatus(row.status) in TERMINAL_STATES:
                raise RecordConflict("Terminal runs cannot receive new execution events")
            attempt = await session.get(AttemptRow, event.attempt_id)
            if attempt is None or attempt.run_id != row.id:
                raise RecordConflict("Attempt does not belong to the run")
            if event.kind == "state_transition":
                source, target = (
                    RunStatus(str(payload["source"])),
                    RunStatus(str(payload["target"])),
                )
                if source != row.status:
                    raise RecordConflict("Expected state does not match persisted state")
                row.status = transition(source, target)
                attempt.status = row.status
                if target is RunStatus.RUNNING and row.started_at is None:
                    row.started_at = event.occurred_at
                    attempt.started_at = event.occurred_at
                if target in TERMINAL_STATES:
                    row.completed_at = event.occurred_at
                    attempt.ended_at = event.occurred_at
                    output = payload.get("output")
                    row.output = str(output) if output is not None else None
                    error = payload.get("failure")
                    row.error = (
                        {str(key): value for key, value in error.items()}
                        if isinstance(error, dict)
                        else None
                    )
                    attempt.failure_reason = str(row.error.get("code")) if row.error else None
            elif event.kind == "tool_requested":
                session.add(
                    ToolRow(
                        id=UUID(str(payload["id"])),
                        run_id=row.id,
                        attempt_id=attempt.id,
                        tool_name=str(payload["name"]),
                        input_json=str(payload["input_json"]),
                        status="REQUESTED",
                        side_effect_class=str(payload["side_effect"]),
                        outcome_uncertain=False,
                        started_at=event.occurred_at,
                    )
                )
            elif event.kind in {"tool_started", "tool_finished"}:
                tool = await session.get(ToolRow, UUID(str(payload["id"])))
                if tool is None or tool.run_id != row.id or tool.attempt_id != attempt.id:
                    raise RecordConflict("Tool invocation does not belong to this run/attempt")
                if event.kind == "tool_started":
                    if tool.status != "REQUESTED":
                        raise RecordConflict("Tool already dispatched")
                    tool.status = "STARTED"
                    tool.outcome_uncertain = tool.side_effect_class != "read_only"
                else:
                    if tool.status != "STARTED":
                        raise RecordConflict("Tool is not awaiting a result")
                    tool.status = str(payload["status"])
                    tool.output_json = (
                        str(payload["output_json"])
                        if payload.get("output_json") is not None
                        else None
                    )
                    tool.error_code = (
                        str(payload["error_code"]) if payload.get("error_code") else None
                    )
                    tool.outcome_uncertain = bool(payload["outcome_uncertain"])
                    tool.completed_at = datetime.fromisoformat(str(payload["completed_at"]))
            elif event.kind not in {"model_request", "model_response", "model_failed"}:
                raise ValueError("Unsupported execution event")
            row.event_sequence += 1
            session.add(
                EventRow(
                    id=uuid4(),
                    run_id=row.id,
                    attempt_id=attempt.id,
                    sequence_number=row.event_sequence,
                    event_type=event.kind,
                    payload=payload,
                    occurred_at=event.occurred_at,
                )
            )
            # Commit happens on leaving sessions.begin. Any error rolls back both
            # the snapshot mutation and event insertion, including sequence allocation.

    async def list_runs(self, limit: int = 100, offset: int = 0) -> list[dict[str, object]]:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Invalid pagination")
        async with self.sessions() as session:
            rows = await session.scalars(
                select(RunRow)
                .order_by(RunRow.created_at.desc(), RunRow.id)
                .limit(limit)
                .offset(offset)
            )
            return [_run_dict(row) for row in rows]

    async def get_run(self, run_id: UUID) -> dict[str, object] | None:
        async with self.sessions() as session:
            row = await session.get(RunRow, run_id)
            if row is None:
                return None
            task = await session.get(TaskRow, row.task_id)
            assert task is not None
            return {**_run_dict(row), "task": task.description, "configuration": task.configuration}

    async def events(
        self, run_id: UUID, after: int = 0, limit: int = 100
    ) -> list[dict[str, object]]:
        if after < 0 or not 1 <= limit <= 1000:
            raise ValueError("Invalid pagination")
        async with self.sessions() as session:
            rows = await session.scalars(
                select(EventRow)
                .where(EventRow.run_id == run_id, EventRow.sequence_number > after)
                .order_by(EventRow.sequence_number)
                .limit(limit)
            )
            return [
                {
                    "id": row.id,
                    "run_id": row.run_id,
                    "attempt_id": row.attempt_id,
                    "sequence_number": row.sequence_number,
                    "event_type": row.event_type,
                    "payload": row.payload,
                    "occurred_at": row.occurred_at,
                }
                for row in rows
            ]

    async def tools(
        self, run_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[dict[str, object]]:
        if not 1 <= limit <= 1000 or offset < 0:
            raise ValueError("Invalid pagination")
        async with self.sessions() as session:
            rows = await session.scalars(
                select(ToolRow)
                .where(ToolRow.run_id == run_id)
                .order_by(ToolRow.started_at, ToolRow.id)
                .limit(limit)
                .offset(offset)
            )
            return [
                {
                    "id": row.id,
                    "run_id": row.run_id,
                    "attempt_id": row.attempt_id,
                    "name": row.tool_name,
                    "status": row.status,
                    "input_json": row.input_json,
                    "output_json": row.output_json,
                    "side_effect": row.side_effect_class,
                    "error_code": row.error_code,
                    "outcome_uncertain": row.outcome_uncertain,
                    "started_at": row.started_at,
                    "completed_at": row.completed_at,
                }
                for row in rows
            ]
