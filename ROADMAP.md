# Roadmap

Current: **v0.1.1**

## v0.1.1 (current) — config-bearing skills are first-class

- `reference/config-spec.md`: the seven-element standard (E1–E7) for any skill that needs a companion
  config — documented schema, env-var discovery mount, deterministic `init`, a `verify` doctor, two
  configs hot-swappable by env var, secrets gitignored (Mode B), and a README Config section.
- `scaffold_skill.py --with-config` emits the standard; `check_config_conformance.py` is Gate G8
  (auto-detects config-bearing repos, live determinism + hot-swap test). Generalized from
  market-intel's companion-config-spec to be skill-agnostic.

## v0.1.0 — framework

- Thin `SKILL.md` orchestrator with the full create workflow (research-first as Phase 0).
- `PHILOSOPHY.md` (6 principles) + Skill-Repo-Spec-v1 conformance for this repo itself (dogfood).
- Reference shards for every step: research-first, scaffold, triggering, acceptance-gate,
  generators, iterate-handoff, deploy, batch.
- Working scripts: `scaffold_skill.py` (deterministic Spec-v1 repo generator),
  `check_conformance.py` (Spec-v1 linter), `budget_check.py` (library token budget),
  `dedup_check.py` (cross-library description overlap).
- Goal of this version: reliably emit a **spec-conformant skill skeleton** and lint any skill repo.

## Planned

### v0.2 — the acceptance gate goes live
- Wire eval-lift (with-skill vs baseline) via `agent-skills-eval` / scenario-eval.
- Held-out trigger-rate optimization via the official `skill-creator` `run_loop.py` (60/40 split).
- Security audit step for generated scripts. Gate becomes blocking end-to-end.

### v0.3 — self-evolve handoff
- `iterate-handoff` automates pointing `self-evolve` at an accepted skill (choose signal provider:
  pytest / anchor / scenario-eval), regression-gated acceptance.

### v0.4 — batch / series
- `batch.md` fan-out (Workflow) + global library-budget manager (rank by lift, prune over budget).

### v0.5 — self-host
- Scaffold skill-smith with skill-smith; evolve it with `self-evolve --self`.

### Later
- Generation-backend adapters (Skill_Seekers, official skill-creator interview, from-git-history).
- Externalize templates from `scaffold_skill.py` into `assets/templates/`.
