"""Validate prerequisite classification without relying on the developer's machine."""

import pytest

from scripts.doctor import inspect_environment


def available(name: str) -> str | None:
    return f"/tools/{name}"


def test_required_tools_present() -> None:
    required, optional = inspect_environment(available, (3, 13))
    assert all(required.values())
    assert all(optional.values())


@pytest.mark.parametrize("missing", ["git", "uv"])
def test_missing_required_tool_fails_readiness(missing: str) -> None:
    required, _ = inspect_environment(
        lambda name: None if name == missing else available(name), (3, 13)
    )
    assert not all(required.values())
    assert not required[missing]


def test_future_services_are_optional() -> None:
    required, optional = inspect_environment(
        lambda name: available(name) if name in {"git", "uv"} else None, (3, 13)
    )
    assert all(required.values())
    assert not any(optional.values())


@pytest.mark.parametrize("version", [(3, 11), (3, 12), (3, 14)])
def test_wrong_project_python_is_reported(version: tuple[int, int]) -> None:
    required, _ = inspect_environment(available, version)
    assert not required["python_3_13"]


@pytest.mark.parametrize("ready, expected", [(True, 0), (False, 1)])
def test_cli_returns_readiness_exit_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], ready: bool, expected: int
) -> None:
    from scripts import doctor

    monkeypatch.setattr(doctor, "inspect_environment", lambda: ({"required": ready}, {}))
    assert doctor.main() == expected
    assert "service readiness is not checked" in capsys.readouterr().out
