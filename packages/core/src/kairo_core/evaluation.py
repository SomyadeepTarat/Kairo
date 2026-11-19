"""Fixed local experiments: real execution, explicit assertions, durable measurements."""

from __future__ import annotations

import asyncio
import hashlib
import json
import platform
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import select

from kairo_core.context import size
from kairo_core.events import Recorder, RuntimeEvent
from kairo_core.execution.sandbox import DockerExecutor, docker
from kairo_core.models import Continue, Final, Model, ModelRequest, ScriptedModel, ToolRequest
from kairo_core.observability import inspect_trace
from kairo_core.ollama import OllamaModel
from kairo_core.orchestration.queue import LeaseRecorder, Queue, database_now
from kairo_core.orchestration.spec import FinalStep, JobSpec, ToolStep
from kairo_core.orchestration.worker import Worker
from kairo_core.orchestration.workflows import Workflows, WorkflowSpec
from kairo_core.persistence.repository import RecordConflict, RunRepository
from kairo_core.persistence.tables import EvaluationRow
from kairo_core.runtime import AgentConfig, RunResult, run_agent
from kairo_core.tools import builtin_registry
from kairo_core.tools.registry import Schema, ToolContext

CASE_IDS = (
    "tool_use",
    "file_task",
    "multistep",
    "command_failure",
    "timeout",
    "interruption",
    "permission",
    "context_stress",
    "coordination",
    "coding",
)


class EvaluationConfig(Schema):
    strategy: Literal["recent", "compact"] = "recent"
    mode: Literal["single", "multi"] = "single"
    recovery: bool = True
    backend: Literal["scripted", "ollama"] = "scripted"
    model: str = Field(default="", max_length=128)
    repetitions: int = Field(default=1, ge=1, le=10)
    context_budget_bytes: int = Field(default=16000, ge=8192, le=65536)
    seed: int = Field(default=0, ge=0, le=2147483647)
    cases: list[
        Literal[
            "tool_use",
            "file_task",
            "multistep",
            "command_failure",
            "timeout",
            "interruption",
            "permission",
            "context_stress",
            "coordination",
            "coding",
        ]
    ] = Field(
        default=[
            "tool_use",
            "file_task",
            "multistep",
            "command_failure",
            "timeout",
            "interruption",
            "permission",
            "context_stress",
            "coordination",
            "coding",
        ],
        min_length=1,
        max_length=10,
    )


class SlowModel:
    async def generate(self, request: ModelRequest) -> Final:
        await asyncio.sleep(10)
        return Final("unreachable")


class InjectedInterruption(BaseException):
    """Controlled loss immediately after a committed tool acknowledgment."""


@dataclass
class InterruptAfterTool:
    delegate: Recorder

    async def start(
        self, run_id: UUID, attempt_id: UUID, task: str, config_json: str, model_name: str
    ) -> None:
        await self.delegate.start(run_id, attempt_id, task, config_json, model_name)

    async def record(self, event: RuntimeEvent) -> None:
        await self.delegate.record(event)
        if event.kind == "tool_finished":
            raise InjectedInterruption


def final_job(task: str, output: str, config: EvaluationConfig) -> JobSpec:
    return JobSpec(
        task=task,
        steps=[FinalStep(kind="final", text=output)],
        max_steps=32,
        context_strategy=config.strategy,
        context_budget_bytes=config.context_budget_bytes,
    )


class Evaluations:
    def __init__(
        self, repo: RunRepository, root: Path, suite_path: Path = Path("benchmarks/suite.json")
    ) -> None:
        self.repo, self.root, self.suite_path = repo, root, suite_path

    async def submit(self, config: EvaluationConfig) -> UUID:
        if len(set(config.cases)) != len(config.cases):
            raise ValueError("Duplicate benchmark cases")
        if config.backend == "ollama" and not config.model.strip():
            raise ValueError("Live evaluations require an explicitly selected installed model")
        manifest = json.loads(self.suite_path.read_text())
        if tuple(c["id"] for c in manifest["cases"]) != CASE_IDS:
            raise ValueError("Unsupported benchmark manifest")
        identity = uuid4()
        from importlib.metadata import version

        from sqlalchemy import text

        image = await docker("image", "inspect", "kairo-sandbox:local", "--format", "{{.Id}}")
        if image.returncode != 0:
            raise ValueError("Build the local sandbox image before running benchmarks")
        async with self.repo.sessions() as session:
            postgres = await session.scalar(text("SHOW server_version"))
        source = Path(__file__).parent
        source_digest = hashlib.sha256()
        for file in sorted(source.rglob("*.py")):
            source_digest.update(str(file.relative_to(source)).encode())
            source_digest.update(file.read_bytes())
        model_metadata: dict[str, object] | None = None
        if config.backend == "ollama":
            import httpx

            async with httpx.AsyncClient(
                base_url="http://127.0.0.1:11434", trust_env=False, timeout=5
            ) as client:
                response = await client.get("/api/tags")
                response.raise_for_status()
                installed = response.json()["models"]
                found = next((m for m in installed if m["name"] == config.model), None)
                if found is None:
                    raise ValueError("Requested model is not installed; no automatic downloads")
                server = await client.get("/api/version")
                server.raise_for_status()
                model_metadata = {
                    "name": found["name"],
                    "digest": found["digest"],
                    "ollama_version": server.json()["version"],
                }
        configuration = {
            **config.model_dump(mode="json"),
            "suite": manifest,
            "source_sha256": source_digest.hexdigest(),
            "model_metadata": model_metadata,
            "suite_sha256": hashlib.sha256(
                json.dumps(manifest, sort_keys=True).encode()
            ).hexdigest(),
            "environment": {
                "system": platform.system(),
                "machine": platform.machine(),
                "python": platform.python_version(),
                "postgres": str(postgres),
                "sandbox_image_id": image.stdout.strip(),
                "dependencies": {
                    key: version(key)
                    for key in ("httpx", "pydantic", "sqlalchemy", "opentelemetry-sdk")
                },
            },
            "budgets": {
                "max_steps": 32,
                "step_seconds": 30,
                "run_seconds": 120,
                "sandbox_image": "kairo-sandbox:local",
            },
        }
        async with self.repo.sessions.begin() as session:
            session.add(
                EvaluationRow(
                    id=identity,
                    configuration=configuration,
                    status="QUEUED",
                    results=[],
                    started_at=datetime.now(UTC),
                )
            )
        return identity

    async def get(self, identity: UUID) -> dict[str, object] | None:
        async with self.repo.sessions() as session:
            row = await session.get(EvaluationRow, identity)
            if row is None:
                return None
            return {
                "id": row.id,
                "configuration": row.configuration,
                "status": row.status,
                "results": row.results,
                "started_at": row.started_at,
                "completed_at": row.completed_at,
                "summary": summarize(row.results),
            }

    async def list_evaluations(self, limit: int = 100, offset: int = 0) -> list[dict[str, object]]:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Invalid pagination")
        async with self.repo.sessions() as session:
            rows = await session.scalars(
                select(EvaluationRow)
                .order_by(EvaluationRow.started_at.desc())
                .limit(limit)
                .offset(offset)
            )
            return [
                {
                    "id": row.id,
                    "status": row.status,
                    "configuration": row.configuration,
                    "summary": summarize(row.results),
                }
                for row in rows
            ]

    async def run(self, identity: UUID) -> None:
        async with self.repo.sessions.begin() as session:
            row = await session.scalar(
                select(EvaluationRow).where(EvaluationRow.id == identity).with_for_update()
            )
            if row is None:
                raise KeyError("Unknown evaluation")
            if row.status != "QUEUED":
                raise RecordConflict("Evaluation is already claimed; never replay automatically")
            config = EvaluationConfig.model_validate(
                {k: v for k, v in row.configuration.items() if k in EvaluationConfig.model_fields}
            )
            row.status = "RUNNING"
        results: list[dict[str, object]] = []
        try:
            for repetition in range(config.repetitions):
                for case in config.cases:
                    started = monotonic()
                    try:
                        outcome = await self.case(identity, case, repetition, config)
                    except Exception as exc:
                        import traceback

                        outcome = {
                            "passed": False,
                            "task_success": False
                            if case not in {"timeout", "permission", "command_failure"}
                            else None,
                            "error": type(exc).__name__,
                            "error_frames": [
                                {
                                    "file": Path(f.filename).name,
                                    "function": f.name,
                                    "line": f.lineno,
                                }
                                for f in traceback.extract_tb(exc.__traceback__)[-5:]
                            ],
                            "model_kind": "infrastructure_error",
                            "run_ids": [],
                        }
                    results.append(
                        {
                            "case": case,
                            "repetition": repetition,
                            **outcome,
                            "duration_seconds": monotonic() - started,
                        }
                    )
                    async with self.repo.sessions.begin() as session:
                        row = await session.get(EvaluationRow, identity)
                        assert row is not None
                        row.results = list(results)
        except BaseException:
            async with self.repo.sessions.begin() as session:
                row = await session.get(EvaluationRow, identity)
                assert row is not None
                row.status, row.completed_at = "INTERRUPTED", datetime.now(UTC)
            raise
        async with self.repo.sessions.begin() as session:
            row = await session.get(EvaluationRow, identity)
            assert row is not None
            row.status, row.completed_at = "COMPLETED", datetime.now(UTC)

    async def case(
        self, identity: UUID, case: str, repetition: int, config: EvaluationConfig
    ) -> dict[str, object]:
        workspace = self.root / str(identity) / f"{case}-{repetition}"
        workspace.mkdir(parents=True, exist_ok=False)
        live = config.backend == "ollama" and case in {"file_task", "coding"}

        def model(script: tuple[Continue | Final | ToolRequest, ...]) -> Model:
            return OllamaModel(config.model, seed=config.seed) if live else ScriptedModel(script)

        agent = AgentConfig(
            max_steps=32,
            context_budget_bytes=config.context_budget_bytes,
            context_strategy=config.strategy,
        )
        runs: list[UUID] = []
        task_success: bool | None = None
        validation: dict[str, object] | None = None
        observed_policy_bypasses: int | None = None
        if case == "coordination" or (case == "file_task" and config.mode == "multi"):
            outcome = await self.workflow_case(workspace, config, live)
            runs = outcome[1]
            passed, task_success = outcome[0], outcome[0]
        elif case == "interruption":
            passed, task_success, runs = await self.interruption(workspace, config)
        else:
            (workspace / "input.txt").write_text("benchmark input")
            approved: frozenset[tuple[str, ...]] = frozenset()
            permissions = frozenset({"workspace.read", "workspace.write", "command.execute"})
            task = "Complete the benchmark using real tools."
            code = "def add(a, b):\n    return a + b\n"
            command = (
                "python",
                "-c",
                "from solution import add; assert add(2,3)==5; assert add(-1,1)==0",
            )
            script: tuple[Continue | Final | ToolRequest, ...]
            if case == "tool_use":
                script = (
                    ToolRequest("list_directory", '{"path":"."}'),
                    ToolRequest("search_files", '{"query":"benchmark"}'),
                    Final("done"),
                )
            elif case in {"file_task", "multistep"}:
                task = (
                    "Write exactly benchmark artifact to artifact.txt, read it back, then finish."
                )
                script = (
                    ToolRequest(
                        "write_file", '{"path":"artifact.txt","content":"benchmark artifact"}'
                    ),
                    ToolRequest("read_file", '{"path":"artifact.txt"}'),
                    Final("done"),
                )
                if case == "multistep":
                    script = (
                        script[:1]
                        + (ToolRequest("search_files", '{"query":"artifact"}'),)
                        + script[1:]
                    )
            elif case == "command_failure":
                approved = frozenset({("python", "-c", "raise SystemExit(7)")})
                script = (
                    ToolRequest(
                        "execute_command", json.dumps({"argv": list(next(iter(approved)))})
                    ),
                    Final("exit observed"),
                )
            elif case == "permission":
                permissions = frozenset({"workspace.read"})
                script = (
                    ToolRequest("write_file", '{"path":"forbidden.txt","content":"denied"}'),
                    Final("denial observed"),
                )
            elif case == "context_stress":
                script = tuple([Continue("bounded history " * 600)] * 20 + [Final("done")])
            elif case == "coding":
                task = (
                    "Create solution.py defining add(a,b) to return their sum. Use write_file, "
                    "then execute this approved argv to test: "
                    + json.dumps(command)
                    + ". Finish after tests."
                )
                approved = frozenset({command})
                script = (
                    ToolRequest("write_file", json.dumps({"path": "solution.py", "content": code})),
                    ToolRequest("execute_command", json.dumps({"argv": list(command)})),
                    Final("tested"),
                )
            else:
                script = (Final("unused"),)
            executor = DockerExecutor(workspace, approved_commands=approved)
            try:
                chosen: Model = SlowModel() if case == "timeout" else model(script)
                selected = AgentConfig(step_timeout_seconds=0.02) if case == "timeout" else agent
                result = await run_agent(
                    task,
                    chosen,
                    selected,
                    tools=builtin_registry(),
                    tool_context=ToolContext(workspace, permissions, executor),
                    recorder=self.repo,
                )
                runs = [result.run_id]
                passed = self.verify(case, result, workspace, config)
                if case == "permission":
                    observed_policy_bypasses = int((workspace / "forbidden.txt").exists())
                if case in {"file_task", "multistep", "coding", "tool_use", "context_stress"}:
                    task_success = passed
                if case == "coding" and (workspace / "solution.py").is_file():
                    # Independent test execution, not trusting model final text or its claimed test.
                    checked = await executor.execute(command, workspace)
                    passed = task_success = passed and checked.returncode == 0
                    validation = {
                        "argv": list(command),
                        "returncode": checked.returncode,
                        "stdout": checked.stdout,
                        "stderr": checked.stderr,
                        "kind": "independent_sandbox_oracle",
                    }
            finally:
                await executor.stop()
        traces = [await inspect_trace(self.repo, run) for run in runs]
        return {
            "passed": passed,
            "task_success": task_success,
            "run_ids": [str(r) for r in runs],
            "model_kind": "ollama" if live else "scripted_infrastructure",
            "metrics": aggregate(traces),
            "validation": validation,
            "observed_policy_bypasses": observed_policy_bypasses,
        }

    @staticmethod
    def verify(case: str, result: RunResult, workspace: Path, config: EvaluationConfig) -> bool:
        if case == "timeout":
            return result.failure is not None and result.failure.code == "STEP_TIMEOUT"
        if case == "permission":
            return (
                not (workspace / "forbidden.txt").exists()
                and bool(result.tool_executions)
                and result.tool_executions[0].status == "FAILED"
                and not result.tool_executions[0].outcome_uncertain
            )
        if case == "command_failure":
            return (
                bool(result.tool_executions)
                and json.loads(result.tool_executions[0].output_json or "{}").get("returncode") == 7
            )
        if result.status != "COMPLETED":
            return False
        if case in {"file_task", "multistep"}:
            return (workspace / "artifact.txt").is_file() and (
                workspace / "artifact.txt"
            ).read_text() == "benchmark artifact"
        if case == "context_stress":
            return len(result.steps) == 21 and all(
                size(s.request.messages, s.request.tool_schemas_json) <= config.context_budget_bytes
                for s in result.steps
            )
        if case == "tool_use":
            return len(result.tool_executions) == 2 and all(
                t.status == "COMPLETED" for t in result.tool_executions
            )
        return (workspace / "solution.py").is_file()

    async def workflow_case(
        self, workspace: Path, config: EvaluationConfig, live: bool
    ) -> tuple[bool, list[UUID]]:
        q = Queue(self.repo)
        workflows = Workflows(q)
        executor = final_job(
            "Write exactly benchmark artifact to artifact.txt and read it back.", "done", config
        )
        executor = executor.model_copy(
            update={
                "steps": [
                    ToolStep(
                        kind="tool",
                        name="write_file",
                        arguments_json='{"path":"artifact.txt","content":"benchmark artifact"}',
                    ),
                    ToolStep(
                        kind="tool", name="read_file", arguments_json='{"path":"artifact.txt"}'
                    ),
                    FinalStep(kind="final", text="done"),
                ]
            }
        )
        executor = executor.model_copy(update={"max_steps": 24, "run_timeout_seconds": 60})
        spec = WorkflowSpec(
            planner=final_job(
                'Return final text containing JSON plan with tasks [{"key":"work"}].',
                '{"tasks":[{"key":"work"}]}',
                config,
            ),
            executors={"work": executor},
            reviewer=final_job(
                "Review handoff evidence. Return final text JSON with accepted "
                "boolean and feedback.",
                '{"accepted":true,"feedback":"checked"}',
                config,
            ),
            max_revisions=0,
        )
        spec = spec.model_copy(
            update={
                "planner": spec.planner.model_copy(
                    update={"max_steps": 4, "run_timeout_seconds": 30}
                ),
                "reviewer": spec.reviewer.model_copy(
                    update={"max_steps": 4, "run_timeout_seconds": 30}
                ),
            }
        )
        identity = await workflows.submit(spec)
        worker = Worker(
            q,
            workspace,
            model_factory=(lambda _: OllamaModel(config.model, seed=config.seed)) if live else None,
        )
        deadline = monotonic() + 120
        for _ in range(100):
            await workflows.advance(identity)
            row = await workflows.get(identity)
            assert row is not None
            if row["status"] in {"FAILED", "COMPLETED"} or monotonic() >= deadline:
                break
            state = row["state"]
            assert isinstance(state, dict) and isinstance(state["events"], list)
            for event in state["events"]:
                if event["kind"] == "delegated":
                    await worker.work_once(UUID(event["run_id"]))
            await asyncio.sleep(0.01)
        assert row is not None
        state = row["state"]
        assert isinstance(state, dict) and isinstance(state["events"], list)
        delegated = [e for e in state["events"] if e["kind"] == "delegated"]
        runs = [UUID(e["run_id"]) for e in delegated]
        paths = [
            workspace / e["run_id"] / "artifact.txt"
            for e in delegated
            if e["role"] == "executor:work"
        ]
        return (
            row["status"] == "COMPLETED"
            and bool(paths)
            and all(p.is_file() and p.read_text() == "benchmark artifact" for p in paths)
        ), runs

    async def interruption(
        self, workspace: Path, config: EvaluationConfig
    ) -> tuple[bool, bool, list[UUID]]:
        # Actual durable lease and acknowledgment gap; deterministic fault, not model randomness.
        q = Queue(self.repo, lease_seconds=0.2)
        spec = final_job("Append x once, then complete", "done", config)
        argv = ["python", "-c", "open('once.txt','a').write('x')"]
        steps = [
            ToolStep(
                kind="tool", name="execute_command", arguments_json=json.dumps({"argv": argv})
            ),
            FinalStep(kind="final", text="done"),
        ]
        spec = spec.model_copy(update={"steps": steps, "approved_commands": [argv]})
        run = await q.enqueue(spec)
        worker_id = uuid4()
        await q.register(worker_id, 1)
        claim = await q.claim(worker_id, run)
        assert claim is not None and claim.binding.run_id == run
        task_workspace = workspace / str(run)
        task_workspace.mkdir()
        # Give the real subprocess enough lease while it runs; expire explicitly after fault.
        q.lease_seconds = 30
        await q.heartbeat(claim)
        executor = DockerExecutor(
            task_workspace, approved_commands=frozenset({tuple(argv)}), identity=claim.token
        )
        try:
            try:
                await run_agent(
                    spec.task,
                    spec.build_model(),
                    spec.config(),
                    binding=claim.binding,
                    recorder=InterruptAfterTool(LeaseRecorder(q, claim)),
                    tools=builtin_registry(),
                    tool_context=ToolContext(
                        task_workspace, frozenset({"command.execute"}), executor
                    ),
                )
            except InjectedInterruption:
                pass
        finally:
            await executor.stop()
        from sqlalchemy import update

        from kairo_core.persistence.tables import JobRow

        async with self.repo.sessions.begin() as session:
            await session.execute(
                update(JobRow)
                .where(JobRow.run_id == run)
                .values(lease_until=await database_now(session) - timedelta(seconds=1))
            )
        expired = await q.expired(run)
        own = next((c for c in expired if c.binding.run_id == run), None)
        if own is None:
            raise RecordConflict("Injected lease expiry was already handled by another worker")
        if config.recovery:
            await q.finish_abandoned(own)
            await asyncio.sleep(1.05)
            await Worker(q, workspace).work_once(run)
        else:
            await q.cancel(run)
            await q.finish_abandoned(own)
        row = await self.repo.get_run(run)
        assert row is not None
        once = (task_workspace / "once.txt").read_text() == "x"
        succeeded = row["status"] == "COMPLETED"
        return once and (succeeded == config.recovery), succeeded, [run]


def aggregate(traces: list[dict[str, object] | None]) -> dict[str, object]:
    result: dict[str, object] = {
        "model_calls": 0,
        "tool_calls": 0,
        "failed_tool_calls": 0,
        "denied_policy_requests": 0,
        "retries": 0,
        "peak_context_bytes": 0,
    }
    for trace in traces:
        if trace is None:
            continue
        metrics = trace["metrics"]
        assert isinstance(metrics, dict)
        for key in result:
            value = int(str(metrics[key]))
            result[key] = (
                max(int(str(result[key])), value)
                if key == "peak_context_bytes"
                else int(str(result[key])) + value
            )
    tokens: dict[str, int] = {}
    for trace in traces:
        if trace is None:
            continue
        metrics = trace["metrics"]
        assert isinstance(metrics, dict)
        usage = metrics.get("token_usage")
        if isinstance(usage, dict):
            for key, value in usage.items():
                tokens[str(key)] = tokens.get(str(key), 0) + int(value)
    result["token_usage"] = tokens or None
    calls = int(str(result["tool_calls"]))
    failures = int(str(result["failed_tool_calls"]))
    result["tool_call_success_rate"] = (calls - failures) / calls if calls else None
    return result


def summarize(results: list[dict[str, object]]) -> dict[str, object]:
    task_results = [r for r in results if r.get("task_success") is not None]
    recovery_results = [r for r in results if r["case"] == "interruption"]
    return {
        "interrupted_task_completion_rate": (
            sum(r.get("task_success") is True for r in recovery_results) / len(recovery_results)
            if recovery_results
            else None
        ),
        "observed_policy_bypasses": sum(
            int(str(r.get("observed_policy_bypasses") or 0)) for r in results
        ),
        "scenario_count": len(results),
        "passed_scenarios": sum(r.get("passed") is True for r in results),
        "task_count": len(task_results),
        "task_successes": sum(r["task_success"] is True for r in task_results),
        "task_completion_rate": (
            sum(r["task_success"] is True for r in task_results) / len(task_results)
            if task_results
            else None
        ),
        "outcome_groups": {
            label: {
                "cases": sum(r.get("model_kind") == label for r in results),
                "passed": sum(
                    r.get("model_kind") == label and r.get("passed") is True for r in results
                ),
            }
            for label in {str(r.get("model_kind", "infrastructure_error")) for r in results}
        },
        "total_case_seconds": sum(float(str(r["duration_seconds"])) for r in results),
    }


def compare(left: dict[str, object], right: dict[str, object]) -> dict[str, object]:
    a, b = left["configuration"], right["configuration"]
    assert isinstance(a, dict) and isinstance(b, dict)
    fixed = (
        "suite_sha256",
        "source_sha256",
        "cases",
        "repetitions",
        "context_budget_bytes",
        "seed",
        "environment",
        "budgets",
    )
    mismatches = [key for key in fixed if a.get(key) != b.get(key)]
    if mismatches:
        raise ValueError("Incomparable evaluation conditions: " + ", ".join(mismatches))
    if left["status"] != "COMPLETED" or right["status"] != "COMPLETED":
        raise ValueError("Compare only completed evaluations")
    from statistics import mean, stdev

    lresults, rresults = left["results"], right["results"]
    assert isinstance(lresults, list) and isinstance(rresults, list)
    paired = []
    cases = a["cases"]
    assert isinstance(cases, list)
    for case in cases:
        x = [float(r["duration_seconds"]) for r in lresults if r["case"] == case]
        y = [float(r["duration_seconds"]) for r in rresults if r["case"] == case]
        if not x or len(x) != len(y):
            raise ValueError("Missing paired results")
        paired.append(
            {
                "case": case,
                "n": len(x),
                "left_mean_seconds": mean(x),
                "right_mean_seconds": mean(y),
                "mean_delta_seconds": mean(y) - mean(x),
                "left_sample_sd": stdev(x) if len(x) > 1 else None,
                "right_sample_sd": stdev(y) if len(y) > 1 else None,
            }
        )
    return {
        "paired_case_timings": paired,
        "left_model_metadata": a.get("model_metadata"),
        "right_model_metadata": b.get("model_metadata"),
        "left": str(left["id"]),
        "right": str(right["id"]),
        "changed_strategies": {
            key: [a[key], b[key]]
            for key in ("strategy", "mode", "recovery", "backend", "model")
            if a[key] != b[key]
        },
        "left_summary": left["summary"],
        "right_summary": right["summary"],
        "caution": (
            "Small local samples; deterministic infrastructure outcomes "
            "are not model quality evidence."
        ),
    }
