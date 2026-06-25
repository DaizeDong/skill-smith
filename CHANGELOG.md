# Changelog

All notable changes to this project are documented here (Keep a Changelog style).

## [0.1.0] - 2026-06-25
### Added
- Initial framework release.
- Thin `skills/skill-smith/SKILL.md` orchestrator: research-first create workflow (Phase 0 delegates
  landscape + frontier-design recon to `market-intel`) through scaffold, trigger-optimize, acceptance
  gate, self-evolve handoff, batch, and deploy.
- `PHILOSOPHY.md` with 6 principles (research-first; generation != usable; thin delegation;
  library-budget is the batch constraint; focused beats exhaustive; dogfood).
- Reference shards: `research-first.md`, `scaffold.md`, `triggering.md`, `acceptance-gate.md`,
  `generators.md`, `iterate-handoff.md`, `deploy.md`, `batch.md`.
- Scripts: `scaffold_skill.py` (Spec-v1 repo generator), `check_conformance.py` (Spec-v1 linter),
  `budget_check.py` (library system-prompt token budget), `dedup_check.py` (cross-library description
  overlap).
- Skill Repo Spec v1 conformance for this repo (dogfood).
- A-tier pytest suite (`tests/`) verifying the create pipeline + each tool; scripts hardened for
  UTF-8 BOM tolerance and empty-name input (found via a self-evolve iteration).
- `trim_descriptions.py` — library description-budget remediation (scan -> review -> apply, with
  per-file backups and a dry-run), the concrete fix for an over-budget skill set (Gate G3).
