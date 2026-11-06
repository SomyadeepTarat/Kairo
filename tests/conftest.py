"""An explicit gate prevents a requested PostgreSQL run silently becoming skips."""

import os

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--require-postgres", action="store_true", help="Fail if database URL is absent"
    )


def pytest_sessionstart(session: pytest.Session) -> None:
    if session.config.getoption("--require-postgres") and not os.environ.get(
        "KAIRO_TEST_DATABASE_URL"
    ):
        raise pytest.UsageError(
            "Set KAIRO_TEST_DATABASE_URL for required PostgreSQL integration tests"
        )
