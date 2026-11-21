"""Ensure shared validation never reports success after a failed command."""

import subprocess

import pytest

from scripts import check as check_runner


@pytest.mark.parametrize("fail_at", [None, 0, 2])
def test_check_sequence_stops_at_failure(
    monkeypatch: pytest.MonkeyPatch, fail_at: int | None
) -> None:
    monkeypatch.delenv("KAIRO_CHECK_WEB", raising=False)
    calls: list[list[str]] = []

    def run_command(
        arguments: list[str], *, cwd: object, check: bool
    ) -> subprocess.CompletedProcess[str]:
        assert cwd == check_runner.ROOT
        assert check is False
        index = len(calls)
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 7 if index == fail_at else 0)

    monkeypatch.setattr(subprocess, "run", run_command)
    assert check_runner.main() == (0 if fail_at is None else 7)
    expected_count = len(check_runner.COMMANDS) if fail_at is None else fail_at + 1
    assert len(calls) == expected_count
    assert [arguments[2:] for arguments in calls] == [
        list(arguments) for arguments in check_runner.COMMANDS[:expected_count]
    ]


def test_optional_web_gate_propagates_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAIRO_CHECK_WEB", "1")
    calls: list[list[str]] = []

    def command(
        arguments: list[str], *, cwd: object, check: bool
    ) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 9 if arguments[0] == "npm" else 0)

    monkeypatch.setattr(subprocess, "run", command)
    assert check_runner.main() == 9
    assert calls[-1] == ["npm", "--prefix", "apps/web", "run", "check"]
