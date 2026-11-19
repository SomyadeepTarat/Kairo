"""Durable, explicitly scripted workload format; not live model inference."""

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
    steps: list[ScriptStep] = Field(min_length=1, max_length=1000)
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
