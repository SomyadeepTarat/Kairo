# ADR 0001: Modular application and milestone-sized repository

Date: 2026-11-04. Status: selected M0 baseline; contributor review pending.

Context: two students, local ARM64 hardware, zero additional spend, PRD §§13–17.
We need inspectable execution without maintaining a distributed platform first.

Decision: logical control/execution boundaries in a modular Python application;
introduce packages only when implemented. M0 contains docs and development tooling.
The next milestone may introduce `packages/core/`; no empty future packages now.

Alternatives: microservices permit independent scaling but add network/operational
failure modes. A framework-owned loop accelerates demos but obscures orchestration.
One undifferentiated module is smaller initially but couples transport to runtime.

Consequences: few moving parts and cheap deterministic tests; code review must
protect dependency direction because process isolation does not enforce it.
Revisit process separation at M5, not because of predicted scale.
