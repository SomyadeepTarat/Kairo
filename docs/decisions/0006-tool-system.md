# ADR 0006: Typed tools and consolidated study through M3

Date: 2026-11-05. The user authorized M2, an M2 commit, then M3, with all study
material collected in `docs/learning/guide.md`. Separate exercise files and study
completion checklists are removed. This explicitly supersedes earlier study gates;
learning remains the purpose and is not claimed complete by automation.

M2 introduces Pydantic at the JSON boundary, with strict input/output schemas and
forbidden unknown fields. A typed registry checks schemas and capability names,
then invokes a handler within a timeout and records its outcome. Unknown tools,
invalid arguments, missing permissions and handler errors return explicit records.
Handlers cannot be arbitrary Python emitted by a model. Tool results enter the
next request as tool messages. Failed actions do not receive automatic retries.
Uncertain mutating outcomes stop the runtime for reconciliation.

Workspace file handlers use no-follow, descriptor-relative path traversal; reject
absolute paths, parent traversal, symlinks, protected metadata/environment files,
hardlinks and nonregular files. Files are capped at 1 MiB; listing is capped at
1000 entries; search is literal, nonrecursive and has a 4 MiB content budget.
These are trusted-local tool boundaries, not M4 isolation. Local filesystem calls
are synchronous and cannot be forcibly preempted by asyncio.

Commands and Git tools require a supplied CommandExecutor with explicit argv,
bounded outputs and cancellation cleanup. No default host executor exists. M4 will
provide container execution; M2 tests the interface with clearly labeled doubles.
This avoids exposing an unrestricted host shell before isolation exists.

Alternatives: untyped dictionaries miss validation errors; implementing a JSON-schema
engine ourselves distracts from orchestration; delegating to an agent framework
hides the runtime; executing host commands by default violates the intended sandbox
boundary. Pydantic is the PRD's selected validation library and has no service cost.
