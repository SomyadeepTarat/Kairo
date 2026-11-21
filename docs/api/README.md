# Local API contract

The running API exposes interactive docs at http://127.0.0.1:8000/docs and OpenAPI at
`/openapi.json`. `openapi.json` in this directory is generated from the actual factory
with `uv run --locked python scripts/export_openapi.py`; it is not a hand-written
collection of promised routes. Engine construction for export does not verify DB health.

Main contracts:

- POST `/api/v1/runs` or `/tasks`: validated JobSpec, returns actual queued run/task IDs.
- GET tasks/runs/detail, tools/events/checkpoints/trace/queue: stored evidence, bounded pages.
- POST run cancel: accepts intent, not a guarantee the operation has already stopped.
- GET run stream: SSE `execution` events with sequence IDs, Last-Event-ID/after replay,
  heartbeat comments and `finished` after terminal backlog is drained.
- GET approvals, POST approval decision: current action/attempt/lease checks, 409 for stale
  or already resolved. Approval does not grant different actions or broader permissions.
- Workflow submission/inspection/advance: validated DAG/template contracts and durable ticks.
- Evaluation submission/inspection/results/comparisons: queued real measurements; embedded
  consumer or CLI executes them. Incomparable/incomplete conditions return 409.
- Models: only installed loopback Ollama models; unavailable is explicit, never a fake list.
- Workers/overview: measured heartbeats and SQL aggregate totals, not invented liveness.

Responses use 422 for invalid input, 404 for missing identities, 409 for stale/conflicting
control operations, and 503 for unavailable SQL storage. Origin/Host checks can reject
untrusted browser requests. This is not an authenticated public API. No generic successful
resume, approval bypass, GitHub publishing or paid provider endpoint is exposed.
