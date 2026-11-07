# ADR 0009: PostgreSQL claims, lease fencing and local workspace ownership

Date: 2026-11-07. Scope: M5, after M4 commit 200ab42. No Redis or framework scheduler.

`packages/core/src/kairo_core/orchestration/queue.py` creates task/run/attempt,
QUEUED transition and job in one transaction. JobSpec is an explicitly scripted,
typed workload format; Worker accepts a replaceable Model factory. It is not a
claim of live inference. Credential-bearing specs recognizable by the redactor are
rejected rather than silently executed with changed/redacted values. This does not
detect every secret in arbitrary prose; dedicated trusted input remains necessary.

Claims lock a worker row to enforce its capacity, then select an available job with
FOR UPDATE SKIP LOCKED. The short transaction assigns a fresh token and lease using
database time. Execution does not hold that transaction open. Available ordering
is best-effort under contention, not strict global FIFO. Worker heartbeat renews
only a still-live token; expired leases cannot renew themselves. Every execution
record verifies token, run/attempt identity and lease in the same transaction as
state/event persistence. The plain M3 recorder cannot bypass fencing for queued runs.

A lease is not physical isolation. Workers also hold a local flock outside the
mounted workspace for their whole execution and cleanup. Reaping first fences the
DB owner, removes that token's containers, then requires the workspace lock before
finalizing abandonment. An alive but paused process retaining the lock delays
reclamation; we prefer safety to concurrent filesystem writers. These workers are
for one local macOS/Linux host with a shared workspace root, not multiple machines.
Lock ordering is worker then job for claims, job then run for execution; heartbeat
updates worker metadata in a separate transaction to avoid reverse-order deadlocks.

Queued cancellation records CANCELLED without dispatch. Active cancellation is a
durable request, polled by heartbeat; the runtime records terminal cancellation
after cleanup. The API returns acceptance, not proof of immediate process stoppage.
M5 fails abandoned executions without automatically repeating actions. M6 owns
retry/checkpoint policy; terminal runs will remain immutable.

Alternatives: an in-memory queue loses work on restart; a held transaction around
execution monopolizes connections/locks; Redis introduces another consistency
boundary without measured need; timestamp-only leases cannot fence stale updates
or safely release a filesystem. The schema adds only actual jobs/workers (migration
0002). CLI enqueue/worker commands and real inspection/cancellation routes expose it.

Source: [PostgreSQL SELECT locking](https://www.postgresql.org/docs/current/sql-select.html).
Correctness is tested with actual competing database transactions and local workers.
