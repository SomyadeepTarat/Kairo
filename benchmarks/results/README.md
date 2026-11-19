# M10 measured baseline observations

All final comparisons use the same source fingerprint, suite, environment and two repetitions.
These are small laptop observations, not statistically established performance rankings.

## Deterministic infrastructure (real operations, prescribed model responses)

| Condition | Scenario assertions | Task completions | Interrupted tasks completed |
|---|---:|---:|---:|
| baseline | 20/20 | 14/14 | 2/2 |
| compact | 20/20 | 14/14 | 2/2 |
| multi | 20/20 | 14/14 | 2/2 |
| no_recovery | 20/20 | 12/14 | 0/2 |

Every scenario assertion passed, including denial/timeouts and the expected no-recovery failure.
The task-completion metric intentionally differs from scenario correctness.
Confirmed append stayed single in both recovery conditions. No permission bypass was observed
in the fixed permission case. Scripted context stress measures budgeting, not semantic recall.
Timing means/sample deviations and per-case evidence are in [infrastructure-baselines.json](infrastructure-baselines.json).

## Live Ollama behavior (two tasks, two repetitions)

| Condition (mode affects file task only) | Successful task outcomes | File task | Coding task |
|---|---:|---:|---:|
| qwen_single | 2/4 | 0/2 | 2/2 |
| qwen_multi | 2/4 | 0/2 | 2/2 |
| vabwee_single | 0/4 | 0/2 | 0/2 |

Only installed local models were used; no model downloads or paid provider calls occurred.
The file oracle requires exactly `benchmark artifact`. In single mode Qwen wrote
`benchmark`, so those cases failed despite final completion text. In multi mode its
planner exhausted the four-call allocation before producing a valid plan. The coding
case stays single-agent in both mode settings, serving as an unchanged control.
Coding results come from
actual independent sandbox assertions. Inspect run IDs, reported token counts, oracle
return codes and model digests in [ollama-baselines.json](ollama-baselines.json).
The second local model failed on its second structured request with HTTPStatusError.
A no-tool replay of the recorded request reproduced HTTP 400 with
`Failed to initialize samplers: std::exception`. This is a provider/sampler failure,
not evidence of general task inability. A simple request separately returned HTTP 200.
See [provider-diagnostic.json](provider-diagnostic.json) for the labelled diagnostic. No latency advantage is claimed from n=2.

## Failures preserved for learning

[preliminary-ollama.json](preliminary-ollama.json) retains the first live run, including failure.
[diagnostic-failures.json](diagnostic-failures.json) retains the pre-fix clock-expiry errors.
Its old denominator excluded infrastructure errors; its summary is deliberately omitted.
The clock-skew and error-denominator regressions now pass in the full deterministic gate.
A separate 100-scenario diagnostic stress run passed, but did not expose the clock skew;
the forced-skew regression was necessary. Historical fingerprints differ and are not compared.

## Reproduce

Use the commands in [the study guide](../../docs/learning/m7-m10.md).
Fresh evaluation UUIDs/workspaces are expected. Keep tasks, limits, seed, repetitions,
source, service versions and image stable. The comparison command rejects mismatches.
Thermal state, model caches and background processes remain uncontrolled confounders.
These JSON files are portable snapshots; database/workspace UUIDs refer to this local run.
Generated oracle scripts and task containers used actual restricted execution.
