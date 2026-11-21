# 0017 — Local 0.1.0 release and independent checkout validation

M13 versions backend/frontend 0.1.0 and validates from a fresh staged source snapshot,
new Python environment, clean npm install, new PostgreSQL schema and separate workspace.
Source distribution includes migrations, infrastructure, frontend, manifests, examples,
tests and docs. Wheel contains library/API modules; workflow/benchmark CLI commands
are documented from the source checkout, not falsely advertised as standalone wheel tools.

The shared Python check remains usable alone. KAIRO_CHECK_WEB=1 adds frontend typing,
format check and production build, propagating failures. Browser tests separately use
the real service. This avoids pretending a backend-only check covered the frontend.

A recorded browser walkthrough inspects the actual saved live coding run. It is
labelled persisted-evidence inspection, not video of all real-time model execution.
Raw events/report retain the timing/attempt evidence. Final measured benchmark snapshots
are distinct from historical M10 comparisons. Metrics are engineering observations,
not claims of statistical model superiority or completed human learning.

Release review adds local Host/mutation-Origin checks to reduce drive-by browser and
DNS-rebinding exposure. They do not replace authentication, OS trust or container
hardening. Loopback and trusted-local use remain mandatory assumptions. Seed path
validation rejects malformed file names before claiming work.

The developer chose to keep the repository unlicensed. No LICENSE file, external
publication, registry upload or Git push is part of this release. Further distribution
terms require a separate decision. No dependency is added for release orchestration.
