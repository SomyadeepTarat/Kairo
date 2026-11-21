"""Durable, explicitly scripted workload format; not live model inference."""

from pathlib import PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from kairo_core.models import Continue, Final, ModelResponse, ScriptedModel, ToolRequest
from kairo_core.runtime import AgentConfig
from kairo_core.tools.registry import Schema


class ContinueStep(Schema):
    kind: Literal["continue"]
    text: str = Field(min_length=1)

    def response(self) -> ModelResponse:
        return Continue(self.text)


class FinalStep(Schema):
    kind: Literal["final"]
    text: str = Field(min_length=1)

    def response(self) -> ModelResponse:
        return Final(self.text)


class ToolStep(Schema):
    kind: Literal["tool"]
    name: str = Field(min_length=1, max_length=128)
    arguments_json: str = Field(min_length=1)

    def response(self) -> ModelResponse:
        return ToolRequest(self.name, self.arguments_json)


type ScriptStep = Annotated[ContinueStep | FinalStep | ToolStep, Field(discriminator="kind")]


class JobSpec(Schema):
    task: str = Field(min_length=1, max_length=4096)
    steps: list[ScriptStep] = Field(default_factory=list, max_length=1000)
    backend: Literal["scripted", "ollama"] = "scripted"
    workflow: Literal["generic", "coding"] = "generic"
    model: str = Field(default="", max_length=128)
    require_approval: bool = False
    initial_files: dict[str, str] = Field(default_factory=dict, max_length=20)
    initialize_git: bool = False
    permissions: list[Literal["workspace.read", "workspace.write", "command.execute"]] = Field(
        default=["workspace.read", "workspace.write", "command.execute"]
    )
    approved_commands: list[list[str]] = Field(default_factory=list, max_length=100)
    max_attempts: int = Field(default=3, ge=1, le=10)
    max_steps: int = Field(default=16, ge=1, le=1000)
    step_timeout_seconds: float = Field(default=30, gt=0, le=3600, allow_inf_nan=False)
    run_timeout_seconds: float = Field(default=120, gt=0, le=3600, allow_inf_nan=False)
    system_prompt: str = "Complete the task within the supplied execution limits."

    context_budget_bytes: int = Field(default=65536, ge=256, le=1048576)
    tool_output_bytes: int = Field(default=8192, ge=64, le=1048576)
    context_strategy: Literal["recent", "compact"] = "recent"

    def config(self) -> AgentConfig:
        return AgentConfig(
            self.max_steps,
            self.step_timeout_seconds,
            self.run_timeout_seconds,
            self.system_prompt,
            self.context_budget_bytes,
            self.tool_output_bytes,
            self.context_strategy,
        )

    def build_model(self) -> ScriptedModel:
        return ScriptedModel(tuple(step.response() for step in self.steps))

    @model_validator(mode="after")
    def valid_kernel_inputs(self) -> Self:
        self.config()
        if sum(len(value.encode()) for value in self.initial_files.values()) > 65536:
            raise ValueError("Initial files exceed 64 KiB")
        for name in self.initial_files:
            path = PurePosixPath(name)
            if (
                not name
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in name
                or any(p == ".git" or p.startswith(".env") for p in path.parts)
            ):
                raise ValueError("Unsafe initial file path")
        if self.backend == "scripted" and not self.steps:
            raise ValueError("Scripted jobs require explicit responses")
        if self.backend == "ollama" and not self.model.strip():
            raise ValueError("Select an installed local model")
        for step in self.steps:
            step.response()
        for command in self.approved_commands:
            if (
                not command
                or len(command) > 64
                or any(not arg or "\x00" in arg or len(arg) > 4096 for arg in command)
            ):
                raise ValueError("Invalid approved command argv")
        return self
