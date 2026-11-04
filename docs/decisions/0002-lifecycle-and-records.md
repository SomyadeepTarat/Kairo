# ADR 0002: Explicit lifecycle and transactional history

Date: 2026-11-04. Status: design baseline; implementation M1/M3/M6.

Context: ad hoc status assignments allow impossible transitions and obscure crashes.

Decision: one transition policy, terminal runs immutable, separate run attempts,
current state plus ordered execution records. Future database transitions and events
commit together. Side effects outside the database can be uncertain.

Alternatives: status booleans permit contradictory combinations; a full event-sourced
system adds replay/versioning complexity before it is needed; automatic retry of
all failures can duplicate commands whose acknowledgment was lost.

Consequences: explicit tests and useful inspection. Database atomicity cannot make
external commands exactly once. Recovery must reconcile uncertain operations.
Detailed recovery/fencing design is intentionally deferred to M6.
