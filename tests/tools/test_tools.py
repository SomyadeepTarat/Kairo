"""Actual workspace I/O and deterministic command-interface/registry tests."""

import asyncio
import json
import os
from pathlib import Path
from typing import cast

import pytest
from kairo_core.models import Final, ScriptedModel, ToolRequest
from kairo_core.runtime import run_agent
from kairo_core.state import RunStatus
from kairo_core.tools import builtin_registry
from kairo_core.tools.registry import (
    CommandResult,
    Schema,
    Tool,
    ToolContext,
    ToolRegistry,
    ToolStatus,
)


def invoke(tmp_path: Path, name: str, payload: str, *, write: bool = True) -> object:
    permissions = (
        frozenset({"workspace.read", "workspace.write"}) if write else frozenset({"workspace.read"})
    )
    return asyncio.run(builtin_registry().invoke(name, payload, ToolContext(tmp_path, permissions)))


def test_agent_really_writes_and_reads_a_file(tmp_path: Path) -> None:
    model = ScriptedModel(
        (
            ToolRequest("write_file", '{"path":"hello.txt","content":"hello kairo"}'),
            ToolRequest("read_file", '{"path":"hello.txt"}'),
            Final("script finished"),
        )
    )
    result = asyncio.run(
        run_agent(
            "exercise file tools",
            model,
            tools=builtin_registry(),
            tool_context=ToolContext(tmp_path, frozenset({"workspace.read", "workspace.write"})),
        )
    )
    assert result.status is RunStatus.COMPLETED
    assert (tmp_path / "hello.txt").read_text() == "hello kairo"
    assert len(result.tool_executions) == 2
    assert all(item.status is ToolStatus.COMPLETED for item in result.tool_executions)
    assert json.loads(result.tool_executions[1].output_json or "null") == {"content": "hello kairo"}
    assert result.steps[2].request.messages[-1].role == "tool"
    assert result.steps[0].request.tool_schemas_json != "[]"
    assert [edge.target for edge in result.transitions].count(RunStatus.WAITING_FOR_TOOL) == 2


@pytest.mark.parametrize(
    "payload", ["{}", '{"path":3}', '{"path":"x","extra":true}', "{broken", "[]"]
)
def test_invalid_input_never_writes(tmp_path: Path, payload: str) -> None:
    result = asyncio.run(builtin_registry().invoke("write_file", payload, ToolContext(tmp_path)))
    assert result.error_code == "INVALID_INPUT"
    assert list(tmp_path.iterdir()) == []


def test_permission_denial_and_unknown_tool(tmp_path: Path) -> None:
    registry = builtin_registry()
    denied = asyncio.run(
        registry.invoke("write_file", '{"path":"x","content":"x"}', ToolContext(tmp_path))
    )
    unknown = asyncio.run(registry.invoke("not_registered", "{}", ToolContext(tmp_path)))
    assert denied.error_code == "PERMISSION_DENIED"
    assert not denied.outcome_uncertain
    assert unknown.error_code == "UNKNOWN_TOOL"
    assert not (tmp_path / "x").exists()


@pytest.mark.parametrize(
    "path", ["../escape", "/tmp/escape", ".git/config", ".env", "a/../../escape"]
)
def test_unsafe_paths_are_rejected(tmp_path: Path, path: str) -> None:
    result = asyncio.run(
        builtin_registry().invoke(
            "write_file",
            json.dumps({"path": path, "content": "bad"}),
            ToolContext(tmp_path, frozenset({"workspace.write"})),
        )
    )
    assert result.status is ToolStatus.FAILED


def test_symlink_and_hardlink_do_not_overwrite_outside(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("safe")
    (workspace / "link").symlink_to(outside)
    os.link(outside, workspace / "hard")
    for path in ("link", "hard"):
        result = asyncio.run(
            builtin_registry().invoke(
                "write_file",
                json.dumps({"path": path, "content": "bad"}),
                ToolContext(workspace, frozenset({"workspace.write"})),
            )
        )
        assert result.status is ToolStatus.FAILED
    assert outside.read_text() == "safe"


def test_list_and_literal_search(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("needle")
    (tmp_path / "b.txt").write_text("hay")
    (tmp_path / ".env").write_text("secret")
    registry = builtin_registry()
    listing = asyncio.run(registry.invoke("list_directory", '{"path":"."}', ToolContext(tmp_path)))
    search = asyncio.run(
        registry.invoke("search_files", '{"query":"needle"}', ToolContext(tmp_path))
    )
    assert json.loads(listing.output_json or "null") == {"entries": ["a.txt", "b.txt"]}
    assert json.loads(search.output_json or "null") == {"entries": ["a.txt"]}


def test_command_requires_an_explicit_executor(tmp_path: Path) -> None:
    context = ToolContext(tmp_path, frozenset({"command.execute"}))
    record = asyncio.run(
        builtin_registry().invoke("execute_command", '{"argv":["echo","hi"]}', context)
    )
    assert record.error_code == "EXECUTOR_UNAVAILABLE"


def test_git_uses_fixed_argv_through_injected_test_executor(tmp_path: Path) -> None:
    class TestExecutor:
        async def execute(self, argv: tuple[str, ...], workspace: Path) -> CommandResult:
            assert argv == ("git", "--no-optional-locks", "status", "--porcelain=v1")
            assert workspace == tmp_path
            return CommandResult(stdout="?? example.txt", stderr="", returncode=0)

    context = ToolContext(tmp_path, frozenset({"command.execute"}), TestExecutor())
    record = asyncio.run(builtin_registry().invoke("git_status", "{}", context))
    assert record.status is ToolStatus.COMPLETED


def test_registry_rejects_duplicates_and_invalid_output(tmp_path: Path) -> None:
    class Input(Schema):
        pass

    class Output(Schema):
        answer: str

    async def broken(value: Input, context: ToolContext) -> Output:
        return cast(Output, Input())

    registry = ToolRegistry()
    tool = Tool("broken", "test double", Input, Output, broken, "workspace.read")
    registry.register(tool)
    with pytest.raises(ValueError):
        registry.register(tool)
    result = asyncio.run(registry.invoke("broken", "{}", ToolContext(tmp_path)))
    assert result.error_code == "INVALID_OUTPUT"


def test_tool_timeout_joins_handler(tmp_path: Path) -> None:
    stopped = False

    class Input(Schema):
        pass

    async def blocked(value: Input, context: ToolContext) -> Input:
        nonlocal stopped
        try:
            await asyncio.Event().wait()
        finally:
            stopped = True
        return Input()

    registry = ToolRegistry()
    registry.register(
        Tool(
            "blocked", "test double", Input, Input, blocked, "workspace.read", timeout_seconds=0.01
        )
    )
    result = asyncio.run(registry.invoke("blocked", "{}", ToolContext(tmp_path)))
    assert result.status is ToolStatus.TIMED_OUT
    assert stopped


def test_uncertain_write_stops_instead_of_automatically_repeating(tmp_path: Path) -> None:
    from kairo_core.runtime import FailureCode
    from kairo_core.tools.registry import SideEffect

    class Input(Schema):
        pass

    async def partial_write(value: Input, context: ToolContext) -> Input:
        (context.workspace / "partial.txt").write_text("side effect happened")
        await asyncio.Event().wait()
        return Input()

    registry = ToolRegistry()
    registry.register(
        Tool(
            "partial",
            "test handler",
            Input,
            Input,
            partial_write,
            "workspace.write",
            SideEffect.WORKSPACE_WRITE,
            timeout_seconds=0.01,
        )
    )
    result = asyncio.run(
        run_agent(
            "task",
            ScriptedModel((ToolRequest("partial", "{}"), Final("unused"))),
            tools=registry,
            tool_context=ToolContext(tmp_path, frozenset({"workspace.write"})),
        )
    )
    assert result.failure is not None
    assert result.failure.code is FailureCode.TOOL_UNCERTAIN
    assert len(result.steps) == 1
    assert result.tool_executions[0].outcome_uncertain
    assert (tmp_path / "partial.txt").exists()


def test_event_cancellation_records_tool_cleanup(tmp_path: Path) -> None:
    async def scenario() -> None:
        started, stopped, cancellation = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class Input(Schema):
            pass

        async def blocked(value: Input, context: ToolContext) -> Input:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
            return Input()

        registry = ToolRegistry()
        registry.register(Tool("blocked", "test handler", Input, Input, blocked, "workspace.read"))
        execution = asyncio.create_task(
            run_agent(
                "task",
                ScriptedModel((ToolRequest("blocked", "{}"),)),
                tools=registry,
                tool_context=ToolContext(tmp_path),
                cancellation=cancellation,
            )
        )
        await started.wait()
        cancellation.set()
        result = await execution
        assert result.status is RunStatus.CANCELLED
        assert stopped.is_set()
        assert result.tool_executions[0].status is ToolStatus.CANCELLED

    asyncio.run(asyncio.wait_for(scenario(), timeout=2))
