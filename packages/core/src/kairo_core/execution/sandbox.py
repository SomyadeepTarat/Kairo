"""Explicit Docker lifecycle with bounded I/O and one workspace mount."""

import asyncio
import os
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from kairo_core.tools.registry import CommandResult, ToolError


@dataclass(frozen=True)
class SandboxLimits:
    timeout_seconds: float = 10
    memory_mb: int = 256
    cpus: float = 1
    pids: int = 64
    output_bytes: int = 262_144

    def __post_init__(self) -> None:
        import math

        for value in (
            self.timeout_seconds,
            self.memory_mb,
            self.cpus,
            self.pids,
            self.output_bytes,
        ):
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError("Sandbox limits must be finite and positive")


class Workspaces:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def create(self, identity: UUID) -> Path:
        path = self.root / str(identity)
        path.mkdir(mode=0o700)  # Never reuse an existing directory implicitly.
        return path

    def get(self, identity: UUID) -> Path:
        path = self.root / str(identity)
        if not path.is_dir() or path.is_symlink():
            raise ValueError("Unknown or symlinked managed workspace")
        return path


async def docker(*arguments: str, timeout: float = 15, limit: int = 262_144) -> CommandResult:
    """Control-plane CLI invocation only; model strings never become Docker flags."""
    process = await asyncio.create_subprocess_exec(
        "docker", *arguments, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    total = 0

    async def read(stream: asyncio.StreamReader | None) -> bytes:
        nonlocal total
        assert stream is not None
        pieces = []
        while chunk := await stream.read(16_384):
            total += len(chunk)
            if total > limit:
                raise ToolError("OUTPUT_LIMIT", "Container output exceeds its limit")
            pieces.append(chunk)
        return b"".join(pieces)

    readers = (asyncio.create_task(read(process.stdout)), asyncio.create_task(read(process.stderr)))
    try:
        async with asyncio.timeout(timeout):
            stdout, stderr = await asyncio.gather(*readers)
            code = await process.wait()
        return CommandResult(
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
            returncode=code,
        )
    finally:
        for task in readers:
            if not task.done():
                task.cancel()
        await asyncio.gather(*readers, return_exceptions=True)
        if process.returncode is None:
            process.kill()

        async def discard(stream: asyncio.StreamReader | None) -> None:
            assert stream is not None
            while await stream.read(16_384):
                pass

        # A paused full pipe can prevent Process.wait() from finishing even after
        # kill. Drain without retaining bytes, and reap concurrently.
        await asyncio.gather(discard(process.stdout), discard(process.stderr), process.wait())


class DockerExecutor:
    def __init__(
        self,
        workspace: Path,
        *,
        approved_commands: frozenset[tuple[str, ...]] = frozenset(),
        identity: UUID | None = None,
        image: str = "kairo-sandbox:local",
        limits: SandboxLimits | None = None,
    ) -> None:
        if not workspace.is_dir() or workspace.is_symlink():
            raise ValueError("Workspace must be an existing nonsymlink directory")
        self.workspace = workspace.resolve()
        if any(character in str(self.workspace) for character in (",", "\n", "\x00")):
            raise ValueError("Unsupported workspace mount path")
        self.approved_commands = approved_commands
        self.identity = identity or uuid4()
        self.image = image
        self.limits = limits or SandboxLimits()

    def create_arguments(self, name: str, argv: tuple[str, ...]) -> tuple[str, ...]:
        limits = self.limits
        uid = os.getuid()
        if uid == 0:
            raise ValueError("Run Kairo as a nonroot local developer")
        return (
            "create",
            "--pull",
            "never",
            "--name",
            name,
            "--label",
            "kairo.managed=true",
            "--label",
            f"kairo.execution={self.identity}",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(limits.pids),
            "--memory",
            f"{limits.memory_mb}m",
            "--memory-swap",
            f"{limits.memory_mb}m",
            "--cpus",
            str(limits.cpus),
            "--ulimit",
            "fsize=16777216:16777216",
            "--user",
            f"{uid}:{os.getgid()}",
            "--workdir",
            "/workspace",
            "--env",
            "HOME=/tmp",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,noexec,size=64m,mode=1777",
            "--log-driver",
            "none",
            "--mount",
            f"type=bind,source={self.workspace},target=/workspace",
            self.image,
            *argv,
        )

    async def execute(self, argv: tuple[str, ...], workspace: Path) -> CommandResult:
        if workspace.is_symlink() or workspace.resolve() != self.workspace:
            raise ToolError(
                "WORKSPACE_MISMATCH",
                "Executor is bound to another workspace",
                side_effect_possible=False,
            )
        if not argv or argv not in self.approved_commands:
            raise ToolError(
                "APPROVAL_REQUIRED",
                "This exact command has not been approved",
                side_effect_possible=False,
            )
        name = f"kairo-{self.identity}-{uuid4().hex[:12]}"
        try:
            created = await docker(*self.create_arguments(name, argv))
            if created.returncode or not re.fullmatch(r"[0-9a-f]{64}", created.stdout.strip()):
                raise ToolError("SANDBOX_CREATE_FAILED", "Docker could not create the sandbox")
            result = await docker(
                "start",
                "--attach",
                name,
                timeout=self.limits.timeout_seconds,
                limit=self.limits.output_bytes,
            )
            inspected = await docker("inspect", "--format", "{{.State.ExitCode}}", name)
            if inspected.returncode:
                raise ToolError("SANDBOX_INSPECT_FAILED", "Container result is unavailable")
            return CommandResult(
                stdout=result.stdout, stderr=result.stderr, returncode=int(inspected.stdout.strip())
            )
        finally:
            # Names are generated before create, so cancellation during create is also cleaned up.
            removed = await docker("rm", "--force", name)
            if removed.returncode and "No such container" not in removed.stderr:
                raise ToolError(
                    "SANDBOX_CLEANUP_FAILED", "Container removal could not be confirmed"
                )

    async def stop(self) -> None:
        result = await docker(
            "ps", "--all", "--quiet", "--filter", f"label=kairo.execution={self.identity}"
        )
        if result.returncode:
            raise ToolError("SANDBOX_CLEANUP_FAILED", "Cannot enumerate owned containers")
        for container in result.stdout.split():
            if not re.fullmatch(r"[0-9a-f]+", container):
                raise ToolError("SANDBOX_CLEANUP_FAILED", "Unexpected container identity")
            removed = await docker("rm", "--force", container)
            if removed.returncode and "No such container" not in removed.stderr:
                raise ToolError("SANDBOX_CLEANUP_FAILED", "Owned container still exists")
