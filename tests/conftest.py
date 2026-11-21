"""An explicit gate prevents a requested PostgreSQL run silently becoming skips."""

import os

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--require-postgres", action="store_true", help="Fail if database URL is absent"
    )

    parser.addoption(
        "--require-docker", action="store_true", help="Fail if Docker tests are disabled"
    )


def pytest_sessionstart(session: pytest.Session) -> None:
    if session.config.getoption("--require-postgres") and not os.environ.get(
        "KAIRO_TEST_DATABASE_URL"
    ):
        raise pytest.UsageError(
            "Set KAIRO_TEST_DATABASE_URL for required PostgreSQL integration tests"
        )

    if session.config.getoption("--require-docker") and os.environ.get("KAIRO_TEST_DOCKER") != "1":
        raise pytest.UsageError("Set KAIRO_TEST_DOCKER=1 for required sandbox tests")


@pytest.fixture(autouse=True)
def explicit_worker_ownership(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests start their own workers; do not inherit a launcher's background service flag."""
    monkeypatch.delenv("KAIRO_EMBEDDED_WORKER", raising=False)
