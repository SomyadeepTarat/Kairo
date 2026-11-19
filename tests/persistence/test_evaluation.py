"""Benchmarks run real tools/DB/Docker with explicitly scripted models."""

import asyncio
from pathlib import Path
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from kairo_api.main import create_app
from kairo_core.evaluation import EvaluationConfig, Evaluations, compare
from kairo_core.persistence.repository import RecordConflict

from tests.persistence.test_repository import repository

pytestmark = [pytest.mark.postgres, pytest.mark.docker]


def test_fixed_suite_twice_and_comparability(database_url: str, tmp_path: Path) -> None:
    async def scenario() -> None:
        repo = repository(database_url)
        evaluations = Evaluations(repo, tmp_path)
        rows = []
        for strategy in ("recent", "compact"):
            identity = await evaluations.submit(EvaluationConfig(strategy=strategy))
            await evaluations.run(identity)
            row = await evaluations.get(identity)
            assert row and row["status"] == "COMPLETED"
            results = row["results"]
            assert isinstance(results, list)
            assert all(r["passed"] for r in results), results
            assert len(results) == 10
            rows.append(row)
            with pytest.raises(RecordConflict):
                await evaluations.run(identity)
        report = compare(*rows)
        assert report["changed_strategies"] == {"strategy": ["recent", "compact"]}
        altered = dict(rows[1])
        config = altered["configuration"]
        assert isinstance(config, dict)
        altered["configuration"] = {**config, "seed": 100}
        with pytest.raises(ValueError, match="seed"):
            compare(rows[0], altered)
        async with AsyncClient(
            transport=ASGITransport(app=create_app(repo)), base_url="http://test"
        ) as c:
            saved_identity = rows[0]["id"]
            assert (await c.get(f"/api/v1/evaluations/{saved_identity}/results")).json()[
                "status"
            ] == "COMPLETED"
            assert len((await c.get("/api/v1/evaluations")).json()) == 2
            assert (
                await c.post("/api/v1/evaluations", json={"cases": ["file_task"]})
            ).status_code == 201
        await repo.close()

    asyncio.run(scenario())


def test_multi_and_no_recovery_conditions(database_url: str, tmp_path: Path) -> None:
    async def scenario() -> None:
        repo = repository(database_url)
        ev = Evaluations(repo, tmp_path)
        identity = await ev.submit(
            EvaluationConfig(mode="multi", recovery=False, cases=["file_task", "interruption"])
        )
        await ev.run(identity)
        row = await ev.get(identity)
        assert row and isinstance(row["results"], list)
        assert all(r["passed"] for r in row["results"]), row["results"]
        assert row["results"][1]["task_success"] is False
        await repo.close()

    asyncio.run(scenario())


def test_infrastructure_errors_count_as_failed_tasks(database_url: str, tmp_path: Path) -> None:
    class BrokenFixture(Evaluations):
        async def case(
            self, identity: UUID, case: str, repetition: int, config: EvaluationConfig
        ) -> dict[str, object]:
            raise OSError("labelled infrastructure fault; message must not be persisted")

    async def scenario() -> None:
        repo = repository(database_url)
        ev = BrokenFixture(repo, tmp_path)
        identity = await ev.submit(EvaluationConfig(cases=["file_task"]))
        await ev.run(identity)
        row = await ev.get(identity)
        assert row and isinstance(row["summary"], dict) and isinstance(row["results"], list)
        assert row["summary"]["task_count"] == 1
        assert row["summary"]["task_completion_rate"] == 0
        groups = row["summary"]["outcome_groups"]
        assert groups == {"infrastructure_error": {"cases": 1, "passed": 0}}
        assert row["results"][0]["error"] == "OSError"
        assert row["results"][0]["error_frames"]
        assert "message must not" not in str(row)
        await repo.close()

    asyncio.run(scenario())


def test_fault_expiry_uses_database_clock(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Host/VM clock skew must not make the intentional expired lease remain live."""
    from datetime import UTC, datetime
    from typing import Self
    from uuid import uuid4

    class SkewedHostClock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Self:
            return cls.fromtimestamp(datetime.now(UTC).timestamp() + 3600, tz=UTC)

    monkeypatch.setattr("kairo_core.evaluation.datetime", SkewedHostClock)

    async def scenario() -> None:
        repo = repository(database_url)
        ev = Evaluations(repo, tmp_path)
        result = await ev.case(uuid4(), "interruption", 0, EvaluationConfig())
        assert result["passed"] and result["task_success"]
        await repo.close()

    asyncio.run(scenario())
