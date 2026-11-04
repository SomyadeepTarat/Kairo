# Kairo development instructions

Repository root: `/Users/somyadeeptarat/Desktop/Kairo`.

- Read `prd.md` completely before architectural work. It is authoritative.
- Current milestone: M0. Do not implement M1 or beyond until explicitly requested.
- Explain concepts, alternatives, exact files and tests before implementing.
- Keep local ARM64 development free of mandatory paid APIs/cloud services.
- Implement fundamental orchestration ourselves; add dependencies with justification.
- Do not scaffold empty future modules or successful placeholder endpoints.
- Maintain `docs/architecture/`, `docs/decisions/`, `docs/learning/` and the active
  record in `docs/milestones/` as relevant to a change.
- Tests must validate actual behavior; label mocks and avoid model-dependent unit tests.
- Run `uv run --locked python scripts/check.py`. State what actually passed and
  what could not run. Do not infer working services from installed CLIs.
- Both developers must understand contracts; do not mark human review complete
  on their behalf. Keep milestone gates explicit.
- Use exact repository-relative paths in implementation instructions, and absolute
  links in chat when referencing local files.
- Never overwrite user changes or commit/push without a request.
