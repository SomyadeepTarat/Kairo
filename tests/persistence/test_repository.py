"""Durability and transaction behavior verified against real PostgreSQL."""

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest
from kairo_core.events import event_now
from kairo_core.models import Final, ScriptedModel, ToolRequest
from kairo_core.persistence.repository import RecordConflict, RunRepository
from kairo_core.persistence.tables import AttemptRow
from kairo_core.runtime import run_agent
from kairo_core.state import InvalidTransition
from kairo_core.tools import builtin_registry
from kairo_core.tools.registry import ToolContext
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.postgres


def repository(url: str) -> RunRepository:
    # No connection pool shared between the independently created test event loops.
    return RunRepository(
        create_async_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 5})
    )


def test_completed_history_survives_new_repository(database_url: str, tmp_path: Path) -> None:
    async def scenario() -> None:
        first = repository(database_url)
        result = await run_agent(
            "write and read",
            ScriptedModel(
                (
                    ToolRequest("write_file", '{"path":"result.txt","content":"durable"}'),
                    ToolRequest("read_file", '{"path":"result.txt"}'),
                    Final("done"),
                )
            ),
            tools=builtin_registry(),
            tool_context=ToolContext(tmp_path, frozenset({"workspace.read", "workspace.write"})),
            recorder=first,
        )
        await first.close()
        restarted = repository(database_url)
        row = await restarted.get_run(result.run_id)
        assert row is not None and row["status"] == "COMPLETED" and row["output"] == "done"
        events = await restarted.events(result.run_id, limit=1000)
        assert [item["sequence_number"] for item in events] == list(range(1, len(events) + 1))
        assert row["event_sequence"] == len(events)
        assert sum(item["event_type"] == "model_request" for item in events) == 3
        tools = await restarted.tools(result.run_id)
        assert len(tools) == 2
        assert [item["id"] for item in tools] == [item.id for item in result.tool_executions]
        assert all(
            item["status"] == "COMPLETED" and not item["outcome_uncertain"] for item in tools
        )
        async with restarted.sessions() as session:
            attempt = await session.get(AttemptRow, result.attempt_id)
            assert (
                attempt is not None
                and attempt.status == "COMPLETED"
                and attempt.ended_at is not None
            )
        await restarted.close()

    asyncio.run(scenario())


def test_event_insert_failure_rolls_back_state_and_sequence(database_url: str) -> None:
    async def scenario() -> None:
        repo = repository(database_url)
        run_id, attempt = uuid4(), uuid4()
        await repo.start(run_id, attempt, "task", "{}", "test")
        # Controlled failure occurs after the repository has changed its ORM snapshot.
        async with repo.engine.begin() as connection:
            await connection.execute(
                text(
                    "CREATE FUNCTION reject_transition() RETURNS trigger LANGUAGE plpgsql AS $$ "
                    "BEGIN IF NEW.event_type = 'state_transition' THEN "
                    "RAISE EXCEPTION 'injected event failure'; END IF; RETURN NEW; END $$"
                )
            )
            await connection.execute(
                text(
                    "CREATE TRIGGER reject_event BEFORE INSERT ON execution_events "
                    "FOR EACH ROW EXECUTE FUNCTION reject_transition()"
                )
            )
        with pytest.raises(DBAPIError):
            await repo.record(
                event_now(
                    run_id, attempt, "state_transition", '{"source":"CREATED","target":"QUEUED"}'
                )
            )
        row = await repo.get_run(run_id)
        assert row is not None and row["status"] == "CREATED" and row["event_sequence"] == 1
        assert len(await repo.events(run_id)) == 1
        await repo.close()

    asyncio.run(scenario())


def test_invalid_stale_terminal_and_wrong_attempt_are_rejected(database_url: str) -> None:
    async def scenario() -> None:
        repo = repository(database_url)
        run_id, attempt = uuid4(), uuid4()
        await repo.start(run_id, attempt, "task", "{}", "test")
        with pytest.raises(InvalidTransition):
            await repo.record(
                event_now(
                    run_id, attempt, "state_transition", '{"source":"CREATED","target":"COMPLETED"}'
                )
            )
        with pytest.raises(RecordConflict):
            await repo.record(
                event_now(
                    run_id, attempt, "state_transition", '{"source":"RUNNING","target":"COMPLETED"}'
                )
            )
        with pytest.raises(RecordConflict):
            await repo.record(event_now(run_id, uuid4(), "model_request", "{}"))
        await repo.record(
            event_now(
                run_id, attempt, "state_transition", '{"source":"CREATED","target":"CANCELLED"}'
            )
        )
        with pytest.raises(RecordConflict):
            await repo.record(event_now(run_id, attempt, "model_request", "{}"))
        assert len(await repo.events(run_id)) == 2
        await repo.close()

    asyncio.run(scenario())


def test_concurrent_event_append_is_ordered(database_url: str) -> None:
    async def scenario() -> None:
        repo = repository(database_url)
        run_id, attempt = uuid4(), uuid4()
        await repo.start(run_id, attempt, "task", "{}", "test")
        await asyncio.gather(
            *(
                repo.record(event_now(run_id, attempt, "model_request", json.dumps({"number": n})))
                for n in range(12)
            )
        )
        events = await repo.events(run_id)
        assert [item["sequence_number"] for item in events] == list(range(1, 14))
        await repo.close()

    asyncio.run(scenario())


def test_credentials_are_redacted_from_durable_records(database_url: str) -> None:
    async def scenario() -> None:
        repo = repository(database_url)
        result = await run_agent(
            "password=do_not_store", ScriptedModel((Final("token=also_secret"),)), recorder=repo
        )
        row = await repo.get_run(result.run_id)
        events = await repo.events(result.run_id)
        serialized = json.dumps({"row": row, "events": events}, default=str)
        assert "do_not_store" not in serialized and "also_secret" not in serialized
        assert "[REDACTED]" in serialized
        await repo.close()

    asyncio.run(scenario())


def test_caller_cancellation_is_durable(database_url: str) -> None:
    async def scenario() -> None:
        started = asyncio.Event()

        class Blocking:
            async def generate(self, request: object) -> Final:
                started.set()
                await asyncio.Event().wait()
                return Final("unreachable")

        repo = repository(database_url)
        task = asyncio.create_task(run_agent("cancel task", Blocking(), recorder=repo))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        rows = await repo.list_runs()
        assert len(rows) == 1 and rows[0]["status"] == "CANCELLED"
        await repo.close()

    asyncio.run(asyncio.wait_for(scenario(), timeout=10))
