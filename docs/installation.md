# Install and run Kairo 0.1.0 locally

Validated target: macOS ARM64, Python 3.13.x, Node 22+ (the validation host uses
Node 25), uv, npm, Docker Desktop/compatible Docker daemon and Git. Linux-compatible
Python/container components are intended; the complete release was measured on macOS
ARM64. Dependencies/container downloads need internet once; no paid API is required.

From a clone or extracted source archive (replace the path with your checkout):

```sh
cd /Users/somyadeeptarat/Desktop/Kairo
uv sync --locked
npm --prefix apps/web ci
docker compose -p kairo-m3 -f infrastructure/compose/compose.yaml up -d --wait
docker build -t kairo-sandbox:local -f infrastructure/docker/Dockerfile.sandbox .
export KAIRO_DATABASE_URL='postgresql+psycopg://kairo:kairo_local_only@127.0.0.1:55432/kairo'
export NEXT_TELEMETRY_DISABLED=1
uv run --locked alembic upgrade head
uv run --locked python scripts/serve.py
```

In another terminal:

```sh
npm --prefix apps/web run dev
```

Open http://127.0.0.1:3000. The API and worker are at loopback port 8000; web is port
3000. The Next proxy is deliberately local. The app does not automatically read `.env`;
export values yourself. `.env.example` is a reference. The PostgreSQL credentials above
are development-only. Compose binds the DB to loopback port 55432 and retains its volume.

Start with a scripted infrastructure example in Tasks. This performs actual writes/
reads with clearly prescribed model decisions. Approve its exact write in Approvals,
then inspect tools/checkpoints/trace. No model is required for this path.

For real inference, start your existing Ollama server and use `ollama list` to choose
an installed model. Kairo never downloads a model. Select that model in the UI.
Performance/task success depend on the model and laptop. The source release's live
reference used qwen3:4b; its failure cases are preserved too.

For the driver-owned coding demonstration, stop embedded worker mode and restart:

```sh
KAIRO_EMBEDDED_WORKER=0 uv run --locked python scripts/serve.py
# Another terminal with the same KAIRO_DATABASE_URL:
uv run --locked python scripts/demo_coding.py --approve-demo-actions
```

Without that flag, approve actions manually in the dashboard. The flag grants only
calculator.py writes and the fixed test command for the isolated demonstration.
Do not run competing workers for this driver-owned crash test. Reports live under
`.kairo/coding-reports/` and workspaces under `.kairo/workspaces/`. A measured example
and recorded evidence inspection are under `docs/demo/`.

## Checks

```sh
export KAIRO_TEST_DATABASE_URL="$KAIRO_DATABASE_URL"
export KAIRO_TEST_DOCKER=1
export KAIRO_CHECK_WEB=1
uv run --locked python scripts/check.py
npm --prefix apps/web test
```

The browser tests need a real running API/worker (`scripts/serve.py` with embedded
worker enabled). They use installed Chrome by default. A free Playwright Chromium
can be installed with `npx --prefix apps/web playwright install chromium`; choose
KAIRO_BROWSER_CHANNEL=chromium when using it. Integration tests create and drop only
their uniquely owned schemas. Missing service flags cause explicit skips; use pytest
`--require-postgres --require-docker` if absence must be an error. The full recorded
release gate enables both services and reports actual skips.

## Shutdown and troubleshooting

Ctrl-C the API and web processes. Active work is cancelled/joined; terminal runs
are not resumable. PostgreSQL data and workspaces remain. Stop Compose with
`docker compose -p kairo-m3 -f infrastructure/compose/compose.yaml stop` when desired;
do not remove its volume unless you intend to erase local execution history.

Connection errors: verify Docker is running/unpaused and Compose reports healthy.
Queued work: check actual worker heartbeat and embedded mode. Approval waits: inspect
exact inputs, deadline and current actionability. BLOCKED uncertainty: investigate;
never assume a lost acknowledgment means an operation did not execute. Model failures:
inspect events and independent task tests; runtime COMPLETED does not prove task success.
SSE reconnects replay ordered history and do not repeat tools.

The wheel contains importable Python modules; examples, migration commands, evaluation
manifests and web setup require this source checkout/archive. Version 0.1.0 has no
license grant and was not uploaded/pushed to a registry or remote repository.
