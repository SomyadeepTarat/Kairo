# Kairo engineering guide — M0 through M3

This is the single study document for the work authorized through M3. Read it at
your own pace; it does not gate implementation. Paths are exact repository-relative
paths under `/Users/somyadeeptarat/Desktop/Kairo`. Commands run from that directory.
Architecture decisions and milestone records separately retain design/validation
history; they are not additional learning assignments.

## 1. What Kairo does and what it does not

Kairo is infrastructure around an agent, not a model or a framework-generated
chatbot. A model proposes a final answer or tool request. Deterministic software
owns lifecycle, validates requests, enforces permissions and records outcomes.
The distinction matters because fluent model text cannot prove a file changed or
that a command succeeded. Actual handler results and automated assertions provide
that evidence. Current demos use ScriptedModel, not Ollama inference.

The control plane accepts configuration and exposes execution records. The
execution plane runs the loop and tools. These are logical boundaries within a
small Python application; separate microservices would add network failures,
deployment work and resource costs without improving the initial kernel.
PostgreSQL is the durable truth for recorded execution inspection. Next.js, Ollama integration,
container execution and workers remain separate future work.

The root `pyproject.toml` defines one installable distribution whose code lives in
`packages/core/src/kairo_core/`. A monorepo is a repository organization, not a
requirement to give each directory a separate deployment or version number.
`uv.lock` fixes dependency resolution; `.python-version` fixes the Python minor.
Setuptools builds the package, Ruff checks style, mypy checks type contracts, and
pytest checks behavior. None alone proves the others' guarantees.

Study checkpoint: explain why a successful mock run is evidence of runtime behavior
but says nothing about model competence, Docker health, or PostgreSQL durability.

## 2. Read the lifecycle and model contract

Start at `packages/core/src/kairo_core/state.py`. RunStatus contains the nine PRD
states. TRANSITIONS is a read-only mapping of allowed edges; `transition` rejects
anything else. All 81 source/target pairs are checked against the specification in
`tests/core/test_state.py`. A state machine prevents contradictory lifecycle
changes; it does not itself prevent two workers or save state across restarts.

CREATED → QUEUED → RUNNING represents local dispatch. QUEUED is not evidence of a
durable scheduler. Continue adds another message while remaining RUNNING; it does
not create an illegal RUNNING → RUNNING transition. Tool calls enter
WAITING_FOR_TOOL, then return to RUNNING after a known outcome. A final answer can
complete only from RUNNING. Terminal runs have no outgoing edges. Every invocation
of run_agent creates a fresh run and attempt rather than editing a terminal result.
PAUSED and WAITING_FOR_APPROVAL are specified but not implemented capabilities.

Next read `packages/core/src/kairo_core/models.py`. A Protocol defines the
operations the runtime needs, without requiring inheritance from a provider SDK.
`Model.generate(ModelRequest)` returns Continue, Final or ToolRequest. This is
dependency inversion: the runtime defines its needs, and an adapter implements
them. A future Ollama adapter must translate its actual transport/schema; it will
not magically speak our internal dataclasses.

Frozen dataclasses and immutable message tuples keep earlier requests from changing
when the runtime appends context. ScriptedModel chooses a prescribed output using
the one-based request step, not a shared mutable cursor. The same task/config/script
therefore reproduces model requests and responses across runs, while UUIDs differ.
Continue is a kernel exercise mechanism, not proof of hidden reasoning or tool use.
ToolRequest contains a name and JSON arguments, not executable Python.

Study checkpoint: trace the difference between a task (requested work), a run
(lifecycle), and an attempt (one execution incarnation). Why is restarting a failed
command more subtle than creating a fresh UUID?

## 3. Async execution, limits and cancellation

Read `packages/core/src/kairo_core/runtime.py` from AgentConfig through run_agent.
Config rejects nonpositive limits, bool-as-int step counts and NaN/infinite time
budgets. Calls are sequential within a run, but independent runs may overlap I/O.
The defaults are 16 model calls, a 30-second step budget and a 120-second total
budget. A final answer on the last allowed call succeeds; another requested call
beyond the limit fails. A tool is part of its initiating step's time budget.

An async function call creates a coroutine. A Task schedules it cooperatively.
Awaiting I/O lets other tasks make progress; synchronous filesystem work or
`time.sleep` still blocks the event loop. Async is not automatic CPU parallelism.

`_await_operation` races work against an event and a time budget. It cancels and
awaits unfinished children in a finally block. Cancellation without joining can
leave cleanup pending, so a returned CANCELLED result must follow cleanup.
An asyncio.Event cancellation returns a result. Cancelling the caller's Task
propagates CancelledError after child cleanup. An adapter cancelling itself is a
failure. If event cancellation and a final response are ready together,
cancellation wins. Tests control these races with Events rather than random sleeps.

A monotonic clock measures elapsed time without wall-clock jumps. The run has an
absolute deadline; every step gets the smaller of its step budget and remaining
run time. Late responses are rejected. Asyncio cannot forcibly stop an adapter
that blocks or suppresses cancellation; cleanup can exceed the requested timeout.
Repeated cancellation during cleanup and hostile code are not hard-isolated here.

RunResult records output/failure, configuration, IDs, requests and transitions.
Failure codes distinguish limits, deadlines, model errors and uncertain tool
outcomes. Exception class names are retained without arbitrary potentially secret
exception text. A bound on steps is not a token/byte context budget; M7 is later.

Study checkpoint: follow `tests/core/test_runtime.py` and predict what event
cancellation, caller cancellation, an invalid response and script exhaustion each
return or raise. Explain why per-step timeouts alone cannot bound a whole run.

## 4. Tool schemas, permissions and outcomes

Read `packages/core/src/kairo_core/tools/registry.py`. Tool binds a name,
description, input/output schemas, async handler, permission, side-effect class
and timeout. Registration rejects duplicate names. The registry advertises JSON
schemas to the model, but schemas are descriptions, not authorization.

Pydantic is introduced at this boundary because model arguments are JSON. Strict
models reject coercion and unknown fields: a numeric path is not silently converted
to text, and unexpected options are not ignored. Inputs are validated before the
handler runs. Outputs are validated too, because a buggy trusted handler can break
its own annotation. Python static types help authors; runtime validation protects
an external data boundary. Pydantic does not decide whether an action is permitted.

ToolContext supplies an existing workspace, explicit capability names and an
optional command executor. A valid write request still needs `workspace.write`.
The registry returns a ToolExecution for success, validation failures, missing
permissions, unknown tools, errors, cancellation and timeout. Outcomes include an
ID, timestamps, side-effect class and whether completion is uncertain.

Known read-only failures can be returned to the model for another permitted
strategy. A mutating operation that fails after invocation may have partly
succeeded, so it is conservatively marked uncertain and the runtime stops. This
is not automatic rollback or exactly-once execution. Denied actions never invoke
the handler. A broad permission is not a human approval system; approvals are later.

`run_agent` supplies schemas, handles a ToolRequest, records its outcome, appends
assistant/tool messages and continues. Without a registry it fails explicitly.
There is no implicit tool execution or model-generated Python evaluation.

Study checkpoint: trace malformed JSON, a missing capability and a partially
completed write. Why must those produce different records and retry decisions?

## 5. Filesystem boundaries and command interfaces

Read `packages/core/src/kairo_core/tools/files.py`. Paths are workspace-relative;
absolute paths, parent traversal, symlinks and protected `.git`/`.env` paths are
rejected. Traversal opens directory descriptors with O_NOFOLLOW and uses dir_fd for
each component. This avoids the classic check-then-open symlink replacement gap of
merely checking Path.resolve and later opening the original string. Descriptors
are closed in finally blocks. Writes reject hardlinks before truncating so an
outside file sharing an inode cannot be overwritten through that link.

Only bounded regular UTF-8 files are accepted. Reads/writes are capped at 1 MiB;
listing at 1000 scanned entries; literal search covers immediate directory files
with a 4 MiB content budget. Directories and binary/oversized files are not text
search candidates. No recursive search or regex engine is implied. Filesystem
calls are synchronous and size-bounded, not forcibly preemptible.

These tools protect ordinary exposed paths in a trusted local environment; they
are not protection against another hostile process replacing mounts or directory
ownership. They also cannot make arbitrary local files safe to disclose. Use a
dedicated workspace. M4 adds isolated execution; no complete security claim exists.

`packages/core/src/kairo_core/tools/commands.py` defines explicit argv commands and
fixed Git inspections through CommandExecutor. No shell string is evaluated and no
host executor is installed by default. A missing executor produces
EXECUTOR_UNAVAILABLE. The future executor must bound output and stop/reap its
processes on cancellation. M2 tests inject a labeled test double to prove routing,
not pretend that a sandbox already exists.

Run `uv run --locked python scripts/demo_tools.py`. The model is prescribed, but
file operations are real, in a disposable directory. Compare its outputs with
`tests/tools/test_tools.py`, including denied permissions and symlink/hardlink tests.

Study checkpoint: explain why O_NOFOLLOW, regular-file checks, output bounds,
permission checks and containers address different failure modes. Why doesn't
having valid JSON make a command safe?

## 6. Reading and validating changes yourself

Run `uv run --locked python scripts/check.py`. It stops on format, lint, type or
test failure. Read the actual failing assertion before changing implementation.
Deterministic tests prove controlled infrastructure behavior, not general agent
quality. Model-dependent evaluations and later browser tests answer other questions.

For each component, be able to explain its purpose, behavior without it,
alternatives, assumptions, failure detection, recovery limits, tests and cost.
This is a reasoning habit, not another completion checklist. The source and tests
are the authority for implemented behavior; the PRD describes the larger destination.

## 7. Why persistence must happen during execution

Before M3, RunResult existed only in memory. Saving it after completion would
preserve successful runs but lose exactly the executions we most need to debug:
ones that terminate midway. Read `packages/core/src/kairo_core/events.py`, then
follow each awaited emit in `packages/core/src/kairo_core/runtime.py`.

Recorder is another dependency-inversion boundary. It exposes start and record,
without importing SQLAlchemy into the kernel. No recorder means in-memory use;
RunRepository supplies durable use. A recording error propagates and prevents
further work. A background fire-and-forget logging task would be faster sometimes,
but could drop records on exit or acknowledge work that was never recorded.

The ordering is deliberate:

```text
create task/run/attempt and run_created event
  -> commit QUEUED, then RUNNING transitions
  -> commit model_request
  -> await the model
  -> commit model_response
  -> commit WAITING_FOR_TOOL and tool_requested
  -> commit tool_started dispatch record
  -> invoke validated tool
  -> commit tool_finished
  -> commit RUNNING, then request the next model response
  -> commit terminal state together with final output/error
```

The registry may deny a dispatched request, so tool_started is not proof a shell
command or authorized handler began. It means the invocation boundary was entered.
The returned tool_finished record establishes validation failures or known results.
The same invocation UUID links the request, dispatch, final record and tool table.

If execution dies before a final response, committed history remains inspectable.
A tool whose dispatch was recorded but completion was not can be uncertain. M3
keeps that fact instead of declaring failure or automatically repeating the action.
A worker lease/recovery protocol belongs to M5/M6, not a flag in this repository.

Study checkpoint: find the exact awaits that occur before model/tool work. What
would change if model_request or tool_started were recorded after the operation?
What can an inspector safely conclude from STARTED without tool_finished?

## 8. Understand the PostgreSQL tables and transaction boundary

Read `packages/core/src/kairo_core/persistence/tables.py` and the matching migration
at `migrations/versions/0001_execution_history.py`.

| Table | Question it answers | Important relationship |
| --- | --- | --- |
| tasks | What work and configuration were requested? | One task can conceptually have multiple runs; M3 creates a task with each run |
| runs | What is the current execution status and result? | References task and current attempt |
| run_attempts | Which execution incarnation produced these records? | Belongs to one run; worker/recovery behavior is not implemented |
| execution_events | What happened, in what durable order? | Run, attempt, unique per-run sequence |
| tool_executions | What was requested and what outcome is known? | Invocation identity, run/attempt, side effect and uncertainty |

UUIDs identify entities without requiring a database round trip first. Foreign keys
prevent dangling identities at commit. Runs reference their current attempt while
attempts reference their run: the named deferred foreign key allows both to be
created in one transaction and checks integrity when that transaction commits.
This avoids creating a temporarily committed run with no attempt.

JSONB holds structured configuration/events that need to remain inspectable as the
runtime evolves. It is not a substitute for relational identity and uniqueness
constraints. Tool input/output JSON is stored as text because invalid input is
still an important record, and must not fail JSONB parsing merely for being invalid.
Wall timestamps use UTC-aware values. Sequence numbers provide order; timestamps
can collide or come from different clocks.

In `packages/core/src/kairo_core/persistence/repository.py`, read start, then record.
Each method uses a session transaction. SQLAlchemy maps objects to rows and manages
unit-of-work flushing; it does not eliminate the need to reason about SQL behavior.
Psycopg is the actual PostgreSQL driver. SQLAlchemy's asyncio extra includes its
required greenlet bridge; our runtime/database calls are still explicitly async.

Record selects the run FOR UPDATE, serializing writers for that run. It checks
current attempt and expected source state, validates the transition, updates the
run/attempt snapshot, increments sequence, and inserts the event. The transaction
commits all of that together. If event insertion fails, status and sequence must
roll back too. The unique (run_id, sequence_number) constraint is a second line of
defense. The lock does not implement worker ownership or scheduling.

An index on run creation/id helps run-list ordering. The event uniqueness index
supports per-run sequence lookup; tool records have a run/start/id index. Each
event incurs a transaction; this favors clear durable boundaries over throughput.
No performance claim exists until measured. Do not add batching or a second queue
just because the architecture could eventually need them.

A database transaction cannot roll back a filesystem write. If a write succeeds
and tool_finished cannot commit, the database must retain uncertainty. Exactly-once
external side effects cannot be obtained just by wrapping ORM calls in begin().
There are no automatic retry loops in M3.

Study checkpoint: sketch two concurrent event appenders. Why does FOR UPDATE plus
a unique sequence constraint preserve order? Then explain why that same transaction
cannot prove a shell command did or did not run after its acknowledgment was lost.

## 9. Migrations and local configuration

Read `alembic.ini` and `migrations/env.py`. Alembic versions database structure so
another checkout can reproduce it. The migration explicitly creates tables,
constraints and indexes. The ORM does not call create_all at application startup;
that would bypass reviewed migration history and can hide schema drift.

The environment obtains the PostgreSQL URL from KAIRO_DATABASE_URL. It does not
print it or read arbitrary `.env` files. `.env.example` documents local values;
exporting variables is explicit. `infrastructure/compose/compose.yaml` runs a
PostgreSQL service on loopback port 55432 with a named volume. The published
credentials are local-development values, not production secrets. Stop the service
when needed without removing its volume; deleting the volume deletes durable data.

The repository requires PostgreSQL, not a SQLite fallback. Async connections have
a finite connect timeout. A paused Docker VM is an unavailable database even if
Docker's CLI exists. A healthy container is an environment prerequisite, not proof
that migrations or application transactions are correct.

Integration tests create a random schema per test, set the session search_path to
it, apply real migrations, and drop only that owned schema afterward. Alembic's
version table uses the same default schema as reflection. One actual test failure
caught a mismatch there: drift detection mistook the version table for an
application table. Aligning version-table lookup with search_path fixed it.
The roundtrip test also runs Alembic's metadata drift check.

Study checkpoint: distinguish a Python virtual environment, container, named volume,
database, schema, and migration revision. Which of them must survive an API restart?
Why is downgrade testing restricted to a disposable test schema?

## 10. The read-only inspection API

Read `apps/api/src/kairo_api/main.py`. The factory constructs the app and repository;
it does not execute agents, create tables or launch background workers. Lifespan
cleanup disposes the engine. Keeping a factory lets tests instantiate a fresh app
against the same database and lets uvicorn start it after configuration is exported.

| Endpoint | Behavior |
| --- | --- |
| GET /api/v1/runs | Up to 100 runs, newest first; limit and offset pagination |
| GET /api/v1/runs/{run_id} | Persisted state/result, task and configuration |
| GET /api/v1/runs/{run_id}/events | Up to 1000 ordered events; after is an exclusive sequence cursor |
| GET /api/v1/runs/{run_id}/tools | Up to 1000 invocation records, ordered by start/id |

Pydantic response models document and validate the HTTP contract separately from
ORM models. This avoids exposing arbitrary ORM internals as the public schema.
FastAPI validates UUIDs and pagination. Unknown runs return 404, invalid arguments
422, and database failures 503 with a generic message. An empty tool list for a
known run is different from an unknown run. No POST/resume endpoint pretends to
work. The server is trusted-local, without authentication; bind to 127.0.0.1.

Database recording redacts known sensitive keys and common credential patterns,
including nested JSON strings, in
`packages/core/src/kairo_core/persistence/redaction.py`. This is not complete secret
detection. Arbitrary file text can still contain secrets. Use dedicated workspaces
and inspect what you permit to be recorded. Redaction intentionally prevents exact
replay of secret-bearing inputs; it is better to document that than claim exact
reproduction of data we deliberately removed.

Study checkpoint: predict the responses to an unknown UUID, a malformed UUID,
a negative event cursor and a database outage. Why should a read-only inspection
server not launch executions while handling a GET request?

## 11. Reproduce the whole flow

Run these commands from `/Users/somyadeeptarat/Desktop/Kairo`:

```sh
uv sync --locked
docker compose -p kairo-m3 -f infrastructure/compose/compose.yaml up -d --wait
export KAIRO_DATABASE_URL='postgresql+psycopg://kairo:kairo_local_only@127.0.0.1:55432/kairo'
uv run --locked alembic upgrade head
uv run --locked python scripts/demo_history.py
```

The demo's model is scripted, but its file operations and database commits are
real. Its disposable workspace is removed; its execution records remain. Copy the
printed run UUID, then start a separate process:

```sh
uv run --locked python scripts/demo_history.py --inspect RUN_UUID
```

Replace RUN_UUID with the printed UUID. You can also start the API:

```sh
uv run --locked uvicorn kairo_api.main:create_app --factory --host 127.0.0.1 --port 8000
```

In another terminal, request
`http://127.0.0.1:8000/api/v1/runs` or open the generated API docs at
`http://127.0.0.1:8000/docs`. Stop and restart the API; the same run remains because
its truth lives in PostgreSQL, not an in-memory list in the HTTP server.

## 12. Learn from the tests and their limits

```sh
export KAIRO_TEST_DATABASE_URL="$KAIRO_DATABASE_URL"
uv run --locked python scripts/check.py
uv run --locked pytest tests/persistence --require-postgres -q
```

Tests without a database URL explicitly skip the PostgreSQL suite. The
--require-postgres option makes a missing URL an error so a requested integration
run cannot silently become a green set of skips. A configured but unavailable
server fails tests; it is never replaced with SQLite.

Read `tests/test_recording.py`: a controlled storage failure before tool dispatch
prevents the file side effect; API outage handling avoids exposing connection
exception details. Those are labeled doubles, not claims of database durability.

Then read the actual PostgreSQL tests:

- `tests/persistence/test_repository.py` writes/reads files while persisting history,
  recreates the repository, injects an event-insert failure through a database
  trigger to verify atomic rollback, checks terminal/stale-attempt rejection,
  concurrent event ordering, redaction and durable caller cancellation.
- `tests/persistence/test_migrations.py` downgrades/upgrades a disposable schema and
  compares the resulting schema with ORM metadata.
- `tests/persistence/test_api.py` inspects real stored rows through newly created API
  instances and checks pagination, validation, 404s and absent mutation endpoints.
- `tests/persistence/test_interruption.py` launches a real child execution, lets a
  controlled tool write a file and block, kills that process, and inspects committed
  history through a fresh repository. The unfinished write stays STARTED/uncertain.

The interruption test proves retained history, not safe recovery. A database outage
or crash can leave completion uncertain. M4 isolation, M5 ownership/leases and M6
checkpoint reconciliation are still future work. There is no live-model evaluation,
no dashboard and no claim about general coding-agent competence.

Study checkpoint: explain what each test actually proves and propose one failure
that it does not cover. For the killed tool, separate what the filesystem, last
committed event and tool completion fields tell you. This is the most important
reasoning exercise before implementing recovery later.
