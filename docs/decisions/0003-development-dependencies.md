# ADR 0003: Development baseline and staged dependencies

Date: 2026-11-04. Status: selected M0 baseline; contributor review pending.

Use Python 3.13.x (the inspected host has 3.13.4), within PRD's 3.11+ requirement.
Keep `.python-version`, `pyproject.toml`, and mypy/Ruff targets aligned. The minor
version is shared; record patch versions when reporting experiments. uv manages the
project virtual environment and exact transitive resolutions in `uv.lock`. The
bootstrap is an existing uv installation, not a runtime dependency. No Python
application package was built during M0 (`tool.uv.package = false` at that time).

| Dependency | Introduce | Reason / alternative / cost |
| --- | --- | --- |
| pytest | M0 dev | Readable failure/parameterized tests; unittest needs no install but less convenient fixtures |
| Ruff | M0 dev | Formatting and lint in one tool; separate Black/Flake8 adds tools |
| mypy | M0 dev | Static interface checks; Pyright is a valid alternative but requires another toolchain here |
| asyncio, dataclasses, typing | M1 stdlib | Implement bounded I/O orchestration ourselves; avoid agent frameworks |
| pytest-asyncio | M1 dev | Explicit asynchronous tests once async runtime exists |
| Pydantic | M1 if configuration validation needs it | PRD stack; avoid duplicating domain and HTTP schemas without need |
| FastAPI, HTTPX | API milestone / first real model HTTP adapter | Validated HTTP boundary and transport tests; not runtime orchestration |
| PostgreSQL, SQLAlchemy, Alembic, psycopg | M3 | Durable transactions, mappings, migrations, async-capable driver; raw SQL remains appropriate for locking |
| Docker/Compose | M3 environment; M4 sandbox | Repeatable DB and restricted process environments; native DB is simpler but less reproducible |
| Ollama | First explicitly requested live-inference integration | Native local inference; model choice depends on measured RAM/latency, not M0 guesses |
| Next.js, React, TypeScript, Tailwind, Playwright | M11 | Real dashboard, types, styling and browser checks; no frontend scaffolding now |
| OpenTelemetry; optional Jaeger | M9 | Correlated tracing once basic execution records exist |

Do not add Redis, vector databases, agent frameworks, paid APIs, or cloud services.
SSE is the PRD default for later one-way event delivery; POST commands carry user
actions. Reconsider WebSockets only if bidirectional streaming is required.

Using installed Python avoids an unnecessary interpreter download. Exact tool
versions are resolved in `uv.lock`; broad manifest ranges are not the reproducible
installation source. Upgrade deliberately and rerun checks. Docker-compatible
local runtimes are acceptable; no mandatory paid license or new purchase is assumed.
Node version selection is deferred until the frontend milestone.

## M1 update — 2026-11-05

ADR 0005 records the implemented choices. The root distribution now installs the
core source using setuptools 80.9.0 (pinned build dependency only). No runtime
libraries were added. Frozen dataclasses with explicit validation suffice for the
local contract, so Pydantic is deferred. Async tests currently use asyncio.run;
pytest-asyncio is deferred until async fixtures/composition justify its addition.
The earlier table's M1 pytest-asyncio entry was an expectation, not a requirement
to add unused tooling. FastAPI, PostgreSQL and all other service dependencies
remain deferred to their actual implementation milestones.
