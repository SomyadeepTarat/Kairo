# Kairo development instructions

Repository root: `/Users/somyadeeptarat/Desktop/Kairo`.

- Read `prd.md` completely before architectural work. It is authoritative, subject
  to explicit user updates recorded in `docs/decisions/0004-solo-development.md`.
- The project has one developer. Plan sequential work with review checkpoints;
  Codex assists with mentoring, implementation and review.
- M7–M10 are authorized, sequentially, with a commit after each validated milestone.
  Stop after M10; M11 and later require a new request.
- Consolidate M7–M10 study in `docs/learning/m7-m10.md`.
- Preserve M0–M3 study in `docs/learning/guide.md`; consolidate the new M3–M6
  material in `docs/learning/m3-m6.md`.
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
