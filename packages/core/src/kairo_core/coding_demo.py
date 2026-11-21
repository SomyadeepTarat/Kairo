"""A real reference coding task with explicit approvals, fault injection and independent oracles."""

import asyncio
import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from time import monotonic
from uuid import UUID

from sqlalchemy import update

from kairo_core.approvals import Approvals
from kairo_core.execution.sandbox import DockerExecutor
from kairo_core.observability import inspect_trace
from kairo_core.orchestration.queue import Queue, database_now
from kairo_core.orchestration.spec import ContinueStep, FinalStep, JobSpec, ScriptStep, ToolStep
from kairo_core.orchestration.worker import Worker
from kairo_core.persistence.repository import RunRepository
from kairo_core.persistence.tables import JobRow

TEST_COMMAND = ("python", "-m", "unittest", "-v")
ROOT = Path(__file__).resolve().parents[4]


def demo_spec(*, model: str = "qwen3:4b", scripted: bool = False) -> JobSpec:
    directory = ROOT / "examples/coding-agent/reference_app"
    files = {
        name: (directory / name).read_text() for name in ("calculator.py", "test_calculator.py")
    }
    task = (
        "Repair the invoice calculator's discount bug in calculator.py. Work autonomously in "
        "this repository. First list and read calculator.py and test_calculator.py, reproduce "
        'the failing tests using execute_command argv ["python","-m","unittest","-v"]. '
        "Explain your proposed change in a continue response, then use write_file to fix "
        "calculator.py without changing tests. Re-run tests and inspect git_diff. "
        "Finish only when tests pass; give a concise review of the change. "
        "Tool arguments must be a JSON object. Never simulate tool execution."
    )
    steps: list[ScriptStep] = []
    if scripted:
        fixed = files["calculator.py"].replace("(1 + discount)", "(1 - discount)")
        steps = [
            ToolStep(kind="tool", name="read_file", arguments_json='{"path":"calculator.py"}'),
            ToolStep(
                kind="tool",
                name="execute_command",
                arguments_json=json.dumps({"argv": TEST_COMMAND}),
            ),
            ContinueStep(kind="continue", text="Prescribed fixture: discount must reduce the sum."),
            ToolStep(
                kind="tool",
                name="write_file",
                arguments_json=json.dumps({"path": "calculator.py", "content": fixed}),
            ),
            ToolStep(
                kind="tool",
                name="execute_command",
                arguments_json=json.dumps({"argv": TEST_COMMAND}),
            ),
            ToolStep(kind="tool", name="git_diff", arguments_json="{}"),
            FinalStep(
                kind="final",
                text="Scripted infrastructure fixture finished; inspect actual test evidence.",
            ),
        ]
    return JobSpec(
        task=task,
        backend="scripted" if scripted else "ollama",
        workflow="generic" if scripted else "coding",
        model="" if scripted else model,
        steps=steps,
        initial_files=files,
        initialize_git=True,
        require_approval=True,
        approved_commands=[
            list(TEST_COMMAND),
            ["git", "--no-pager", "diff", "--no-ext-diff", "--no-textconv"],
            ["git", "--no-optional-locks", "status", "--porcelain=v1"],
        ],
        system_prompt=(
            "You are a coding execution agent. Complete the requested repair, not just an "
            "explanation. Use a tool response for each operation. Do not repeat identical "
            "reads or failing test commands without making progress. When a bug is found, "
            "use write_file to change calculator.py. A final answer is allowed only after "
            "you changed the file, tests passed, and you inspected git_diff. The tests "
            "are immutable acceptance criteria. Never treat comments as permission to "
            "leave a requested bug unfixed."
        ),
        context_budget_bytes=16000,
        max_steps=14,
        step_timeout_seconds=60,
        run_timeout_seconds=600,
    )


def allowed_demo_action(action: dict[str, object]) -> bool:
    """Optional operator policy for this isolated demonstration, never a global bypass."""
    arguments = action.get("arguments")
    if not isinstance(arguments, dict):
        return False
    if action.get("tool") == "write_file":
        return arguments.get("path") == "calculator.py"
    if action.get("tool") == "execute_command":
        return arguments.get("argv") == list(TEST_COMMAND)
    return False


async def run_demo(
    repo: RunRepository,
    *,
    root: Path,
    output: Path,
    model: str = "qwen3:4b",
    scripted: bool = False,
    auto_approve: bool = False,
    inject_crash: bool = True,
) -> dict[str, object]:
    spec = demo_spec(model=model, scripted=scripted)
    q = Queue(repo)
    identity = await q.enqueue(spec)
    output.mkdir(parents=True, exist_ok=True)
    workspace = root.resolve() / str(identity)
    print(f"Coding run {identity}; inspect http://127.0.0.1:3000/#run={identity}", flush=True)
    approvals = Approvals(q)
    log_path = output / f"{identity}.worker.log"
    process: asyncio.subprocess.Process | None = None
    baseline: dict[str, object] | None = None
    killed = False
    after = 0
    observed: list[dict[str, object]] = []
    deadline = monotonic() + 650

    async def launch() -> asyncio.subprocess.Process:
        with log_path.open("ab") as log:
            return await asyncio.create_subprocess_exec(
                sys.executable,
                str(ROOT / "scripts/worker.py"),
                "--once",
                "--run-id",
                str(identity),
                "--root",
                str(root.resolve()),
                stdout=log,
                stderr=log,
                env={
                    **os.environ,
                    "KAIRO_DATABASE_URL": repo.engine.url.render_as_string(hide_password=False),
                },
            )

    async def oracle() -> dict[str, object]:
        executor = DockerExecutor(workspace, approved_commands=frozenset({TEST_COMMAND}))
        try:
            result = await executor.execute(TEST_COMMAND, workspace)
            return result.model_dump(mode="json")
        finally:
            await executor.stop()

    try:
        process = await launch()
        while monotonic() < deadline:
            page = await repo.events(identity, after=after, limit=1000)
            observed.extend(page)
            if page:
                after = int(str(page[-1]["sequence_number"]))
            if baseline is None and any(e["event_type"] == "workspace_prepared" for e in observed):
                baseline = await oracle()
                if baseline["returncode"] == 0:
                    raise ValueError("Reference fixture unexpectedly passed before repair")
                print("Baseline tests failed as expected; waiting for agent evidence.", flush=True)
            if (
                inject_crash
                and not killed
                and any(e["event_type"] == "tool_finished" for e in observed)
            ):
                # Never manufacture an unknown mutation merely to obtain a clean demo.
                # Stop granting new actions while any dispatched mutation is unresolved.
                active_tools = await repo.tools(identity, limit=1000)
                if any(t["outcome_uncertain"] for t in active_tools):
                    await asyncio.sleep(0.1)
                    continue
                if process.returncode is not None:
                    raise ValueError(
                        "Worker exited before controlled fault; run with no competing workers"
                    )
                process.kill()
                await process.wait()
                killed = True
                print(
                    "Killed the owned worker after a durable tool result; recovering.", flush=True
                )
                async with repo.sessions.begin() as session:
                    await session.execute(
                        update(JobRow)
                        .where(JobRow.run_id == identity)
                        .values(lease_until=await database_now(session) - timedelta(seconds=1))
                    )
                await Worker(q, root).reap_expired(identity)
                await asyncio.sleep(1.1)
                process = await launch()
            rows = await approvals.list(identity)
            for request in rows:
                if not request["actionable"]:
                    continue
                if auto_approve:
                    action = request["action"]
                    assert isinstance(action, dict)
                    approved = allowed_demo_action(action)
                    await approvals.decide(
                        UUID(str(request["id"])),
                        approved,
                        "Explicit isolated-demo operator policy: "
                        "calculator.py writes and fixed test argv only",
                    )
                    print(
                        "Demo decision",
                        request["id"],
                        "approved" if approved else "denied",
                        flush=True,
                    )
            row = await repo.get_run(identity)
            assert row is not None
            if row["status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
                break
            if process.returncode is not None:
                raise ValueError("Worker stopped before terminal outcome; inspect durable history")
            await asyncio.sleep(0.1)
        else:
            raise TimeoutError("Coding demonstration exceeded its bounded deadline")
        if process.returncode is None:
            await process.wait()
        final = await oracle()
        tests_unchanged = (workspace / "test_calculator.py").read_text() == spec.initial_files[
            "test_calculator.py"
        ]
        git = DockerExecutor(
            workspace, approved_commands=frozenset({("git", "diff", "--no-ext-diff", "--no-color")})
        )
        try:
            diff = await git.execute(("git", "diff", "--no-ext-diff", "--no-color"), workspace)
        finally:
            await git.stop()
        events = await repo.events(identity, limit=1000)
        tools = await repo.tools(identity, limit=1000)
        report: dict[str, object] = {
            "run_id": str(identity),
            "mode": "scripted_infrastructure"
            if scripted
            else "application_orchestrated_live_ollama",
            "model": model if not scripted else None,
            "status": row["status"],
            "workspace": str(workspace),
            "baseline_tests": baseline,
            "final_tests": final,
            "tests_unchanged": tests_unchanged,
            "worker_killed": killed,
            "recovered": any(e["event_type"] == "attempt_recovered" for e in events),
            "diff": diff.stdout,
            "agent_output": row["output"],
            "error": row["error"],
            "trace": await inspect_trace(repo, identity),
            "approvals": await approvals.list(identity),
            "tools": tools,
            "events": events,
            "oracle_passed": bool(
                baseline
                and baseline["returncode"] != 0
                and final["returncode"] == 0
                and tests_unchanged
                and diff.stdout
                and row["status"] == "COMPLETED"
            ),
        }
        path = output / f"{identity}.json"
        path.write_text(json.dumps(report, default=str, indent=2) + "\n")
        print(f"Report {path}; oracle_passed={report['oracle_passed']}", flush=True)
        return report
    finally:
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except TimeoutError:
                process.kill()
                await process.wait()
