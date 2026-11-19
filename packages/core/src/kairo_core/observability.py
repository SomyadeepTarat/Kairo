"""Explicit OTel spans plus durable, payload-free correlation/timing metadata."""

import json
import logging
from dataclasses import dataclass, replace
from time import monotonic_ns, time_ns
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from kairo_core.persistence.repository import RunRepository

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import NonRecordingSpan, Span, SpanContext, StatusCode, TraceFlags, Tracer

from kairo_core.events import Recorder, RuntimeEvent

# No exporter, collector, network, or global provider mutation is required.
PROVIDER = TracerProvider()
LOGGER = logging.getLogger("kairo.execution")


@dataclass
class ActiveSpan:
    span: Span
    name: str
    started_ns: int
    clock_ns: int
    parent_id: str

    def metadata(self, *, end: bool = False, failed: bool = False) -> dict[str, object]:
        context = self.span.get_span_context()
        result: dict[str, object] = {
            "name": self.name,
            "trace_id": f"{context.trace_id:032x}",
            "span_id": f"{context.span_id:016x}",
            "parent_span_id": self.parent_id,
            "started_ns": self.started_ns,
        }
        if end:
            ended = time_ns()
            result.update(
                ended_ns=ended,
                duration_seconds=(monotonic_ns() - self.clock_ns) / 1e9,
                status="ERROR" if failed else "OK",
            )
            self.span.set_status(StatusCode.ERROR if failed else StatusCode.OK)
            self.span.end(end_time=ended)
        return result


class TraceRecorder:
    """Recorder decorator; durable event metadata is authoritative, exporters optional."""

    def __init__(self, delegate: Recorder | None, tracer: Tracer | None = None) -> None:
        self.delegate = delegate
        self.tracer = tracer or PROVIDER.get_tracer("kairo.runtime")
        self.root: ActiveSpan | None = None
        self.active: dict[str, ActiveSpan] = {}
        self.first = True

    def begin(self, name: str, parent: Span, **attributes: str) -> ActiveSpan:
        started = time_ns()
        span = self.tracer.start_span(
            name,
            context=trace.set_span_in_context(parent),
            attributes=attributes,
            start_time=started,
            record_exception=False,
            set_status_on_exception=False,
        )
        return ActiveSpan(
            span, name, started, monotonic_ns(), f"{parent.get_span_context().span_id:016x}"
        )

    async def start(
        self, run_id: UUID, attempt_id: UUID, task: str, config_json: str, model_name: str
    ) -> None:
        if self.delegate is not None:
            await self.delegate.start(run_id, attempt_id, task, config_json, model_name)
        # Stable virtual run parent correlates attempts across process restarts.
        parent = NonRecordingSpan(
            SpanContext(
                run_id.int,
                (run_id.int & ((1 << 64) - 1)) or 1,
                False,
                TraceFlags(TraceFlags.SAMPLED),
            )
        )
        self.root = self.begin(
            "attempt", parent, run_id=str(run_id), attempt_id=str(attempt_id), adapter=model_name
        )

    async def record(self, event: RuntimeEvent) -> None:
        assert self.root is not None
        payload = json.loads(event.payload_json)
        root_context = self.root.span.get_span_context()
        correlation: dict[str, object] = {
            "trace_id": f"{root_context.trace_id:032x}",
            "attempt_span_id": f"{root_context.span_id:016x}",
        }
        if self.first:
            correlation["attempt_started"] = self.root.metadata()
            self.first = False
        key: str | None = None
        opening = event.kind in {"model_request", "tool_started"}
        if event.kind in {"model_request", "model_response", "model_failed"}:
            key = "model"
        elif event.kind in {"tool_started", "tool_finished"}:
            key = "tool:" + str(payload["id"])
        if key is not None:
            if opening:
                self.active[key] = self.begin(
                    key.split(":")[0],
                    self.root.span,
                    run_id=str(event.run_id),
                    attempt_id=str(event.attempt_id),
                )
                correlation["span_started"] = self.active[key].metadata()
            elif key in self.active:
                failed = event.kind == "model_failed" or (
                    event.kind == "tool_finished" and payload.get("status") != "COMPLETED"
                )
                correlation["span_finished"] = self.active.pop(key).metadata(
                    end=True, failed=failed
                )
        terminal = event.kind == "state_transition" and payload.get("target") in {
            "COMPLETED",
            "FAILED",
            "CANCELLED",
        }
        if terminal:
            correlation["interrupted_spans"] = [
                s.metadata(end=True, failed=True) for s in self.active.values()
            ]
            self.active.clear()
            correlation["attempt_finished"] = self.root.metadata(
                end=True, failed=payload["target"] != "COMPLETED"
            )
        if self.delegate is not None:
            await self.delegate.record(
                replace(event, payload_json=json.dumps({**payload, "telemetry": correlation}))
            )
        LOGGER.info(
            json.dumps(
                {
                    "event": event.kind,
                    "run_id": str(event.run_id),
                    "attempt_id": str(event.attempt_id),
                    **correlation,
                }
            )
        )

    def close(self) -> None:
        for span in self.active.values():
            span.metadata(end=True, failed=True)
        self.active.clear()
        if self.root is not None and self.root.span.is_recording():
            self.root.metadata(end=True, failed=True)


async def inspect_trace(repository: "RunRepository", run_id: UUID) -> dict[str, object] | None:
    """Reconstruct measured spans/metrics from durable events, including unfinished work."""
    run = await repository.get_run(run_id)
    if run is None:
        return None
    spans: dict[str, dict[str, object]] = {}
    model_calls = tool_calls = failed_tools = retries = 0
    context_peak = 0
    failures: list[dict[str, object]] = []
    after = 0
    while True:
        events = await repository.events(run_id, after=after, limit=1000)
        if not events:
            break
        for event in events:
            after = int(str(event["sequence_number"]))
            payload = event["payload"]
            assert isinstance(payload, dict)
            telemetry = payload.get("telemetry", {})
            if isinstance(telemetry, dict):
                for key in ("attempt_started", "span_started", "span_finished", "attempt_finished"):
                    span = telemetry.get(key)
                    if isinstance(span, dict):
                        spans[str(span["span_id"])] = span
                interrupted = telemetry.get("interrupted_spans", [])
                if isinstance(interrupted, list):
                    for span in interrupted:
                        if isinstance(span, dict):
                            spans[str(span["span_id"])] = span
            kind = event["event_type"]
            model_calls += kind == "model_request"
            tool_calls += kind == "tool_requested"
            retries += kind == "attempt_recovered"
            if kind == "tool_finished" and payload.get("status") != "COMPLETED":
                failed_tools += 1
                failures.append(
                    {
                        "sequence": after,
                        "kind": kind,
                        "code": payload.get("error_code"),
                        "invocation_id": payload.get("id"),
                    }
                )
            if kind in {"model_failed", "recovery_blocked"}:
                failures.append(
                    {
                        "sequence": after,
                        "kind": kind,
                        "code": payload.get("code", payload.get("reason")),
                    }
                )
            if kind == "context_assembled":
                context_peak = max(context_peak, int(str(payload["supplied_bytes"])))
        if len(events) < 1000:
            break
    incomplete = [s for s in spans.values() if "ended_ns" not in s]
    # Incomplete spans are historical observations, never synthetic successful endings.
    metrics: dict[str, object] = {
        "model_calls": model_calls,
        "tool_calls": tool_calls,
        "failed_tool_calls": failed_tools,
        "retries": retries,
        "peak_context_bytes": context_peak,
        "token_usage": None,
    }
    from datetime import datetime

    started, completed = run["started_at"], run["completed_at"]
    metrics["duration_seconds"] = (
        (completed - started).total_seconds()
        if isinstance(started, datetime) and isinstance(completed, datetime)
        else None
    )
    return {
        "run_id": str(run_id),
        "trace_id": run_id.hex,
        "status": run["status"],
        "error": run["error"],
        "metrics": metrics,
        "spans": list(spans.values()),
        "incomplete_span_count": len(incomplete),
        "failures": failures,
        "virtual_run_parent": True,
    }
