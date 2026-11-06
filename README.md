# Kairo

A local-first agent execution harness built for engineering understanding and
reliable, inspectable execution. Product specification: [prd.md](prd.md).

Implemented through **M3**: a custom async kernel, typed workspace tools,
PostgreSQL execution history, migrations and a read-only inspection API. Demos
use a scripted model with real file operations and database records. Live Ollama
inference, isolated command execution, workers, recovery and the dashboard are
future milestones. No paid API or cloud service is required.

All study explanations and checkpoints are in one [engineering guide](docs/learning/guide.md).
There are no separate learning completion checklists. Architecture and validation
history remain in [architecture notes](docs/architecture/overview.md),
[ADRs](docs/decisions/0007-postgresql-history.md), and [milestone records](docs/milestones/M3.md).

## Python setup and local tools

```sh
cd /Users/somyadeeptarat/Desktop/Kairo
uv sync --locked
uv run --locked python scripts/doctor.py
uv run --locked python scripts/check.py
uv run --locked python scripts/demo_tools.py
```

Use Python 3.13.x and uv. Setup installs the core/API packages and locked dependencies
in `.venv`. The first install may need free downloads; cached dependencies can be
used offline. Doctor checks CLI presence, not running service health. Without a
test database URL, PostgreSQL integration tests are explicitly reported as skipped.
The file-tool demo uses a disposable directory and performs no inference.

## PostgreSQL and persisted demo

Start/unpause the existing Docker-compatible runtime, then:

```sh
docker compose -p kairo-m3 -f infrastructure/compose/compose.yaml up -d --wait
export KAIRO_DATABASE_URL='postgresql+psycopg://kairo:kairo_local_only@127.0.0.1:55432/kairo'
uv run --locked alembic upgrade head
uv run --locked python scripts/demo_history.py
```

The demo prints a run UUID. Read it back in a separate process:

```sh
uv run --locked python scripts/demo_history.py --inspect RUN_UUID
```

Replace RUN_UUID with the actual printed value. `.env.example` documents configuration;
Kairo does not automatically load `.env` files. These credentials are for the local
loopback development database. Keep secrets and `.env` files out of Git.
The Compose volume preserves data when the API or container stops. Use
`docker compose -p kairo-m3 -f infrastructure/compose/compose.yaml stop` to stop the
service while retaining data. Do not remove its volume if you need the records.

## Inspection API

```sh
uv run --locked uvicorn kairo_api.main:create_app --factory --host 127.0.0.1 --port 8000
```

Open [API documentation](http://127.0.0.1:8000/docs). Implemented routes:

- `GET /api/v1/runs?limit=100&offset=0`
- `GET /api/v1/runs/{run_id}`
- `GET /api/v1/runs/{run_id}/events?after=0&limit=100`
- `GET /api/v1/runs/{run_id}/tools?limit=100&offset=0`

This is a trusted-local read-only API; there are no placeholder submission/resume
routes. Incomplete runs retain their last known state and uncertain effects,
without automatic recovery or retries.

## Full validation, including PostgreSQL

```sh
export KAIRO_TEST_DATABASE_URL="$KAIRO_DATABASE_URL"
uv run --locked python scripts/check.py
uv run --locked pytest tests/persistence --require-postgres -q
```

Integration tests migrate and remove only their own unique schemas in the selected
test database. Use the dedicated local development database. `--require-postgres`
rejects a missing URL; an unavailable configured server fails the tests.
The suite covers actual commits, rollback, schema drift, API recreation and history
retained after killing an executing process. Unit tests never depend on inference.

## Development discipline

One developer owns the project, with Codex assisting as mentor and implementation
assistant. Work in small changes, explain contracts and test actual behavior.
Follow [AGENTS.md](AGENTS.md). M2 was committed before M3 as `a291bfe`.
Further milestones require an explicit request. Consolidated study is independent
of implementation progress, as requested.
