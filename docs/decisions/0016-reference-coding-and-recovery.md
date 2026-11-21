# 0016 — Real coding task with independent oracles and controlled failure

M12 supplies a small executable invoice calculator and unchanged unittest acceptance
conditions under `examples/coding-agent/reference_app/`. The intentionally wrong
subtotal multiplier makes discounts increase the price. The task describes expected
behavior and asks the local model to inspect, reproduce, propose, modify, test and
review. The live adapter is Ollama; the separate scripted mode is an explicitly
prescribed infrastructure fixture, never described as autonomous reasoning.

JobSpec initial_files is a bounded caller-supplied fixture (20 files, 64 KiB).
Worker file validation rejects traversal, symlinks and protected paths. Preparation
is idempotent only before the first RUNNING; recovery after that never resets agent
changes. Optional isolated Git initialization/baseline commit uses fixed bootstrap
commands inside Docker, not the host repository. No agent gets arbitrary Git commit,
network, host mount or shell permissions from this bootstrap.

Approval stays in the M11 backend. The default demo waits for manual dashboard
approval. The explicit `--approve-demo-actions` flag is a narrow operator policy
for this isolated demo: writes only to calculator.py and only the exact unittest
argv. It is not a model approval, test-edit permission, or global gate disable.

An independent sandbox oracle verifies baseline failure and final success, unchanged
tests and a nonempty diff. A model's final claim alone is insufficient. The report
includes actual tool records, events, approvals, attempts, traces and diff. It is a
small reference task, not evidence of general autonomous software engineering ability.

Optional SIGKILL fault uses a dedicated targeted worker subprocess. The API stays
inspection-only during this driver-owned experiment to avoid competing consumers.
Once a confirmed result exists, the driver stops granting new actions and waits for
unresolved dispatched mutations to settle, then kills only its owned process. It
expires that run's lease using database time, reaps owned containers, and resumes
through the production recovery path. Unknown effects still block; the driver does
not reconcile them by assumption. The initial overly broad fault boundary produced
an actual BLOCKED uncertain-effect run, retained as failure evidence.

Alternative: a scripted patch pretending to be inference or a fake crash event would
not demonstrate autonomy/recovery. Running generated code on the host would bypass
the execution boundary. Full repository merge orchestration is unnecessary for this
single isolated reference app. Tests remain deterministic; actual local inference
is measured separately. No new dependency.

Measured free-form runs explained the bug but did not repair it, despite successful
runtime completion/recovery. Their independent oracles failed. The final reference
therefore uses `coding_model.CodingWorkflowModel`: deterministic read/test/diff
operations, real model-generated proposal/source/review, at most three repair rounds.
The report explicitly labels application-orchestrated live Ollama. This is a coding
application on Kairo, not a claim that arbitrary open-ended agents reliably self-plan.
The source repair is never supplied in the live branch. Oracle checks are unchanged.

A live patch also exposed fragile double JSON encoding of multiline code. Ollama now
returns an arguments object and the adapter serializes it once into the unchanged
internal ToolRequest.arguments_json contract. A regression checks quoted multiline
source roundtrips. Prior internal tool messages are translated into the same provider
object form. Registry validation/approvals remain after the provider boundary.
