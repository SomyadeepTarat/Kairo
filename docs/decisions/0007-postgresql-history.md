# ADR 0007: Incremental PostgreSQL history with atomic lifecycle updates

Date: 2026-11-05. Scope: M3; authorized after the M2 commit a291bfe.

## Decision and boundaries

The runtime awaits the Recorder port in `packages/core/src/kairo_core/events.py`.
Its default remains in-memory execution without a recorder. The PostgreSQL adapter
is `packages/core/src/kairo_core/persistence/repository.py`. With it supplied,
execution identities and CREATED are committed before execution, model requests
before model calls, and tool dispatch before potential side effects. Final state
and output/error are saved with the terminal transition. Storage errors propagate;
no success is fabricated and no automatic retry repeats uncertain actions.

Use PostgreSQL with SQLAlchemy's async session/transaction machinery and psycopg.
SQLAlchemy's asyncio extra supplies its required greenlet bridge. Native async DB
I/O prevents blocking the event loop on ordinary database requests. Alembic owns
schema changes through a reviewed explicit migration, not ORM create_all on startup.
The server has finite connection timeouts; cooperative runtime deadlines do not
constitute a hard wall-time guarantee for database commits or cleanup.

## Data and consistency

Tasks retain the description and configuration. Runs retain lifecycle, current
attempt, model adapter metadata, output/error and timestamps. Attempts distinguish
one execution incarnation. Events have per-run sequence numbers, typed names,
payloads and UTC timestamps. Tool records retain requested input, outcome, side
effect class and completion certainty. No checkpoint, worker or approval tables are
created before their functionality exists.

Each append transaction locks its run row with SELECT FOR UPDATE. It checks run/
attempt identity and terminal immutability, validates lifecycle transitions, updates
the snapshot, increments sequence and inserts the event in one transaction. A
unique (run_id, sequence_number) constraint protects ordering. Timestamps alone
cannot establish order. This is snapshot plus ordered history, not a complete
event-sourcing/replay framework or a worker-leasing protocol.

Run and attempt rows have a circular identity reference; a deferred foreign key
allows creating both in one transaction while retaining referential integrity at
commit. Runtime state changes only after the recording call returns. A failed
commit stops further execution and leaves the last known committed history.
The database and filesystem are not in one transaction. In-flight mutating tools
are conservatively marked uncertain before dispatch; a known completed outcome
clears that uncertainty. tool_started means dispatch has begun, including validation,
not proof the handler was authorized or that an external command began.

Interrupted runs retain their last known status and unfinished calls. They are not
automatically failed, resumed or retried: safe recovery is M6. Losing an
acknowledgment cannot prove an operation did nothing.

## API and redaction

FastAPI's factory at `apps/api/src/kairo_api/main.py` provides only real read-only
inspection: paginated runs, a run, ordered events, and tools. Unknown IDs return
404; invalid pagination/UUIDs return 422; storage outages return 503 without DB
exception details. No placeholder submission/resume/approval endpoints exist.
Bind to loopback for trusted local use; authentication/public deployment is absent.

Known sensitive structured keys and common credential patterns are redacted before
storing descriptions, configuration, events or tool payloads. Nested JSON strings
are inspected too. This is not general secret detection; arbitrary prose and files
can still contain sensitive data. Use dedicated workspaces and never expose this
local database/API publicly. Redaction deliberately prevents exact reproduction of
secret-bearing inputs; identifiers and nonsecret structure remain inspectable.

## Alternatives and tests

Saving a final JSON blob is simpler but loses interrupted progress. SQLite cannot
validate PostgreSQL locking or JSONB semantics. Raw SQL everywhere is transparent
but adds mapping/transaction boilerplate; SQLAlchemy is used without hiding the
locking query. Redis or a hosted event store creates unnecessary infrastructure.

Integration tests migrate unique PostgreSQL schemas, verify rollback with an
injected database trigger, serialize concurrent appends, recreate the API, and
kill an executing process after a real partial write. Tests never silently replace
PostgreSQL with SQLite. An explicit --require-postgres option rejects a missing test
URL. No study gate or additional learning checklist is introduced.
