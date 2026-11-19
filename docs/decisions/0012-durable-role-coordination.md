# 0012 — Durable bounded role coordination

M8 uses the existing queue for all role execution. A PostgreSQL workflow row stores
the typed spec and bounded coordinator state/history. Each short tick locks the row;
child submission and delegation are one transaction. Concurrent/restarted ticks
therefore cannot submit a child twice. No new dependency or framework is needed.

Planner final output is a JSON `Plan` with task keys/dependencies. It must cover
exactly the caller-approved executor templates. Validate unknown dependencies,
duplicates and cycles before execution. Caller templates own tools and approvals;
planner text cannot grant commands. Each child has a distinct run/context/workspace.
Planner and reviewer permissions are empty, enforced by the worker's ToolContext.

Reviewer final output is a JSON `Review` (accepted, feedback). Rejection reruns the
whole approved DAG in fresh workspaces up to max_revisions. Prior artifacts remain
inspectable; no merge/rollback is implied. Successful predecessor output/tool records
are bounded handoff data; reviewer has evidence, not arbitrary shared file access.
Review is an agent judgment, not proof of task correctness. Automated success
conditions belong in evaluations. Any child terminal failure fails the coordinator;
already-submitted siblings remain independent durable jobs and may finish. BLOCKED
children keep the workflow waiting for explicit reconciliation/cancellation.

Alternative: shared mutable workspaces require ownership/merge protocols; in-memory
async gather loses delegation state on crash. Full event-sourced workflow schemas
would add migrations/joins without current need. This JSON state is bounded by at
most 20 tasks and 4 execution rounds. A coordinator needs explicit ticks (API/CLI);
it is not an implicit always-running service. Workspaces share the one-host limits
of M5–M6. There is no distributed exactly-once external side-effect guarantee.
