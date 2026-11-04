# ADR 0004: Solo development workflow

Date: 2026-11-05. Status: team-size change directed by the user; M0 design review remains pending.

Context: the PRD originally assumes two developers. The user explicitly updated
that constraint: one developer will do all the work. This instruction supersedes
the two-contributor organization in PRD §§14, 15, 18 and associated learning gates.
The product specification otherwise remains authoritative and unchanged.

Decision: one developer owns every component. Replace A/B assignments with small,
sequential implementation tasks and explicit integration checkpoints. Codex remains
an engineering mentor and implementation/review assistant. The developer retains
responsibility for understanding contracts and approving milestone completion.

Alternatives: retaining two-person gates would block progress on an unavailable
contributor. Eliminating review entirely would weaken learning and error detection.
Instead use written explanations, diff review, deterministic tests and Codex-assisted
review. This does not provide an independent human reviewer's perspective.

Consequences: fewer coordination costs but less independent review and less available
development capacity. Keep milestone scope narrow; avoid simultaneous branches unless
needed. Preserve module boundaries and tests even though one person implements both
sides. No M1 or later implementation is authorized by this workflow change.
