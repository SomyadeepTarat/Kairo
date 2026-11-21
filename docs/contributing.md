# Development and contribution notes

The project currently has one developer, with Codex as a mentoring/implementation aid.
Start with `AGENTS.md`, the full `prd.md`, `docs/architecture/overview.md`, and the
relevant decision/study/milestone records. Explicit developer updates override the PRD.
The repository remains unlicensed by developer choice; no external redistribution or
contribution licensing workflow is established by this release.

Work in small reviewed changes. Explain contracts/alternatives and failure tests before
implementation. Keep model-dependent measurements separate from deterministic tests.
No successful placeholder endpoints, fabricated metrics or mock decisions presented as
inference. Runtime terminal states remain immutable. Never weaken uncertainty fencing
or add a mandatory paid service to make a demo appear successful.

Use a `codex/` branch for assisted work when creating a new branch. Run the commands in
`docs/installation.md`, including the optional web gate and actual browser tests when
changing frontend behavior. Tests use real PostgreSQL, not SQLite, for queue/recovery
contracts. Schema changes require Alembic migrations and upgrade/downgrade/drift checks.
Do not overwrite another person's changes, commit or push without a request.

Update architecture/ADRs/milestone evidence and the consolidated learning guide relevant
to the change. Record failing attempts and actual validation limits. Do not mark human
study or understanding complete on the developer's behalf. Use exact repository-relative
paths in instructions. The runtime/orchestration is intentionally implemented here;
new dependencies need a concrete justification.
