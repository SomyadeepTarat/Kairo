"""Pure lifecycle policy; no scheduling, persistence, or mutation lives here."""

from enum import StrEnum
from types import MappingProxyType
from typing import Final


class RunStatus(StrEnum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_FOR_TOOL = "WAITING_FOR_TOOL"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_STATES: Final = frozenset({RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED})
_FAILURE_EXITS = {RunStatus.FAILED, RunStatus.CANCELLED}
TRANSITIONS: Final = MappingProxyType(
    {
        RunStatus.CREATED: frozenset({RunStatus.QUEUED} | _FAILURE_EXITS),
        RunStatus.QUEUED: frozenset({RunStatus.RUNNING} | _FAILURE_EXITS),
        RunStatus.RUNNING: frozenset(
            {
                RunStatus.WAITING_FOR_TOOL,
                RunStatus.WAITING_FOR_APPROVAL,
                RunStatus.PAUSED,
                RunStatus.COMPLETED,
            }
            | _FAILURE_EXITS
        ),
        RunStatus.WAITING_FOR_TOOL: frozenset({RunStatus.RUNNING} | _FAILURE_EXITS),
        RunStatus.WAITING_FOR_APPROVAL: frozenset({RunStatus.RUNNING} | _FAILURE_EXITS),
        RunStatus.PAUSED: frozenset({RunStatus.QUEUED} | _FAILURE_EXITS),
        RunStatus.COMPLETED: frozenset(),
        RunStatus.FAILED: frozenset(),
        RunStatus.CANCELLED: frozenset(),
    }
)


class InvalidTransition(ValueError):
    """A requested lifecycle edge is not in the shared policy."""


def transition(source: RunStatus, target: RunStatus) -> RunStatus:
    """Validate an edge and return its target; invalid edges have no side effects."""
    if not isinstance(source, RunStatus) or not isinstance(target, RunStatus):
        raise InvalidTransition("Lifecycle transitions require RunStatus values")
    if target not in TRANSITIONS[source]:
        raise InvalidTransition(f"Illegal transition: {source} -> {target}")
    return target
