"""Real Docker isolation tests; no host shell executor or inference."""

import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from kairo_core.execution.sandbox import DockerExecutor, SandboxLimits, Workspaces, docker
from kairo_core.models import Final, ScriptedModel, ToolRequest
from kairo_core.runtime import run_agent
from kairo_core.state import RunStatus
from kairo_core.tools import builtin_registry
from kairo_core.tools.registry import ToolContext, ToolError


def test_managed_workspace_and_policy_arguments(tmp_path: Path) -> None:
    manager = Workspaces(tmp_path / "workspaces")
    identity = uuid4()
    workspace = manager.create(identity)
    assert manager.get(identity) == workspace
    with pytest.raises(FileExistsError):
        manager.create(identity)
    executor = DockerExecutor(workspace)
    args = executor.create_arguments("test-name", ("python", "--version"))
    assert args[args.index("--network") + 1] == "none"
    assert "--read-only" in args and "--privileged" not in args
    assert args[args.index("--cap-drop") + 1] == "ALL"
    assert args[-3:] == ("kairo-sandbox:local", "python", "--version")
    assert sum(arg == "--mount" for arg in args) == 1


def test_exact_command_approval_and_workspace_binding(tmp_path: Path) -> None:
    executor = DockerExecutor(tmp_path, approved_commands=frozenset({("python", "--version")}))
    with pytest.raises(ToolError, match="not been approved"):
        asyncio.run(executor.execute(("python", "-c", "print('different')"), tmp_path))
    (tmp_path / "link").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ToolError, match="another workspace"):
        asyncio.run(executor.execute(("python", "--version"), tmp_path / "link"))


@pytest.fixture
def docker_ready() -> None:
    if os.environ.get("KAIRO_TEST_DOCKER") != "1":
        pytest.skip(
            "Set KAIRO_TEST_DOCKER=1 and build kairo-sandbox:local for actual container tests"
        )


@pytest.mark.docker
def test_real_sandbox_agent_and_isolation(tmp_path: Path, docker_ready: None) -> None:
    async def scenario() -> None:
        command = (
            "python",
            "-c",
            "from pathlib import Path; Path('result.txt').write_text('sandbox'); print('ok')",
        )
        executor = DockerExecutor(tmp_path, approved_commands=frozenset({command}))
        result = await run_agent(
            "scripted filesystem/command task",
            ScriptedModel(
                (
                    ToolRequest("execute_command", json.dumps({"argv": command})),
                    ToolRequest("read_file", '{"path":"result.txt"}'),
                    Final("script complete"),
                )
            ),
            tools=builtin_registry(),
            tool_context=ToolContext(
                tmp_path, frozenset({"command.execute", "workspace.read"}), executor
            ),
        )
        assert result.status is RunStatus.COMPLETED
        assert (tmp_path / "result.txt").read_text() == "sandbox"
        assert "sandbox" in (result.tool_executions[1].output_json or "")
        remaining = await docker(
            "ps", "-aq", "--filter", f"label=kairo.execution={executor.identity}"
        )
        assert not remaining.stdout.strip()

    asyncio.run(scenario())


@pytest.mark.docker
def test_no_host_secrets_network_or_root_writes(
    tmp_path: Path, docker_ready: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KAIRO_HOST_SECRET", "never_in_container")
    code = """import os, socket
from pathlib import Path
assert os.getuid() != 0
assert 'KAIRO_HOST_SECRET' not in os.environ
assert not Path('/var/run/docker.sock').exists()
assert not Path('/Users').exists()
try:
    Path('/forbidden').write_text('x')
except OSError:
    pass
else:
    raise AssertionError('root was writable')
try:
    socket.create_connection(('1.1.1.1', 53), timeout=0.3)
except OSError:
    pass
else:
    raise AssertionError('network was available')
print('restricted')
"""
    command = ("python", "-c", code)
    executor = DockerExecutor(tmp_path, approved_commands=frozenset({command}))
    result = asyncio.run(executor.execute(command, tmp_path))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "restricted"


@pytest.mark.docker
@pytest.mark.parametrize("mode", ["timeout", "output", "cancel"])
def test_cleanup_after_timeout_output_limit_or_cancellation(
    tmp_path: Path, docker_ready: None, mode: str
) -> None:
    async def scenario() -> None:
        code = "print('x'*1000000)" if mode == "output" else "import time; time.sleep(60)"
        command = ("python", "-c", code)
        executor = DockerExecutor(
            tmp_path,
            approved_commands=frozenset({command}),
            limits=SandboxLimits(timeout_seconds=1, output_bytes=1024),
        )
        execution = asyncio.create_task(executor.execute(command, tmp_path))
        if mode == "cancel":
            await asyncio.sleep(0.3)
            execution.cancel()
            with pytest.raises(asyncio.CancelledError):
                await execution
        elif mode == "timeout":
            with pytest.raises(TimeoutError):
                await execution
        else:
            with pytest.raises(ToolError, match="output exceeds"):
                await execution
        remaining = await docker(
            "ps", "-aq", "--filter", f"label=kairo.execution={executor.identity}"
        )
        assert not remaining.stdout.strip()

    asyncio.run(scenario())


def test_denied_command_is_recorded_without_an_uncertain_side_effect(tmp_path: Path) -> None:
    executor = DockerExecutor(tmp_path)
    context = ToolContext(tmp_path, frozenset({"command.execute"}), executor)
    result = asyncio.run(
        builtin_registry().invoke("execute_command", '{"argv":["python","--version"]}', context)
    )
    assert result.error_code == "APPROVAL_REQUIRED"
    assert not result.outcome_uncertain


def test_output_limit_reaps_a_cli_with_saturated_pipes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A labelled fake control-plane CLI forces the real OS pipe/backpressure race."""
    import sys

    program = tmp_path / "docker"
    program.write_text(
        f"#!{sys.executable}\nimport os, time\nos.write(1, b'x' * 1048576)\ntime.sleep(30)\n"
    )
    program.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])

    async def scenario() -> None:
        with pytest.raises(ToolError, match="output exceeds"):
            await asyncio.wait_for(docker("fixture", limit=1024), timeout=3)

    asyncio.run(scenario())
