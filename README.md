# Kairo · 0.1.0

A local-first agent execution harness built for engineering study and inspectable,
controlled execution. Python/FastAPI, PostgreSQL, Docker, Ollama and Next.js. No
mandatory paid API or cloud service. Developed by one developer with Codex assistance.

Implemented through M13: explicit async kernel/state machine, typed tools and restricted
workspaces/containers, durable queues/workers, checkpoint recovery and uncertainty
reconciliation, bounded context views, role coordination, OpenTelemetry/durable traces,
fixed evaluations, real dashboard controls and a verified reference coding application.

**Local engineering release; unlicensed by developer choice.** No external publication,
registry upload or Git push is implied. [PRD](prd.md) is authoritative subject to explicit
updates in [decisions](docs/decisions/0004-solo-development.md).

## Run locally

Requirements: Python 3.13.x, uv, Node 22+, npm, Git and running Docker on macOS ARM64.
Initial open-source dependency/image downloads require network access. From the checkout:

```sh
uv sync --locked
npm --prefix apps/web ci
docker compose -p kairo-m3 -f infrastructure/compose/compose.yaml up -d --wait
docker build -t kairo-sandbox:local -f infrastructure/docker/Dockerfile.sandbox .
export KAIRO_DATABASE_URL='postgresql+psycopg://kairo:kairo_local_only@127.0.0.1:55432/kairo'
export NEXT_TELEMETRY_DISABLED=1
uv run --locked alembic upgrade head
uv run --locked python scripts/serve.py
```

In another terminal: `npm --prefix apps/web run dev`. Open http://127.0.0.1:3000.
API docs: http://127.0.0.1:8000/docs. See the full [installation guide](docs/installation.md).
The app reads exported environment variables, not `.env` automatically.

Tasks can use labelled scripted infrastructure decisions or an installed local Ollama
model. No model is downloaded automatically. Approval is enabled by default in the UI
for writes/commands; permissions and exact command grants still apply after approval.
The dashboard shows actual runs, tools, checkpoints, role handoffs, worker heartbeats,
replayable SSE events and evaluation results. Bare uvicorn provides inspection/control;
`scripts/serve.py` also enables the worker/controller/evaluation consumer.

## A real coding example

Use inspection-only API mode so the demonstration owns its targeted worker:

```sh
KAIRO_EMBEDDED_WORKER=0 uv run --locked python scripts/serve.py
# Another terminal, with the same database URL and Ollama running:
uv run --locked python scripts/demo_coding.py --approve-demo-actions
```

The explicit flag grants only isolated calculator.py writes and the fixed test command.
Omit it for manual dashboard approval. The application orchestrates inspection/tests/diff;
Ollama generates proposal, repaired source and review. An actual worker kill/recovery and
independent unchanged tests verify the outcome. `--scripted` is a separate prescribed
infrastructure fixture, not live inference. [Measured evidence](docs/demo/README.md) and
failed attempts are preserved. This is one small app, not proof of general coding autonomy.

## Validate and evaluate

```sh
export KAIRO_TEST_DATABASE_URL="$KAIRO_DATABASE_URL"
export KAIRO_TEST_DOCKER=1
export KAIRO_CHECK_WEB=1
uv run --locked python scripts/check.py
npm --prefix apps/web test
uv run --locked python scripts/evaluate.py run --repetitions 2
```

The full gate includes Python checks/tests and frontend typing/format/build. Browser
tests require the real API/worker and Chrome (or configured free Playwright Chromium).
Service tests use uniquely owned PostgreSQL schemas and actual Docker. Without service
flags they explicitly skip; the release record states what ran. Live inference is a
separate measurement, never a randomized unit-test dependency. Source checkout commands
use versioned migrations, manifests and fixtures included in the source distribution.

Evaluation comparisons enforce recorded conditions. Scenario correctness differs from
task completion. Unknown token/resource data stays unknown. Historical
[M10 observations](benchmarks/results/README.md) and [release evidence](docs/release/README.md)
include failures and sample-size limitations. No fabricated throughput/coverage claims.

## Study and architecture

- [M0–M3 guide](docs/learning/guide.md)
- [M3–M6 guide](docs/learning/m3-m6.md)
- [M7–M10 guide](docs/learning/m7-m10.md)
- [M11–M13 guide](docs/learning/m11-m13.md)
- [Architecture](docs/architecture/overview.md), [state machine](docs/architecture/state-machine.md),
  [API](docs/api/README.md), [milestone records](docs/milestones/M13.md)
- [Security and known failures](docs/security.md), [development notes](docs/contributing.md)

Trusted-local use only. No authentication for public hosting, hostile-tenant sandbox
guarantee, distributed-host lock protocol, complete secret detection, filesystem rollback,
or exactly-once external side-effect guarantee. Unknown mutations block for evidence-based
reconciliation. Never force a resume merely to make a demo finish. Human study is not
marked complete by passing tests. Requested scope ends at M13.
