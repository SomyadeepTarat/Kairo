"""Local execution inspection, cancellation and explicit operator reconciliation."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from kairo_core.orchestration.queue import Queue, workers
from kairo_core.orchestration.workflows import Workflows, WorkflowSpec
from kairo_core.persistence.repository import RecordConflict, RunRepository
from kairo_core.persistence.tables import CheckpointRow
from kairo_core.state import RunStatus
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError


class RunView(BaseModel):
    id: UUID
    task_id: UUID
    current_attempt_id: UUID
    status: RunStatus
    model_configuration: dict[str, object]
    event_sequence: int
    output: str | None
    error: dict[str, object] | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class RunDetail(RunView):
    task: str
    configuration: dict[str, object]


class EventView(BaseModel):
    id: UUID
    run_id: UUID
    attempt_id: UUID
    sequence_number: int
    event_type: str
    payload: dict[str, object]
    occurred_at: datetime


class ToolView(BaseModel):
    id: UUID
    run_id: UUID
    attempt_id: UUID
    name: str
    status: Literal["REQUESTED", "STARTED", "COMPLETED", "FAILED", "TIMED_OUT", "CANCELLED"]
    input_json: str
    output_json: str | None
    side_effect: Literal["read_only", "workspace_write", "external"]
    error_code: str | None
    outcome_uncertain: bool
    started_at: datetime
    completed_at: datetime | None


class ReconcileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invocation_id: UUID
    reason: str = Field(min_length=1, max_length=4096)
    not_executed: bool = False
    completed_output: str | None = None


def create_app(repository: RunRepository | None = None) -> FastAPI:
    if repository is None:
        url = os.environ.get("KAIRO_DATABASE_URL")
        if not url:
            raise ValueError("Set KAIRO_DATABASE_URL before starting the inspection API")
        repository = RunRepository.from_url(url)
    repo = repository

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await repo.close()

    app = FastAPI(title="Kairo local execution control", version="0.6.0", lifespan=lifespan)

    @app.exception_handler(SQLAlchemyError)
    async def storage_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "Execution storage unavailable"})

    async def require_run(run_id: UUID) -> dict[str, object]:
        row = await repo.get_run(run_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return row

    @app.get("/api/v1/runs", response_model=list[RunView])
    async def list_runs(
        limit: Annotated[int, Query(ge=1, le=100)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[dict[str, object]]:
        return await repo.list_runs(limit, offset)

    @app.get("/api/v1/runs/{run_id}", response_model=RunDetail)
    async def get_run(run_id: UUID) -> dict[str, object]:
        return await require_run(run_id)

    @app.get("/api/v1/runs/{run_id}/events", response_model=list[EventView])
    async def get_events(
        run_id: UUID,
        after: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> list[dict[str, object]]:
        await require_run(run_id)
        return await repo.events(run_id, after, limit)

    @app.get("/api/v1/runs/{run_id}/tools", response_model=list[ToolView])
    async def get_tools(
        run_id: UUID,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[dict[str, object]]:
        await require_run(run_id)
        return await repo.tools(run_id, limit, offset)

    @app.get("/api/v1/runs/{run_id}/queue")
    async def get_queue(run_id: UUID) -> dict[str, object]:
        row = await Queue(repo).get(run_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Queued run not found")
        return row

    @app.post("/api/v1/runs/{run_id}/cancel", status_code=202)
    async def cancel_run(run_id: UUID) -> dict[str, bool]:
        try:
            return {"accepted": await Queue(repo).cancel(run_id)}
        except KeyError:
            raise HTTPException(status_code=404, detail="Queued run not found") from None

    @app.get("/api/v1/workers")
    async def get_workers() -> list[dict[str, object]]:
        return await workers(Queue(repo))

    @app.get("/api/v1/workers/{worker_id}")
    async def get_worker(worker_id: UUID) -> dict[str, object]:
        rows = await workers(Queue(repo), worker_id)
        if not rows:
            raise HTTPException(status_code=404, detail="Worker not found")
        return rows[0]

    @app.get("/api/v1/runs/{run_id}/checkpoints")
    async def get_checkpoints(
        run_id: UUID,
        after: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> list[dict[str, object]]:
        await require_run(run_id)
        async with repo.sessions() as session:
            rows = await session.scalars(
                select(CheckpointRow)
                .where(CheckpointRow.run_id == run_id, CheckpointRow.event_sequence > after)
                .order_by(CheckpointRow.event_sequence)
                .limit(limit)
            )
            return [
                {
                    "id": row.id,
                    "attempt_id": row.attempt_id,
                    "event_sequence": row.event_sequence,
                    "workspace_reference": row.workspace_reference,
                    "state": row.state,
                    "created_at": row.created_at,
                }
                for row in rows
            ]

    @app.post("/api/v1/runs/{run_id}/reconcile", status_code=202)
    async def reconcile_run(run_id: UUID, request: ReconcileRequest) -> dict[str, bool]:
        try:
            await Queue(repo).reconcile(
                run_id,
                request.invocation_id,
                reason=request.reason,
                completed_output=request.completed_output,
                not_executed=request.not_executed,
            )
        except (RecordConflict, ValueError) as exc:
            raise HTTPException(
                status_code=409, detail="Invalid reconciliation for this run/invocation"
            ) from exc
        return {"accepted": True}

    @app.post("/api/v1/workflows", status_code=201)
    async def submit_workflow(spec: WorkflowSpec) -> dict[str, UUID]:
        try:
            return {"id": await Workflows(Queue(repo)).submit(spec)}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid workflow payload") from exc

    @app.get("/api/v1/workflows/{workflow_id}")
    async def get_workflow(workflow_id: UUID) -> dict[str, object]:
        row = await Workflows(Queue(repo)).get(workflow_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Workflow not found")
        return row

    @app.post("/api/v1/workflows/{workflow_id}/advance", status_code=202)
    async def advance_workflow(workflow_id: UUID) -> dict[str, bool]:
        try:
            await Workflows(Queue(repo)).advance(workflow_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Workflow not found") from exc
        return {"accepted": True}

    return app
