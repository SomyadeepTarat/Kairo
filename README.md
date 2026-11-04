# Kairo

A local-first agent execution harness built for engineering understanding and
reliable, inspectable execution. The authoritative specification is [prd.md](prd.md).

**Current scope: M1 single-agent execution kernel.** The bounded async loop runs
with a deterministic scripted model. There is no live inference, tool execution,
API, database integration or frontend. M2 requires an explicit request.

## Start here

1. [Architecture and contracts](docs/architecture/overview.md)
2. [Initial state machine](docs/architecture/state-machine.md)
3. [M1 implementation, validation and checklist](docs/milestones/M1.md)
4. [M1 concepts and review exercises](docs/learning/m1.md)
5. [Architecture decisions](docs/decisions/0001-foundation-boundaries.md)

## Local setup

From this checkout (all other documentation uses repository-relative paths):

```sh
cd /Users/somyadeeptarat/Desktop/Kairo
python3 --version
uv --version
git --version
uv sync --locked
uv run --locked python scripts/doctor.py
uv run --locked python scripts/check.py
```

Use Python 3.13.x and uv. This host already has both. `uv sync --locked` creates
`/Users/somyadeeptarat/Desktop/Kairo/.venv` and installs the core package plus development tools;
it needs network access on first installation, not a paid service. Subsequent
checks can run offline once the locked packages are installed. uv may download
Python if 3.13 is not installed; use `uv sync --locked --no-python-downloads` to
require an existing interpreter instead.

Individual checks:

```sh
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked mypy
uv run --locked pytest
```

`/Users/somyadeeptarat/Desktop/Kairo/scripts/doctor.py` reports required Python,
Git and uv readiness, plus optional CLI presence. It does not check service health.
Docker, PostgreSQL, Node and Ollama are not required for M1. Do not pull models,
create containers, or install a frontend for this milestone. Optional manual
service diagnostics, when those services are deliberately started later:

```sh
docker info
ollama list
```

There is no `.env.example` yet because no implemented component reads configuration
from environment variables. Do not commit secrets or local `.env` files.

## Scripted kernel demonstration

```sh
uv run --locked python scripts/demo_kernel.py
```

This executes a three-response script and reports its real kernel outcome. It
performs no inference, tools or external work. Tests also cover failure, limits
and cancellation. Run `uv run --locked pytest tests/core -q` for core tests only.
See [the kernel decision](docs/decisions/0005-single-agent-kernel.md) for contracts,
alternatives and cooperative cancellation limits. In-memory records do not survive
process termination. M0 history remains in [its record](docs/milestones/M0.md).

## Contribution discipline

This is a solo project, with Codex assisting as an engineering mentor. Define module
contracts before implementation, work in small sequential steps, review each change,
and run the checks before integration. The updated workflow is recorded in
[ADR 0004](docs/decisions/0004-solo-development.md). Follow [AGENTS.md](AGENTS.md). Preserve `prd.md` as the product
authority; record refinements and unresolved decisions in the architecture notes.
