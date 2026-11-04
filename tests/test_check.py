"""Ensure shared validation never reports success after a failed command."""

import subprocess

import pytest

from scripts import check as check_runner


@pytest.mark.parametrize("fail_at", [None, 0, 2])
def test_check_sequence_stops_at_failure(
    monkeypatch: pytest.MonkeyPatch, fail_at: int | None
) -> None:
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
