# Kairo development instructions

Repository root: `/Users/somyadeeptarat/Desktop/Kairo`.

- Read `prd.md` completely before architectural work. It is authoritative, subject
  to explicit user updates recorded in `docs/decisions/0004-solo-development.md`.
- The project has one developer. Plan sequential work with review checkpoints;
  Codex assists with mentoring, implementation and review.
- Current milestone: M3. M2 was committed as a291bfe before M3 implementation,
  as explicitly requested. Do not implement M4 or later without a new request.
- Keep all M0–M3 study explanations/checkpoints in `docs/learning/guide.md`.
  Do not create separate learning checklists or block implementation on study gates.
- Explain concepts, alternatives, exact files and tests before implementing.
- Keep local ARM64 development free of mandatory paid APIs/cloud services.
- Implement fundamental orchestration ourselves; add dependencies with justification.
- Do not scaffold empty future modules or successful placeholder endpoints.
- Maintain `docs/architecture/`, `docs/decisions/`, `docs/learning/` and the active
  record in `docs/milestones/` as relevant to a change.
- Tests must validate actual behavior; label mocks and avoid model-dependent unit tests.
- Run `uv run --locked python scripts/check.py`. State what actually passed and
  what could not run. Do not infer working services from installed CLIs.
- Explain contracts and limitations candidly; do not claim the developer has
  completed study or understood material on their behalf.
- Use exact repository-relative paths in implementation instructions, and absolute
  links in chat when referencing local files.
- Never overwrite user changes or commit/push without a request.
