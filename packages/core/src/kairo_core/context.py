"""Deterministic UTF-8 context accounting; these units are bytes, never tokens."""

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Literal

from kairo_core.models import Message


def size(messages: tuple[Message, ...], schemas: str = "[]") -> int:
    return len(json.dumps([asdict(m) for m in messages], ensure_ascii=False).encode()) + len(
        schemas.encode()
    )


class ContextOverflow(ValueError):
    """Pinned instructions and schemas alone exceed the caller's budget."""


@dataclass(frozen=True)
class ContextPolicy:
    budget_bytes: int = 65536
    tool_bytes: int = 8192
    strategy: Literal["recent", "compact"] = "recent"

    def __post_init__(self) -> None:
        if type(self.budget_bytes) is not int or self.budget_bytes < 256:
            raise ValueError("Context budget must be an integer >=256 bytes")
        if type(self.tool_bytes) is not int or self.tool_bytes < 64:
            raise ValueError("Tool limit must be an integer >=64 bytes")
        if self.strategy not in {"recent", "compact"}:
            raise ValueError("Unknown context strategy")


@dataclass(frozen=True)
class ContextView:
    messages: tuple[Message, ...]
    original_bytes: int
    supplied_bytes: int
    omitted_messages: int
    trimmed_tools: int
    history_sha256: str


def prefix(text: str, limit: int) -> str:
    return text.encode()[: max(0, limit)].decode("utf-8", errors="ignore")


def assemble(messages: tuple[Message, ...], schemas: str, policy: ContextPolicy) -> ContextView:
    """Pin system/task, trim tool payloads, then evict oldest complete exchanges.

    Compaction is a labelled extract, not a semantic/model-generated summary.
    The original immutable messages remain the checkpoint/history source.
    """
    if len(messages) < 2 or (messages[0].role, messages[1].role) != ("system", "user"):
        raise ValueError("Context must start with system/task")
    pinned = messages[:2]
    if size(pinned, schemas) > policy.budget_bytes:
        raise ContextOverflow("Pinned system/task and tool schemas exceed context budget")
    trimmed = 0
    groups: list[tuple[Message, ...]] = []
    for message in messages[2:]:
        if message.role == "tool":
            if not groups or groups[-1][-1].role != "assistant":
                raise ValueError("Orphan tool result")
            if len(message.content.encode()) > policy.tool_bytes:
                message = Message(
                    "tool",
                    prefix(message.content, policy.tool_bytes - 32) + "\n[tool output trimmed]",
                )
                trimmed += 1
            groups[-1] += (message,)
        else:
            groups.append((message,))
    removed: list[Message] = []

    def current() -> tuple[Message, ...]:
        return pinned + tuple(m for group in groups for m in group)

    while groups and size(current(), schemas) > policy.budget_bytes:
        removed.extend(groups.pop(0))
    selected = current()
    if removed and policy.strategy == "compact":
        # Fit a bounded extract into the remaining room without evicting newer exchanges.
        extract = "[Earlier context extract; incomplete]\n" + "\n".join(
            f"{m.role}: {prefix(m.content, 160)}" for m in removed
        )
        while extract:
            candidate = pinned + (Message("assistant", extract),) + selected[2:]
            if size(candidate, schemas) <= policy.budget_bytes:
                selected = candidate
                break
            extract = prefix(extract, len(extract.encode()) - 16)
    digest = hashlib.sha256(json.dumps([asdict(m) for m in messages]).encode()).hexdigest()
    return ContextView(
        selected, size(messages, schemas), size(selected, schemas), len(removed), trimmed, digest
    )
