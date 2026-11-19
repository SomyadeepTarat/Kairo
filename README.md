# Kairo

A local-first agent execution harness for learning reliable, inspectable execution.
Product specification: [prd.md](prd.md). No paid API or cloud service is required.

Implemented through **M10**: custom async execution, typed tools, restricted Docker
commands, PostgreSQL history, durable workers/recovery, bounded context views,
planner/executor/reviewer coordination, OpenTelemetry traces, and reproducible local
evaluations. Infrastructure demos/tests use labelled scripted models with real
operations. Optional behavioral evaluations use local Ollama; no model is downloaded
automatically. Dashboard and final demonstration/release work remain later milestones.

Study at your own pace:

- [M0–M3 guide](docs/learning/guide.md)
- [Separate M3–M6 guide](docs/learning/m3-m6.md)
- [Separate M7–M10 guide](docs/learning/m7-m10.md)
- [Architecture](docs/architecture/overview.md), [decisions](docs/decisions/0010-safe-recovery.md),
  and [milestone validation records](docs/milestones/M6.md)

There are no separate study completion checklists or learning gates.

## Local setup

```sh
cd /Users/somyadeeptarat/Desktop/Kairo
uv sync --locked
docker compose -p kairo-m3 -f infrastructure/compose/compose.yaml up -d --wait
docker build -t kairo-sandbox:local -f infrastructure/docker/Dockerfile.sandbox .
export KAIRO_DATABASE_URL='postgresql+psycopg://kairo:kairo_local_only@127.0.0.1:55432/kairo'
uv run --locked alembic upgrade head
```

Use Python 3.13.x, uv and a running Docker-compatible local daemon on macOS ARM64.
Initial free dependency/image downloads need network access. Task containers do not.
`.env.example` documents values; Kairo does not automatically load `.env` files.
These credentials are local-development values. PostgreSQL's named volume retains
records across restarts. Stop the service without removing that volume when you
need to conserve resources.

## Queue a real container/filesystem demonstration

```sh
uv run --locked python scripts/enqueue.py examples/scripted-job.json
uv run --locked python scripts/worker.py --once --root .kairo/workspaces
```

Enqueue prints a run UUID. The prescribed model sequence executes an explicitly
approved container command, reads the resulting file and ends. Inspect the returned
tool outcomes rather than treating the scripted final text as evidence of success.
Managed workspaces are under `.kairo/workspaces/RUN_UUID` and ignored by Git.

For a continuing service with two concurrent slots and automatic stale-lease reaping:

```sh
uv run --locked python scripts/worker.py --capacity 2 --root .kairo/workspaces
```

All local workers must share that root. Ctrl-C requests shutdown and joins cleanup.
`--once` does one claim and does not run the periodic reaper. Workspaces and local
locks prevent overlapping owners; containers have no host home/socket/secret mounts,
no network, a readonly root, nonroot UID and resource/output/time limits.
Exact argv approval is separate from the command permission.

## Inspect and control

```sh
uv run --locked uvicorn kairo_api.main:create_app --factory --host 127.0.0.1 --port 8000
uv run --locked python scripts/demo_history.py --inspect RUN_UUID
```

Replace RUN_UUID with an actual ID. [Local API docs](http://127.0.0.1:8000/docs):

- `GET /api/v1/runs`, run detail, `/events`, `/tools`, `/checkpoints`, and `/queue`.
- `GET /api/v1/workers` and `/api/v1/workers/{worker_id}`.
- `POST /api/v1/runs/{run_id}/cancel` acknowledges cancellation intent.
- `POST /api/v1/runs/{run_id}/reconcile` records an explicit operator resolution.

This is trusted-local control, without public authentication. Keep the binding on
loopback. There are no placeholder submission/provider/approval/resume controls.

Unknown mutations remain BLOCKED until investigated. Only when you can prove one
invocation did not execute may you use:

```sh
uv run --locked python scripts/reconcile.py RUN_UUID TOOL_UUID \
  --not-executed --reason 'Evidence that this invocation never reached its side effect'
```

Alternatively provide `--completed-output` with its known, schema-valid JSON result
and an evidence reason. The decision is recorded and reaping checks ownership again.
Do not use reconciliation merely to force progress. Blocked runs can be cancelled.
The guide explains lost acknowledgments, partial effects and recovery limits.

## Validation

```sh
export KAIRO_TEST_DATABASE_URL="$KAIRO_DATABASE_URL"
export KAIRO_TEST_DOCKER=1
uv run --locked python scripts/check.py
uv run --locked pytest tests/persistence --require-postgres --require-docker -q
```

Tests migrate/drop only their uniquely owned schemas in the dedicated local test DB.
The full suite includes real containers, competing claims, process termination,
checkpoint gaps, no duplicate confirmed writes, reconciliation and bounded retries.
Without service variables, those integration tests explicitly skip; require flags
make missing configuration an error. Doctor checks CLI presence, not service health.

Kernel-only and file-only demos remain `scripts/demo_kernel.py` and
`scripts/demo_tools.py`; `scripts/demo_history.py` records a direct scripted run.

## Scope and contribution

One developer owns the project with Codex as mentor/implementation assistant.
[AGENTS.md](AGENTS.md) records scope. Each new milestone gets relevant tests, notes
and its requested commit. M4: `200ab42`; M5: `b227eec`; M6 adds validated checkpointed recovery and reconciliation.
Stop at M10 unless another milestone is explicitly requested. There is no claim of
exactly-once external effects, hostile-tenant security, distributed-host locking,
complete secret detection or recovery from lost/externally changed workspace data.

M7 context policies are configurable in job JSON using `context_budget_bytes`,
`tool_output_bytes` and `context_strategy` (`recent` or `compact`). These are UTF-8
byte limits, not token counts. Study the implementation in `docs/learning/m7-m10.md`.

M8: after migrating PostgreSQL, run the explicitly scripted role example with
`uv run --locked python scripts/workflow.py run examples/scripted-workflow.json`.
The planner validates a dependency graph; executors use real files; review/handoffs
are durable. API: POST `/api/v1/workflows`, GET `/api/v1/workflows/{id}`, POST
`/api/v1/workflows/{id}/advance`. See ADR 0012 for the fresh-workspace revision policy.

M9: GET `/api/v1/runs/{id}/trace` or run
`uv run --locked python scripts/trace.py RUN_UUID` for measured span timing,
failure codes, retries and unfinished operations. OpenTelemetry SDK instrumentation
runs locally without a collector. Unknown provider token usage remains null.


## Evaluate reproducibly

```sh
uv run --locked python scripts/evaluate.py run --repetitions 2
uv run --locked python scripts/evaluate.py run --strategy compact --repetitions 2
uv run --locked python scripts/evaluate.py compare LEFT_UUID RIGHT_UUID
uv run --locked python scripts/evaluate.py run --ollama qwen3:4b --cases file_task coding
```

The last command requires Ollama running and that model already installed. Other
models can be selected explicitly. Deterministic infrastructure cases and live
behavioral outcomes are labelled separately; assertions inspect real files/tests.
No claim of general model quality follows from this small suite. Use `--mode multi`
or `--no-recovery` for the other comparisons. Changed source/environment/budgets are
rejected as incomparable. Baselines are in `benchmarks/results/` with limitations.

POST `/api/v1/evaluations` queues a configuration; GET collection/detail/`results`
inspects persisted outcomes. Execute an API submission using
`uv run --locked python scripts/evaluate.py execute EVALUATION_UUID`.
A completed evaluation can contain failed cases. Partial results survive interruption;
evaluations are never automatically replayed after an unknown process outcome.
