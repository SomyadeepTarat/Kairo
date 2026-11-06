"""Create a local inspection server; migrations and execution are explicit commands."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from kairo_core.persistence.repository import RunRepository
from kairo_core.state import RunStatus
from pydantic import BaseModel
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

    app = FastAPI(title="Kairo execution inspection", version="0.3.0", lifespan=lifespan)

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

    return app
