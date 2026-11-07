# ADR 0010: Checkpointed continuation, bounded retries and explicit uncertainty

Date: 2026-11-07. Scope: M6 after M5 commit b227eec. No M7 context compaction,
multi-agent framework, provider inference or dashboard is introduced.

KernelSnapshot in `packages/core/src/kairo_core/checkpoints.py` versions and validates
messages, next logical step, remaining time and any durably known final response.
The runtime records initial/continuation checkpoints; a tool result's new context
and return to RUNNING share a transaction with its checkpoint. Checkpoints refer to
the persistent managed workspace by run identity. They do not copy/rollback files.
Recovery requires that workspace to remain present and externally unmodified.

The reaper must fence the DB owner, stop its containers and acquire the local
workspace lock before recovery. Recovery locks the job/run, checks cancellation,
unknown mutations, workspace presence, attempt budget and original absolute run
deadline, then validates checkpoint state. Redacted, malformed or unsupported state
blocks recovery; it is never silently used as substituted model input.

A checkpoint alone leaves a tool-finished/checkpoint gap. The recovery projector
reads later committed model requests/responses and tool outcomes to reconstruct the
latest safe context. A confirmed tool outcome is consumed without invoking that
tool again, even if its checkpoint was never saved. A known final response can be
finalized without another model request. Unknown read-only work can be re-requested;
unknown mutations remain BLOCKED. This is not an exactly-once external execution
claim: lost acknowledgments require reconciliation.

Safe recovery ends the old attempt as FAILED/LEASE_EXPIRED and atomically creates
a new attempt on the same nonterminal run. The versioned attempt_recovered event
explains the explicit reset to QUEUED; it is not an ordinary illegal lifecycle edge.
Terminal runs never resume. Attempt count is bounded (default 3, configurable 1–10).
Backoff is 1, 2, 4... seconds capped at 30. Logical step position is preserved;
an unacknowledged model/read request may be repeated, but physical attempts remain
bounded. Total time includes downtime/backoff from the first RUNNING timestamp,
and remaining time cannot increase past the checkpoint's budget.

Explicit operator reconciliation binds to one uncertain invocation in its current
blocked run/attempt. The operator must supply a reason and either proof of no
execution or a known result that validates against that tool's output schema.
The decision and result are recorded, then cleanup/ownership checks run again.
Completed results advance context; proven nonexecution permits retry of that step.
The backend cannot independently prove an operator's assertion. This is trusted-
local intervention, not the later authenticated approval workflow. Cancelling a
blocked run remains possible and preserves the uncertainty record.

Alternatives: replaying from the beginning duplicates effects; checkpoint-only
replay misses committed results between boundaries; automatically retrying all
exceptions mistakes unknown completion for failure; overwriting a terminal run
loses attempt history. Full event sourcing, distributed consensus and filesystem
snapshots add complexity beyond this local scope. A referenced persistent workspace
plus conservative blocking is chosen and its limits are documented.

Migration 0003 adds checkpoint records and recovery fields/state. Real child-process
crashes test both checkpoint windows, unknown effects, reconciliation, limits,
missing/redacted/malformed state, finalization and local lock fencing. These are
infrastructure tests, not live-model evaluations or a hostile-environment guarantee.
