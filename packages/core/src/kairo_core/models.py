"""Immutable model contract and an explicitly scripted, non-inference adapter."""

from dataclasses import dataclass
from typing import Literal, Protocol


def require_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")


@dataclass(frozen=True)
class Message:
    role: Literal["system", "user", "assistant"]
    content: str

    def __post_init__(self) -> None:
        if self.role not in {"system", "user", "assistant"}:
            raise ValueError("Unsupported message role")
        require_text(self.content, "content")


@dataclass(frozen=True)
class ModelRequest:
    messages: tuple[Message, ...]
    step: int  # One-based model-call number within a run.


@dataclass(frozen=True)
class Continue:
    """Another model step is needed; this is not a tool invocation."""

    text: str

    def __post_init__(self) -> None:
        require_text(self.text, "continuation")


@dataclass(frozen=True)
class Final:
    text: str

    def __post_init__(self) -> None:
        require_text(self.text, "final answer")


@dataclass(frozen=True)
class ToolRequest:
    """Recognized but unsupported in M1; argument schemas arrive in M2."""

    name: str
    arguments_json: str

    def __post_init__(self) -> None:
        require_text(self.name, "tool name")
        require_text(self.arguments_json, "tool arguments")


type ModelResponse = Continue | Final | ToolRequest


class Model(Protocol):
    async def generate(self, request: ModelRequest) -> ModelResponse:
        """Return structured output; yield to asyncio and honor task cancellation."""
        ...


class ScriptExhausted(RuntimeError):
    """The development script did not define this model step."""


@dataclass(frozen=True)
class ScriptedModel:
    """Deterministic development/test model. Does not perform inference or tools.

    Lookup by request step, rather than a mutable cursor, makes scripts reusable
    across runs without leaking one run's progress into another.
    """

    responses: tuple[ModelResponse, ...]

    async def generate(self, request: ModelRequest) -> ModelResponse:
        if not 1 <= request.step <= len(self.responses):
            raise ScriptExhausted(f"No scripted response for step {request.step}")
        return self.responses[request.step - 1]
