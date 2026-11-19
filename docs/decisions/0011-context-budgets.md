# 0011 — Deterministic context views

M7 selects a bounded working view from immutable history at each model request.
The budget counts UTF-8 JSON message bytes plus schema bytes, not model tokens or
provider protocol overhead. Pin system/task; fail explicitly if they cannot fit.
Trim tool results, then drop complete oldest exchanges. `compact` optionally adds
a bounded labelled extract of omitted messages; it is lossy and not a semantic summary.

Alternatives: model summaries add inference latency and nondeterminism; a tokenizer
would tie accounting to a specific model. Both can be added behind this boundary.
No dependency is needed. Real provider adapters must enforce their own token limits.

`context_assembled` records sizes, transformations, history digest and run/step reference.
`model_request.messages` records the actual supplied view; `history_messages` and
checkpoints preserve original context for crash-gap projection. Existing event and
checkpoint APIs provide persistent retrieval, with credential redaction limitations.
These references identify history, not cross-task memory or filesystem snapshots.
