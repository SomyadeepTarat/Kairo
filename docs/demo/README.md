# Measured coding demonstration

`live-coding.json` is an actual application-orchestrated Ollama run, not a scripted
patch. The harness selects inspection/test/diff operations; local qwen3:4b generated
the proposal, complete repaired source and final review. The selected run is
`03131581-6544-487a-b9cb-aed79eb2a290`.

Observed evidence:

- Baseline independent unittest command exited 1.
- The dedicated worker was killed with SIGKILL and recovered once through leases/checkpoints.
- The model-generated patch changed the discount multiplier from plus to minus.
- Exactly one patch write is recorded. Acceptance tests stayed unchanged.
- Independent final unittest command exited 0; all five cases passed.
- The actual Git diff, tools, approvals, events and trace are in the JSON report.
- Approval decisions used the explicit isolated-demo operator policy, not human review.

`failed-attempts.json` preserves earlier free-form explanations without repairs and
the malformed nested-JSON patch attempt. Their independent oracles failed. A separate
initial fault during a dispatched command correctly became BLOCKED uncertainty;
that run is retained in the local database (`84f19a66-8355-4d56-884c-3493028ec8d6`).
Do not present these failures as successful agent tasks or general model rankings.

This is one small reference application, not proof of arbitrary coding autonomy.
UUIDs/workspace paths refer to the validation machine. Fresh runs create fresh IDs.
See [the study guide](../learning/m11-m13.md) and ADR 0016 for commands and assumptions.


[Recorded dashboard walkthrough](coding-demo.webm) · [Dashboard screenshot](dashboard.png).
This is an inspection of persisted evidence, not a simulated or replayed real-time
agent session. The raw report remains the source for timing and operation details.
