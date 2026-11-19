# 0013 — Durable timing with optional standard span export

M9 adds the open-source `opentelemetry-sdk` (locked in uv.lock) because the PRD
requires standard tracing. It does not implement orchestration. No collector or
paid backend is required. SDK provider is local, with no default exporter/global
provider mutation. Tests inject an actual SDK in-memory exporter. Applications can
provide a tracer to `TraceRecorder`; a collector exporter is optional future setup.

TraceRecorder decorates the Recorder port. It correlates all attempts using the
run UUID as a 128-bit trace ID with a stable virtual run parent. Attempt spans own
model/tool spans. Parent run is virtual, not an exported timed operation. Workflow
handoff run IDs connect child traces, rather than pretending separate role runs
are one physical request. Names/IDs/status are logged as JSON, never raw prompts.

Span metadata commits in the same execution event as the observation. Failed DB
recording propagates; SDK exported spans do not prove a durable operation committed.
Cancellation closes interrupted spans as errors. A killed worker lacks end metadata;
inspection exposes incomplete spans rather than inventing success. Recovery attempts
remain in the same trace and old incomplete spans remain incomplete.

Latencies use monotonic elapsed clocks; SDK timestamps use wall-clock nanoseconds.
Total run duration uses persisted database timestamps and includes downtime/retries.
Metrics are derived from stored events, not separate counters that could drift.
Missing token/provider/resource data is unknown, not zero or fabricated estimates.
Old pre-M9 runs have events but no retrospectively invented spans.

Source: https://opentelemetry.io/docs/languages/python/instrumentation/
Alternatives: raw logs alone lose durable diagnostic structure; Jaeger as a mandatory
service adds unnecessary resource use. A separate span database would duplicate
already transactional events. Paginated event reads bound DB batches; response size
is still proportional to one bounded run, not the entire run collection.
