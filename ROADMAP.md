# Roadmap

Current: **v0.1.5**

The plugin manifest defines the release version. Later work is recorded in CHANGELOG Unreleased;
it does not imply another release or production readiness.

## Current capabilities beyond the release baseline

- The Python package provides schema 1 source catalogs, exact selection, validated
  overlays and llmcall adapters. Synthetic contract and wheel checks are separate
  from live loader, provider-permission and deployment acceptance.
- Evidence CLI validates G1 paired scores, G2 held-out trials and required policy/candidate-bound
  artifacts. It reports contract-only verdicts and never grants acceptance.
- Completed implementation/docs/version metadata freeze before evidence and independent review;
  evaluator policy and holdout freeze before implementation. Snapshots include document state.
- Library, private transport and remote workflow checks retain missing/unobserved states.
- Scaffold assigns all docs. Conformance delegates document structure to the pinned Style checker;
  release preparation refuses placeholders, invalid dates and non-advancing versions.
- Installed provider readiness, semantic accuracy and actual usefulness need their own evidence.

## v0.1.5 (current)
See [CHANGELOG.md](CHANGELOG.md) for this release; current capabilities follow below.

## v0.1.4
See [CHANGELOG.md](CHANGELOG.md) for this release; current capabilities follow below.

## v0.1.3, the dash gate is scaffolded into every new skill

- `scaffold_skill.py` initializes the pinned `guards/` security and `style/` presentation submodules.
  Its dash workflow calls `./style/ci/dash-guard`; the scanner is `style/tools/dash_guard.py`.
  The scanner de-dashes Markdown and Python comments only, leaving every string literal
  untouched, and never touches the ASCII hyphen.
- `check_conformance.py` verifies both files exist and that the tree is dash-clean.

## v0.1.2, remote metadata is a first-class deploy step (G6b)

- Root-cause fix for the topics=null incident: a plain `git push` sets no GitHub topics/description, and
  the old `check_conformance.py` (G6) only lints LOCAL files, so repos shipped Spec-non-conformant.
- `scripts/set_repo_metadata.py`: idempotent setter for remote topics (base-9 + domain) + description +
  homepage, defaulting from the repo's own `plugin.json` (owner/repo from homepage, domain topics from
  keywords). PUT replaces the whole topic set; `--dry-run` previews.
- `scripts/check_remote_conformance.py`: Gate **G6b**, queries the live GitHub repo and asserts base-9
  present, >=1 domain topic, non-empty description (homepage advisory). Explicit SKIP if gh missing /
  unauthenticated / offline (never a silent pass).
- `deploy.md` Step 8 now makes set-metadata + G6b a MANDATORY publish finisher; SKILL.md invariant 5 +
  acceptance-gate add G6b as the remote-layer twin of G6 ("both layers required").

## v0.1.1, config-bearing skills are first-class

- `reference/config-spec.md`: the seven-element standard (E1 to E7) for any skill that needs a companion
  config, documented schema, env-var discovery mount, deterministic `init`, a `verify` doctor, two
  configs hot-swappable by env var, secrets gitignored (Mode B), and a README Config section.
- `scaffold_skill.py --with-config` emits the standard; `check_config_conformance.py` is Gate G8
  (auto-detects config-bearing repos, live determinism + hot-swap test). Generalized from
  market-intel's companion-config-spec to be skill-agnostic.

## v0.1.0, framework

- Thin `SKILL.md` orchestrator with the full create workflow (research-first as Phase 0).
- `PHILOSOPHY.md` (6 principles) + Skill-Repo-Spec-v1 conformance for this repo itself (dogfood).
- Reference shards for every step: research-first, scaffold, triggering, acceptance-gate,
  generators, iterate-handoff, deploy, batch.
- Working scripts: `scaffold_skill.py` (deterministic Spec-v1 repo generator),
  `check_conformance.py` (Spec-v1 linter), `budget_check.py` (library token budget),
  `dedup_check.py` (cross-library description overlap).
- Goal of this version: reliably emit a **spec-conformant skill skeleton** and lint any skill repo.

## Planned

### v0.2, evaluator integration
- Contract validation is implemented; running external measurements remains an integration duty.
  Select only installed providers and preserve unavailable status.
- Keep final held-out triggering evaluation separate from selection/optimization.
- Expand measured provider readiness without confusing validation with independent acceptance.

### v0.3, self-evolve handoff
- `iterate-handoff` automates pointing `self-evolve` at an accepted skill (choose signal provider:
  pytest / anchor / scenario-eval), regression-gated acceptance.

### v0.4, batch / series
- `batch.md` fan-out (Workflow) + global library-budget manager (rank by lift, prune over budget).

### v0.5, self-host
- Scaffold skill-smith with skill-smith; evolve it with `self-evolve --self`.

### Later
- Generation-backend adapters (Skill_Seekers, official skill-creator interview, from-git-history).
- Externalize templates from `scaffold_skill.py` into `assets/templates/`.
