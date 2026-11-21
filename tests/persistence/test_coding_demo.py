"""Prescribed model infrastructure test with real Git, worker SIGKILL and sandbox oracles."""

import asyncio
from pathlib import Path

import pytest
from kairo_core.coding_demo import allowed_demo_action, run_demo
from kairo_core.orchestration.spec import FinalStep, JobSpec

from tests.persistence.test_repository import repository

pytestmark = [pytest.mark.postgres, pytest.mark.docker]


def test_coding_fixture_recovers_and_verifies_real_patch(database_url: str, tmp_path: Path) -> None:
    async def scenario() -> None:
        repo = repository(database_url)
        try:
            report = await run_demo(
                repo,
                root=tmp_path / "workspaces",
                output=tmp_path / "reports",
                scripted=True,
                auto_approve=True,
            )
            assert report["oracle_passed"] and report["worker_killed"] and report["recovered"]
            assert report["tests_unchanged"] and "1 - discount" in str(report["diff"])
            trace = report["trace"]
            assert isinstance(trace, dict) and isinstance(trace["metrics"], dict)
            assert trace["metrics"]["retries"] == 1
            tools = report["tools"]
            assert isinstance(tools, list)
            assert sum(t["name"] == "write_file" for t in tools) == 1
        finally:
            await repo.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("path", ["../outside", "/absolute", ".git/config", ".env", "a/.env.local"])
def test_unsafe_seed_rejected(path: str) -> None:
    with pytest.raises(ValueError):
        JobSpec(task="seed", steps=[FinalStep(kind="final", text="x")], initial_files={path: "bad"})


def test_demo_policy_does_not_approve_test_tampering_or_arbitrary_commands() -> None:
    assert not allowed_demo_action(
        {"tool": "write_file", "arguments": {"path": "test_calculator.py"}}
    )
    assert not allowed_demo_action(
        {"tool": "execute_command", "arguments": {"argv": ["sh", "-c", "anything"]}}
    )
    assert allowed_demo_action({"tool": "write_file", "arguments": {"path": "calculator.py"}})
