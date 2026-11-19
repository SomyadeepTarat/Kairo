# 0014 — Fixed local evaluations with independently checked outcomes

M10 implements the benchmark engine ourselves. `benchmarks/suite.json` defines ten
fixed scenarios and explicit success conditions. `evaluation.py` executes real file,
container, queue, recovery and workflow operations. Scripted responses test infrastructure;
only selected file/coding tasks use optional live Ollama. Every result labels its
model kind. A passed timeout/permission scenario is not successful agent task completion.

`EvaluationRow` stores the manifest/hash, source fingerprint, config, dependency and
service versions, sandbox image ID, model digest/version when applicable, repetitions,
results and summaries. Per-case commits preserve partial results. Claiming a QUEUED
evaluation is atomic; a second runner is rejected. No automatic benchmark replay:
an interrupted process may have caused effects. Normal cancellation records INTERRUPTED;
a hard-killed evaluator can retain RUNNING with partial results, requiring inspection
and a fresh evaluation identity. This is separate from recoverable agent attempts.

Comparisons require matching suite/source, tasks, repetitions, seed, environment and
budgets. Strategy, mode, recovery and model/backend are explicit varying factors.
Per-case paired timing means/sample standard deviations expose repetitions; n=1 has
unknown spread. Two local repetitions support inspection, not statistical claims of
model superiority. Warm caches, thermal state, background load and nondeterministic
inference can vary despite matching metadata. Do not interpret raw wall time as a
controlled hardware benchmark. A real benchmark runner would isolate these further.

Single task budget is 32 model calls/120 runtime seconds. Multi-agent file tasks split
that allowance across planner (4/30), executor (24/60), reviewer (4/30), with the same
per-role context byte/step limits and no revisions. Orchestration/database overhead is
measured too. Every mode checks the same resulting artifact. Each case uses a fresh
workspace. Fault tests use explicit short timeout/fault overrides, recorded by the
manifest/source version rather than falsely claiming every scenario has identical limits.

Recovery benchmark injects a controlled interruption after a committed real container
append, before the next checkpoint, then explicitly expires that run's lease. It
verifies no duplicate append with/without recovery. This is a deterministic fault
injection, not a substitute for existing killed-process tests. Targeted claims/reaping
prevent benchmark workers from consuming or fencing unrelated jobs.

Ollama is the only live provider. HTTPX is promoted from development to runtime to
provide cancellable/bounded HTTP streams; the stdlib blocking client would leave
requests running in threads after cancellation. The adapter accepts loopback HTTP
only, disables environment proxies/redirects, limits responses to 1 MiB and validates
structured outputs. It does not install/pull models. Provider token counts are stored
only when returned. Cancelling a client request cannot guarantee immediate inference
termination inside Ollama. Num_ctx/num_predict bound inference, but provider framing
and instruction overhead are additional to M7's byte accounting, not exact token limits.

API submits durable evaluations; `scripts/evaluate.py execute UUID` runs a queued
identity. `run` submits/executes, `inspect` retrieves, and `compare` reports. An always-on
evaluation service and dashboard are unnecessary at this milestone. Benchmark execution
requires the source checkout's manifest plus local PostgreSQL/Docker. Arbitrary uploaded
benchmark Python code is never executed. Oracle assertions run in the restricted sandbox.

Sources: https://github.com/ollama/ollama/blob/main/docs/api.md

Post-validation finding: fault injection must use the same database clock as normal
lease management. A forced host-clock-skew regression demonstrates this. Infrastructure
errors on task cases count as failed completions, not missing observations. Raw
exception messages are omitted; safe frame locations support diagnosis. Pre-fix
error-accounting artifacts are historical evidence, not valid comparative summaries.
