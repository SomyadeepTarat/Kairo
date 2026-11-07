"""Validated kernel continuation state; no persistence or automatic side effects."""

from typing import Literal, Self

from pydantic import Field, model_validator

from kairo_core.models import Message
from kairo_core.tools.registry import Schema


class KernelSnapshot(Schema):
    version: Literal[1] = 1
    messages: tuple[Message, ...] = Field(min_length=2)
    next_step: int = Field(ge=1)
    remaining_seconds: float = Field(ge=0, allow_inf_nan=False)
    final_output: str | None = None

    @model_validator(mode="after")
    def valid_context(self) -> Self:
        if self.messages[0].role != "system" or self.messages[1].role != "user":
            raise ValueError("Checkpoint context must begin with system/user messages")
        if self.final_output is not None and not self.final_output.strip():
            raise ValueError("Recorded final output must be nonempty")
        return self
