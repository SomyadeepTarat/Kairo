"""A local worker owns a DB lease and a filesystem lock, then runs the custom kernel."""

import asyncio
import fcntl
import json
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Self
from uuid import UUID, uuid4

from kairo_core.events import event_now
from kairo_core.execution.sandbox import DockerExecutor, Workspaces
from kairo_core.models import Model
from kairo_core.orchestration.queue import Claim, LeaseLost, LeaseRecorder, Queue
from kairo_core.orchestration.spec import JobSpec
from kairo_core.runtime import RunResult, run_agent
from kairo_core.tools import builtin_registry
from kairo_core.tools.registry import ToolContext


class WorkspaceBusy(RuntimeError):
    pass


class WorkspaceLock:
    def __init__(self, root: Path, identity: UUID) -> None:
        directory = root / ".locks"
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = directory / str(identity)
        self.fd: int | None = None

    def __enter__(self) -> Self:
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise WorkspaceBusy("An old local execution still owns the workspace") from None
        self.fd = fd
        return self

    def __exit__(self, *args: object) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class Worker:
    def __init__(
        self,
        queue: Queue,
        root: Path,
        *,
        capacity: int = 1,
        model_factory: Callable[[JobSpec], Model] | None = None,
    ) -> None:
        if not 1 <= capacity <= 32:
            raise ValueError("Invalid worker capacity")
        self.queue, self.workspaces, self.capacity = queue, Workspaces(root), capacity
        self.id = uuid4()

        def default_model(spec: JobSpec) -> Model:
            if spec.backend == "ollama":
                if spec.workflow == "coding":
                    from kairo_core.coding_model import CodingWorkflowModel

                    return CodingWorkflowModel(spec.model)
                from kairo_core.ollama import OllamaModel

                return OllamaModel(spec.model)
            return spec.build_model()

        self.model_factory = model_factory or default_model

    def workspace(self, identity: UUID) -> Path:
        path = self.workspaces.root / str(identity)
        return self.workspaces.get(identity) if path.exists() else self.workspaces.create(identity)

    async def work_once(self, run_id: UUID | None = None) -> RunResult | None:
        await self.queue.register(self.id, self.capacity)
        claim = await self.queue.claim(self.id, run_id)
        if claim is None:
            return None
        with WorkspaceLock(self.workspaces.root, claim.binding.run_id):
            continuation = await self.queue.continuation(claim)
            path = self.workspaces.root / str(claim.binding.run_id)
            if (
                continuation is not None
                and (not path.is_dir() or path.is_symlink())
                and await self.queue.workspace_required(claim)
            ):
                await self.queue.block_owned(claim, "WORKSPACE_MISSING")
                return None
            workspace = self.workspace(claim.binding.run_id)
            executor = DockerExecutor(
                workspace,
                identity=claim.token,
                approved_commands=frozenset(tuple(argv) for argv in claim.spec.approved_commands),
            )
            if not await self.queue.workspace_required(claim):
                await self.prepare(claim, workspace)
            cancellation = asyncio.Event()

            async def renew() -> None:
                while True:
                    await asyncio.sleep(self.queue.lease_seconds / 3)
                    if await self.queue.heartbeat(claim):
                        cancellation.set()

            from kairo_core.approvals import Approvals

            async def authorize(invocation: UUID, name: str, arguments: str, risk: str) -> bool:
                return await Approvals(self.queue).wait(claim, invocation, name, arguments, risk)

            execution = asyncio.create_task(
                run_agent(
                    claim.spec.task,
                    self.model_factory(claim.spec),
                    claim.spec.config(),
                    binding=claim.binding,
                    recorder=LeaseRecorder(self.queue, claim),
                    tools=builtin_registry(),
                    tool_context=ToolContext(
                        workspace,
                        frozenset(claim.spec.permissions),
                        executor,
                    ),
                    cancellation=cancellation,
                    resume=continuation,
                    authorize=authorize if claim.spec.require_approval else None,
                )
            )
            renewal = asyncio.create_task(renew())
            try:
                done, _ = await asyncio.wait(
                    (execution, renewal), return_when=asyncio.FIRST_COMPLETED
                )
                if execution in done:
                    return execution.result()
                renewal.result()  # Lease/storage failure must cancel local execution.
                raise LeaseLost("Lease renewal stopped")
            finally:
                renewal.cancel()
                if not execution.done():
                    execution.cancel()
                await asyncio.gather(execution, renewal, return_exceptions=True)
                await executor.stop()

    async def prepare(self, claim: "Claim", workspace: Path) -> None:
        """Explicit caller fixtures, replayed idempotently only before first RUNNING."""
        registry = builtin_registry()
        for name, content in claim.spec.initial_files.items():
            record = await registry.invoke(
                "write_file",
                json.dumps({"path": name, "content": content}),
                ToolContext(workspace, frozenset({"workspace.write"})),
            )
            if record.status != "COMPLETED":
                raise ValueError("Workspace fixture preparation failed")
        if claim.spec.initialize_git:
            commands = (
                ("git", "init"),
                ("git", "rev-parse", "--verify", "HEAD"),
                ("git", "add", "."),
                (
                    "git",
                    "-c",
                    "user.name=Kairo demo",
                    "-c",
                    "user.email=kairo@localhost",
                    "commit",
                    "-m",
                    "Reference application baseline",
                ),
            )
            executor = DockerExecutor(
                workspace, identity=claim.token, approved_commands=frozenset(commands)
            )
            try:
                initialized = await executor.execute(commands[0], workspace)
                if initialized.returncode:
                    raise ValueError("Cannot initialize isolated demo repository")
                head = await executor.execute(commands[1], workspace)
                if head.returncode:
                    for command in commands[2:]:
                        if (await executor.execute(command, workspace)).returncode:
                            raise ValueError("Cannot record isolated baseline")
            finally:
                await executor.stop()
        if claim.spec.initial_files or claim.spec.initialize_git:
            await LeaseRecorder(self.queue, claim).record(
                event_now(
                    claim.binding.run_id,
                    claim.binding.attempt_id,
                    "workspace_prepared",
                    json.dumps(
                        {"files": list(claim.spec.initial_files), "git": claim.spec.initialize_git}
                    ),
                )
            )

    async def reap_expired(self, run_id: UUID | None = None) -> int:
        count = 0
        for claim in await self.queue.expired(run_id):
            path = self.workspaces.root / str(claim.binding.run_id)
            existing = path.is_dir() and not path.is_symlink()
            executor = DockerExecutor(self.workspaces.root, identity=claim.token)
            await executor.stop()
            try:
                with WorkspaceLock(self.workspaces.root, claim.binding.run_id):
                    await self.queue.finish_abandoned(claim, workspace_exists=existing)
                    count += 1
            except (WorkspaceBusy, LeaseLost):
                continue
        return count

    async def run(self, stop: asyncio.Event) -> None:
        async def slot() -> None:
            while not stop.is_set():
                try:
                    await self.work_once()
                except Exception as exc:
                    logging.error("Worker iteration failed: %s", type(exc).__name__)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=0.25)
                except TimeoutError:
                    pass

        async def reap() -> None:
            while not stop.is_set():
                try:
                    await self.reap_expired()
                except Exception as exc:
                    logging.error("Reaper failed: %s", type(exc).__name__)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=1)
                except TimeoutError:
                    pass

        tasks = [asyncio.create_task(slot()) for _ in range(self.capacity)]
        tasks.append(asyncio.create_task(reap()))
        try:
            await stop.wait()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
