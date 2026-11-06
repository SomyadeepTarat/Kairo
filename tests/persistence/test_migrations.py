"""Upgrade/downgrade/upgrade in a unique test schema, never the user's public schema."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url

pytestmark = pytest.mark.postgres


def test_migration_roundtrip(database_url: str) -> None:
    options = str(make_url(database_url).query["options"])
    schema = options.split("-csearch_path=")[-1]
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.attributes["schema"] = schema
    engine = create_engine(database_url)
    expected = {"tasks", "runs", "run_attempts", "execution_events", "tool_executions"}
    try:
        assert expected <= set(inspect(engine).get_table_names(schema=schema))
        command.downgrade(config, "base")
        assert not expected & set(inspect(engine).get_table_names(schema=schema))
        command.upgrade(config, "head")
        assert expected <= set(inspect(engine).get_table_names(schema=schema))
        # Alembic compares versioned schema with ORM metadata, catching drift.
        command.check(config)
    finally:
        engine.dispose()
