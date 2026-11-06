"""Each test migrates and drops only its own uniquely named PostgreSQL schema."""

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def database_url(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    base = os.environ.get("KAIRO_TEST_DATABASE_URL")
    if not base:
        pytest.skip("Set KAIRO_TEST_DATABASE_URL to run real PostgreSQL integration tests")
    if not base.startswith("postgresql+psycopg://"):
        raise ValueError("Integration tests require PostgreSQL, never SQLite")
    schema = "kairo_test_" + uuid4().hex
    admin = create_engine(base, connect_args={"connect_timeout": 5})
    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        # Preserve any test-server options while adding the unique schema search path.
        url = make_url(base)
        existing = str(url.query.get("options", ""))
        url = url.update_query_dict({"options": f"{existing} -csearch_path={schema}".strip()})
        test_url = url.render_as_string(hide_password=False)
        monkeypatch.setenv("KAIRO_DATABASE_URL", test_url)
        config = Config(str(ROOT / "alembic.ini"))
        config.attributes["schema"] = schema
        command.upgrade(config, "head")
        yield test_url
    finally:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()
