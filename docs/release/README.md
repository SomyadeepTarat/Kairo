# Kairo 0.1.0 local engineering release

This release remains **unlicensed**, as explicitly chosen by the developer. It was
not published, uploaded or pushed. Versioned source, local artifacts and measured
validation are the deliverables. Python/API and frontend both identify as 0.1.0.

Read the [installation guide](../installation.md), [API contract](../api/README.md),
[architecture](../architecture/overview.md), [security limits](../security.md) and
[contributor notes](../contributing.md). The consolidated study guide is
[M11–M13](../learning/m11-m13.md); all earlier guides are preserved.

`docs/demo/live-coding.json` is the measured model-generated reference repair and
recovery. `coding-demo.webm` is a recorded dashboard inspection of that persisted
execution, not a replay claiming to show every real-time model interaction. Earlier
failures and their oracle results are retained. Model capability claims must stay
narrow: this was one application-orchestrated repair with five unchanged tests.

Final quality-gate counts, source/wheel checksums, fresh-checkout validation and
benchmark results are recorded in the accompanying artifacts and M13 record after
execution. Engineering metrics are measured observations, not completed human study,
production readiness, general autonomy or statistical performance guarantees.


## Recorded validation

- Combined gate: 255 deterministic Python tests passed without skips, Ruff formatting/
  lint, strict mypy over 83 files, frontend type/format checks and production build.
- Fresh staged source: new Python environment and clean npm install/build; new schema;
  a real approval-gated file write/read and SSE replay; the full 255-test Python gate
  and three Chrome browser tests passed. Only the owned schema was dropped.
- Release benchmarks: two context strategies, two repetitions, ten scenarios each:
  40/40 scenario assertions passed with matching source/environment conditions.
  Decisions were scripted; execution/storage/containers were real. This is not LLM quality.
- Reference coding: qwen3:4b generated one actual patch; five unchanged tests passed
  after baseline failure; one worker kill/recovery. Application-orchestrated, not free-form autonomy.
- Recorded walkthrough: 11.08-second VP9 video, 1440×1000, inspecting persisted evidence.

See [metrics.json](metrics.json), [fresh-checkout.json](fresh-checkout.json),
[benchmarks.json](benchmarks.json) and [coding evidence](../demo/README.md).
The initial cache miss and inherited worker flag failure are recorded in the study
guide/M13 record; neither was hidden as a successful clean setup.

Local source/wheel filenames and SHA-256 values are recorded in artifacts.json in the
checkout and in the output artifact directory. That checksum sidecar is intentionally
not embedded in its own source archive. No distribution/upload has occurred.
