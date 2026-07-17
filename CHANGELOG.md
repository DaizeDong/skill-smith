# Changelog

All notable changes to this project are documented here (Keep a Changelog style).

## [0.1.3] - 2026-07-16
### Added
- **Dash gate (Spec v1 section 10) is now scaffolded into every new skill.** `scaffold_skill.py`
  vendors `tools/dash_guard.py` plus a `dash-guard` CI workflow (assets under `assets/dash-guard/`),
  so a new skill is born enforcing the house rule that published prose carries no en/em dash. The
  tool de-dashes Markdown and Python COMMENTS only, leaving every string literal (docstrings and data
  such as regexes or fixtures) untouched, so a functional literal is never corrupted; the ASCII hyphen
  is never touched. `check_conformance.py` now verifies the two files exist and that the tree is
  dash-clean. Runtime output compliance stays the renderer's job (normalize dashes in `_inline`).

## [0.1.2] - 2026-06-25
### Added
- **Remote conformance is now a first-class deploy step (Gate G6b).** Root-cause fix for the
  topics=null incident: `git push` sets no GitHub topics/description/homepage, and `check_conformance.py`
  (G6) only validates LOCAL files, so repos passed G6 yet shipped with `topics=null`, violating Skill
  Repo Spec v1.
- `scripts/set_repo_metadata.py`, idempotent setter for remote topics (base-9 + domain) + description
  + homepage via `gh api PUT .../topics` and `gh repo edit`. Defaults are derived from the repo's own
  `plugin.json` (owner/repo from homepage, domain topics from keywords minus the trailing `skill`/base-9
  dups, one-line description). `--dry-run` previews; PUT replaces the whole topic set so re-runs converge.
- `scripts/check_remote_conformance.py`, Gate **G6b**: queries the live GitHub repo and asserts the
  base-9 topics are all present, >=1 domain topic exists, and description is non-empty (homepage is
  advisory). Prints an explicit **SKIP** (never a silent pass) when `gh` is missing / unauthenticated /
  offline. Self-tested read-only: PASS on a conformant repo, FAIL (exit 1) on a non-conformant one.
- `reference/deploy.md` Step 8: setting remote metadata + passing G6b is now a MANDATORY publish
  finisher (was a one-line optional `gh repo edit --add-topic`). SKILL.md invariant 5 + workflow Step 8
  and `reference/acceptance-gate.md` add G6b as the remote-layer twin of G6, both layers required,
  neither substitutes for the other.

## [0.1.1] - 2026-06-25
### Added
- **Config-bearing skills are now first-class** (config-spec E1 to E7). A skill that needs a companion
  config (keys / installed-tool registry / endpoints) must be configurable by anyone on the first try,
  generate the identical config shape, and hot-swap between two configs via one env var.
- `reference/config-spec.md`, authoritative seven-element standard (schema doc · env-var discovery
  mount · deterministic init · verify doctor · hot-swap · secrets Mode B · README Config section),
  generalized from market-intel's companion-config-spec to any skill.
- `scripts/check_config_conformance.py`, Gate **G8**: auto-detects config-bearing repos and enforces
  E1 to E7 with a live deterministic-generation test + hot-swap test (runs the repo's own init/verify).
  Non-config-bearing repos are reported and skip the gate.
- `scaffold_skill.py --with-config`, emits the config-bearing standard: `CONFIG.md`, generic
  `scripts/init_config.py` + `verify_config.py` (auto-detect skill from plugin.json), README
  `## Config`/`## 配置` section (EN+CN), and a secrets `.gitignore` (Mode B).
- `assets/config/` templates (init/verify scripts, CONFIG.md, README sections, gitignores).
- SKILL.md invariant 6 + workflow Steps 3/5/8 now treat config-bearing as a first-class case;
  acceptance-gate G8 added; `tests/test_config.py` (A-tier signal for the new gate).

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
- `trim_descriptions.py`, library description-budget remediation (scan -> review -> apply, with
  per-file backups and a dry-run), the concrete fix for an over-budget skill set (Gate G3).
