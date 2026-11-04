# ADR 0005: A provider-independent, cooperative M1 kernel

Date: 2026-11-05. Status: implemented baseline; developer learning review pending.
Scope: M1 only, explicitly authorized by the user's request to continue to the next
milestone. This does not assert completion of the M0 learning exercises.
All paths are relative to `/Users/somyadeeptarat/Desktop/Kairo`.

## Context and decision

We need a real bounded execution loop before tools, providers, storage or services.
Implement one async `run_agent` function in
`packages/core/src/kairo_core/runtime.py`, with per-call private lifecycle state.
Use the shared pure transition policy in `packages/core/src/kairo_core/state.py`.
A frozen result is returned; no API accepts a terminal result as resumable input.
Every invocation gets fresh run/attempt UUIDs. CREATED → QUEUED → RUNNING is local
dispatch, not a claim of durable scheduling.

Use a structural `Model` Protocol and frozen dataclasses in
`packages/core/src/kairo_core/models.py`. The runtime accepts Continue, Final and
ToolRequest responses. Continue adds assistant text and requests another model
step; it is a kernel exercise mechanism, not evidence of hidden reasoning, a tool
result, or a standardized provider response. A future adapter must explicitly map
its provider's outputs; we do not assume Ollama speaks this contract natively.
ToolRequest always fails with UNSUPPORTED_TOOL in M1. No tool registry, argument
schema validation or command execution is implemented.

The ScriptedModel selects output by request step instead of a shared cursor. It is
explicitly a development/test adapter, performs no inference, and can be reused
across runs. Exhausting its script is an error, not fabricated completion.

## Alternatives and tradeoffs

- A framework-owned loop would hide the orchestration we want to learn.
- A synchronous function is simpler but cannot promptly cancel an awaited request.
- A mutable shared runtime object could accidentally leak state between runs.
- Dictionaries and status strings are easy to start with but obscure valid shapes.
  Dataclasses plus explicit validation suffice at this local Python boundary;
  Pydantic remains an option when real JSON/configuration boundaries arrive.
- Pause, approvals and tool waiting exist in the full lifecycle policy, but the
  M1 runtime cannot enter them. A full graph does not implement those capabilities.

## Deadlines and cancellation

Count model invocations, including failed attempts, as steps. A final response on
the last allowed step succeeds. Another requested step after exhaustion fails.
Use a monotonic clock for an absolute run deadline. Each model wait receives the
smaller of remaining run time and per-step time. Recheck elapsed time before
accepting a response so delayed cleanup cannot turn a late answer into success.

Race the model task against an asyncio.Event waiter. On event cancellation,
cancel and await unfinished children before returning CANCELLED. Cancellation wins
if both it and a final response are ready together. A caller's Task.cancel()
propagates CancelledError after cleanup, rather than being swallowed as a result.
An adapter cancelling its own request is instead a MODEL_ERROR.

Adapters must yield to asyncio and cooperate with cancellation. A coroutine that
blocks the event loop or suppresses cancellation can exceed the deadline while
cleanup waits. We choose resource cleanup over pretending such work has stopped.
This is an in-process contract, not a hard isolation guarantee. Repeated external
cancellation during cleanup is also outside the single-cancel guarantee tested here.
Do not spawn untracked background work from an adapter. Process isolation is later.

## Packaging and tests

Keep a single root Python distribution with source under
`packages/core/src/kairo_core/`. Pin setuptools 80.9.0 as a build-only dependency in
`pyproject.toml`; it installs the core without manual sys.path hacks. A workspace
of separately versioned distributions adds no value with one implemented package.
The `py.typed` marker declares that the distributed package includes typing.
No runtime dependencies are added. Build requirements are pinned in pyproject,
whereas uv.lock resolves application/development dependencies.

Async tests use asyncio.run and event-driven test doubles; pytest-asyncio is deferred
until fixtures/async test composition justify it. This changes the earlier M0
expectation, not the selected pytest test runner. Tests exercise all 81 lifecycle
pairs, reproducibility, malformed responses, limits and child-task cleanup.
No network, provider, Docker or PostgreSQL is needed for kernel tests.

## Consequences

Step records and transitions are immutable in-memory evidence only. They are lost
on process termination. Model exception records retain the exception class, not
arbitrary exception text that could contain secrets. No retries occur automatically.
Context has a step bound but not a byte/token budget yet (M7); this is unsuitable for
unbounded model outputs. No throughput, inference-quality or recovery claim follows
from deterministic tests. Both schema evolution and real provider behavior still
require validation at their implementation milestones.
