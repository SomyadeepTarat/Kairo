"""Typed tool registration, validation and auditable invocation outcomes."""

import asyncio
import json
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class SideEffect(StrEnum):
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    EXTERNAL = "external"


class ToolStatus(StrEnum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"


class CommandResult(Schema):
    stdout: str = Field(max_length=1_048_576)
    stderr: str = Field(max_length=1_048_576)
    returncode: int


class CommandExecutor(Protocol):
    async def execute(self, argv: tuple[str, ...], workspace: Path) -> CommandResult:
        """Execute without a shell, bound output, and stop/reap processes on cancellation."""
        ...


@dataclass(frozen=True)
class ToolContext:
    workspace: Path
    permissions: frozenset[str] = frozenset({"workspace.read"})
    command_executor: CommandExecutor | None = None

    def __post_init__(self) -> None:
        if not self.workspace.is_dir() or self.workspace.is_symlink():
            raise ValueError("workspace must be an existing nonsymlink directory")


class ToolError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ToolExecution:
    id: UUID
    name: str
    input_json: str
    output_json: str | None
    status: ToolStatus
    side_effect: SideEffect
    error_code: str | None
    started_at: datetime
    completed_at: datetime
    outcome_uncertain: bool = False


@dataclass(frozen=True)
class Tool[I: BaseModel, O: BaseModel]:
    name: str
    description: str
    input_schema: type[I]
    output_schema: type[O]
    handler: Callable[[I, ToolContext], Awaitable[O]]
    permission: str
    side_effect: SideEffect = SideEffect.READ_ONLY
    timeout_seconds: float = 10.0


@dataclass(frozen=True)
class _Binding:
    descriptor: str
    permission: str
    side_effect: SideEffect
    timeout: float
    validate: Callable[[str], BaseModel]
    execute: Callable[[BaseModel, ToolContext], Awaitable[str]]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, _Binding] = {}

    def register[I: BaseModel, O: BaseModel](self, tool: Tool[I, O]) -> None:
        if not tool.name or tool.name in self._tools:
            raise ValueError("Tool names must be nonempty and unique")
        if not math.isfinite(tool.timeout_seconds) or tool.timeout_seconds <= 0:
            raise ValueError("Tool timeout must be finite and positive")

        async def execute(value: BaseModel, context: ToolContext) -> str:
            validated = tool.input_schema.model_validate(value)
            output = await tool.handler(validated, context)
            # Revalidate even if a badly implemented handler violates its annotation.
            result = tool.output_schema.model_validate(output)
            return result.model_dump_json()

        self._tools[tool.name] = _Binding(
            json.dumps(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema.model_json_schema(),
                    "output_schema": tool.output_schema.model_json_schema(),
                    "permission": tool.permission,
                    "side_effect": tool.side_effect,
                    "timeout_seconds": tool.timeout_seconds,
                },
                sort_keys=True,
            ),
            tool.permission,
            tool.side_effect,
            tool.timeout_seconds,
            tool.input_schema.model_validate_json,
            execute,
        )

    def side_effect(self, name: str) -> SideEffect:
        binding = self._tools.get(name)
        return binding.side_effect if binding else SideEffect.READ_ONLY

    def schemas_json(self) -> str:
        return "[" + ",".join(binding.descriptor for binding in self._tools.values()) + "]"

    async def invoke(
        self,
        name: str,
        arguments_json: str,
        context: ToolContext,
        *,
        invocation_id: UUID | None = None,
    ) -> ToolExecution:
        """Always return a record, including cancellation after handler cleanup.

        Cancellation is a recorded tool outcome; the enclosing runtime still
        propagates caller cancellation after joining this task.
        """
        started = datetime.now(UTC)
        binding = self._tools.get(name)
        effect = binding.side_effect if binding else SideEffect.READ_ONLY
        status = ToolStatus.FAILED
        code: str | None = None
        output: str | None = None
        invoked = False
        try:
            if binding is None:
                raise ToolError("UNKNOWN_TOOL", "Tool is not registered")
            value = binding.validate(arguments_json)
            if binding.permission not in context.permissions:
                raise ToolError("PERMISSION_DENIED", "Required permission is absent")
            async with asyncio.timeout(binding.timeout):
                invoked = True
                output = await binding.execute(value, context)
            status = ToolStatus.COMPLETED
        except ValidationError:
            code = "INVALID_INPUT" if not invoked else "INVALID_OUTPUT"
        except ToolError as exc:
            code = exc.code
        except TimeoutError:
            status, code = ToolStatus.TIMED_OUT, "TOOL_TIMEOUT"
        except asyncio.CancelledError:
            status, code = ToolStatus.CANCELLED, "TOOL_CANCELLED"
        except Exception:
            code = "TOOL_ERROR"
        return ToolExecution(
            invocation_id if invocation_id is not None else uuid4(),
            name,
            arguments_json,
            output,
            status,
            effect,
            code,
            started,
            datetime.now(UTC),
            invoked and status is not ToolStatus.COMPLETED and effect is not SideEffect.READ_ONLY,
        )
