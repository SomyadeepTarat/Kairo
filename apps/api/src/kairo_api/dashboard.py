"""Dashboard contracts: real aggregates, durable submissions, approvals and replayable SSE."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from kairo_core.approvals import Approvals
from kairo_core.evaluation import Evaluations, compare
from kairo_core.orchestration.queue import Queue
from kairo_core.orchestration.spec import JobSpec
from kairo_core.persistence.repository import RecordConflict, RunRepository
from kairo_core.persistence.tables import JobRow, RunRow, TaskRow, WorkflowRow
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved: bool
    reason: str = Field(min_length=1, max_length=4096)


def dashboard_routes(repo: RunRepository) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/overview")
    async def overview() -> dict[str, object]:
        async with repo.sessions() as session:
            counts = dict(
                (
                    await session.execute(
                        select(RunRow.status, func.count()).group_by(RunRow.status)
                    )
                ).all()
            )
            queued = await session.scalar(
                select(func.count()).select_from(JobRow).where(JobRow.state == "QUEUED")
            )
            blocked = await session.scalar(
                select(func.count()).select_from(JobRow).where(JobRow.state == "BLOCKED")
            )
        return {
            "total": sum(counts.values()),
            "counts": counts,
            "queued": queued or 0,
            "blocked": blocked or 0,
            "recent": await repo.list_runs(12),
        }

    @router.post("/runs", status_code=201)
    @router.post("/tasks", status_code=201)
    async def submit(spec: JobSpec) -> dict[str, object]:
        try:
            identity = await Queue(repo).enqueue(spec)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail="Invalid or credential-bearing workload"
            ) from exc
        run = await repo.get_run(identity)
        assert run is not None
        return {"id": identity, "run_id": identity, "task_id": run["task_id"], "status": "QUEUED"}

    @router.get("/tasks")
    async def tasks(
        limit: Annotated[int, Query(ge=1, le=100)] = 50, offset: Annotated[int, Query(ge=0)] = 0
    ) -> list[dict[str, object]]:
        async with repo.sessions() as session:
            rows = await session.execute(
                select(TaskRow, RunRow)
                .join(RunRow, RunRow.task_id == TaskRow.id)
                .order_by(TaskRow.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            return [
                {
                    "id": t.id,
                    "description": t.description,
                    "configuration": t.configuration,
                    "created_at": t.created_at,
                    "run_id": r.id,
                    "status": r.status,
                }
                for t, r in rows
            ]

    @router.get("/tasks/{identity}")
    async def task(identity: UUID) -> dict[str, object]:
        async with repo.sessions() as session:
            row = await session.get(TaskRow, identity)
            if row is None:
                raise HTTPException(status_code=404, detail="Task not found")
            runs = await session.scalars(select(RunRow).where(RunRow.task_id == identity))
            return {
                "id": row.id,
                "description": row.description,
                "configuration": row.configuration,
                "runs": [{"id": r.id, "status": r.status} for r in runs],
            }

    @router.get("/approvals")
    async def approvals(run_id: UUID | None = None) -> list[dict[str, object]]:
        return await Approvals(Queue(repo)).list(run_id)

    @router.post("/approvals/{identity}/decision")
    async def decide(identity: UUID, decision: Decision) -> dict[str, bool]:
        try:
            await Approvals(Queue(repo)).decide(identity, decision.approved, decision.reason)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Approval not found") from exc
        except (ValueError, RecordConflict) as exc:
            raise HTTPException(
                status_code=409, detail="Approval stale or already resolved"
            ) from exc
        return {"accepted": True}

    @router.get("/models")
    async def models() -> dict[str, object]:
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=3) as client:
                response = await client.get("http://127.0.0.1:11434/api/tags")
                response.raise_for_status()
                return {
                    "available": True,
                    "models": [
                        {"name": m["name"], "digest": m["digest"]}
                        for m in response.json()["models"]
                    ],
                }
        except (httpx.HTTPError, ValueError, KeyError):
            return {"available": False, "models": []}

    @router.get("/workflows")
    async def workflows(
        limit: Annotated[int, Query(ge=1, le=100)] = 50, offset: Annotated[int, Query(ge=0)] = 0
    ) -> list[dict[str, object]]:
        async with repo.sessions() as session:
            rows = await session.scalars(
                select(WorkflowRow)
                .order_by(WorkflowRow.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            return [
                {"id": r.id, "status": r.status, "state": r.state, "updated_at": r.updated_at}
                for r in rows
            ]

    @router.get("/evaluation-comparisons")
    async def comparison(left: UUID, right: UUID) -> dict[str, object]:
        from pathlib import Path

        ev = Evaluations(repo, Path(".kairo/evaluations"))
        a, b = await ev.get(left), await ev.get(right)
        if a is None or b is None:
            raise HTTPException(status_code=404, detail="Evaluation not found")
        try:
            return compare(a, b)
        except ValueError as exc:
            raise HTTPException(
                status_code=409, detail="Evaluation conditions differ or are incomplete"
            ) from exc

    @router.get("/runs/{identity}/stream")
    async def stream(
        identity: UUID, request: Request, after: Annotated[int, Query(ge=0)] = 0
    ) -> StreamingResponse:
        if await repo.get_run(identity) is None:
            raise HTTPException(status_code=404, detail="Run not found")
        cursor = request.headers.get("last-event-id")
        try:
            after = max(after, int(cursor)) if cursor else after
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid event cursor") from exc

        async def events() -> AsyncIterator[str]:
            position = after
            yield "retry: 1000\n\n"
            while not await request.is_disconnected():
                page = await repo.events(identity, after=position, limit=100)
                for event in page:
                    position = int(str(event["sequence_number"]))
                    data = json.dumps(jsonable_encoder(event))
                    yield f"id: {position}\nevent: execution\ndata: {data}\n\n"
                row = await repo.get_run(identity)
                if (
                    row
                    and row["status"] in {"COMPLETED", "FAILED", "CANCELLED"}
                    and len(page) < 100
                ):
                    yield "event: finished\ndata: {}\n\n"
                    return
                if not page:
                    yield ": heartbeat\n\n"
                    await asyncio.sleep(0.5)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router
