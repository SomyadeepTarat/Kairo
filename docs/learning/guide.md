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
PostgreSQL will be the durable truth for inspection. Next.js, Ollama integration,
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
