"""Awaited execution-recording port; no database or HTTP dependencies."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class RuntimeEvent:
    run_id: UUID
    attempt_id: UUID
    kind: str
    payload_json: str
    occurred_at: datetime


class Recorder(Protocol):
    async def start(
        self, run_id: UUID, attempt_id: UUID, task: str, config_json: str, model_name: str
    ) -> None:
        """Persist initial identities and CREATED state before execution starts."""
        ...

    async def record(self, event: RuntimeEvent) -> None:
        """Commit this event or raise. Never silently drop an execution record."""
        ...


def event_now(run_id: UUID, attempt_id: UUID, kind: str, payload_json: str) -> RuntimeEvent:
    return RuntimeEvent(run_id, attempt_id, kind, payload_json, datetime.now(UTC))
