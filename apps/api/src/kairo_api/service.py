"""Optional trusted-local service: existing workers plus durable coordinator/evaluation ticks."""

import asyncio
import logging
from pathlib import Path

from kairo_core.evaluation import Evaluations
from kairo_core.orchestration.queue import Queue
from kairo_core.orchestration.worker import Worker
from kairo_core.orchestration.workflows import Workflows
from kairo_core.persistence.repository import RunRepository
from kairo_core.persistence.tables import EvaluationRow, WorkflowRow
from sqlalchemy import select


async def serve_execution(repo: RunRepository, stop: asyncio.Event, root: Path) -> None:
    worker = Worker(Queue(repo), root)

    async def control() -> None:
        while not stop.is_set():
            try:
                async with repo.sessions() as session:
                    workflows = list(
                        await session.scalars(
                            select(WorkflowRow.id)
                            .where(WorkflowRow.status.notin_(["COMPLETED", "FAILED"]))
                            .limit(100)
                        )
                    )
                    evaluation = await session.scalar(
                        select(EvaluationRow.id)
                        .where(EvaluationRow.status == "QUEUED")
                        .order_by(EvaluationRow.started_at)
                        .limit(1)
                    )
                for identity in workflows:
                    await Workflows(Queue(repo)).advance(identity)
                if evaluation is not None:
                    await Evaluations(repo, root.parent / "evaluations").run(evaluation)
            except Exception as exc:
                logging.error("Control tick failed: %s", type(exc).__name__)
            await asyncio.sleep(0.5)

    tasks = [asyncio.create_task(worker.run(stop)), asyncio.create_task(control())]
    try:
        await stop.wait()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
