# Security boundaries and known failure modes

Kairo 0.1.0 is for one trusted local developer. There is no multi-user authentication,
Internet-facing tenant isolation, adversarial-kernel defense or external exactly-once
guarantee. Bind API/web/DB to loopback. Host/Origin checks reduce browser drive-by and
rebinding exposure; they do not protect against malicious local processes or replace
authentication. Unauthenticated local approval endpoints assume the local operator.

Exposed file tools reject traversal, protected files, symlinks and unsafe hardlinks.
Commands require exact argv grants, no shell fallback, one workspace bind, no network,
readonly container root, nonroot UID, dropped capabilities, no Docker socket/secrets,
and CPU/memory/PID/output/time limits. A container is not a complete security guarantee.
Generated code runs inside that sandbox, including independent acceptance oracles.

An approval is bound to exact action/invocation/run/attempt and live lease, consumed
once, and cannot expand a permission or command grant. UI defaults approval on; legacy
explicit scripts can opt out. The demonstration's explicit operator policy is limited
to calculator.py writes and the fixed test command, and is labelled as automated policy.

Interrupted mutations with unknown outcomes BLOCK instead of blindly retrying. Operator
reconciliation is a trusted assertion of evidence; Kairo cannot prove it independently.
Physical workspace locks apply to cooperating processes on one host/shared root.
Checkpoints reference a workspace, not a filesystem rollback/snapshot. Lost or externally
modified files can prevent safe continuation. Confirmed operation history is not erased.

Known-pattern redaction is not comprehensive secret detection. Do not put credentials
in tasks, tool outputs or source fixtures. Durable prompts/results may contain local
code. No cloud model provider exists; Ollama is loopback-only, ignores proxies/redirects,
and never auto-pulls models. Cancelling client I/O may not immediately stop inference.
Provider byte/context accounting is not an exact tokenizer; token usage is recorded only
when reported and cannot account for lost responses. Extractive context compaction is
lossy and does not guarantee retention of important facts.

Worker/controller/evaluator failures retain history. A hard-killed evaluator may remain
RUNNING with partial results; inspect it and start a fresh identity rather than replaying
unknown effects. A failed workflow can leave independently queued siblings to finish.
Coordinator progress requires ticks/embedded mode. Bounded collections show a page,
not every historical row. Rendered SSE history is capped at 1,000 events; use paginated
API inspection for complete records. SDK spans are observations, not proof of committed
side effects. Old incomplete attempt spans remain incomplete after successful recovery.

Small local models can loop, emit malformed outputs, hit provider sampler errors, or
claim completion without making a correct change. Independent file/test oracles are
required. The successful coding example is application-orchestrated and covers five
cases in one small app; it is not evidence of general autonomous coding reliability.
Baseline timings have uncontrolled cache/thermal/background-load effects and tiny samples.
