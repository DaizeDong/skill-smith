# Changelog

All notable changes to this project are documented here (Keep a Changelog style).

## [Unreleased]
### Added
- **`scripts/fleet_check.py`, the driver `check_conformance.py` never had.** The linter has been
  correct and complete for weeks and surfaced nothing, because nothing ever ran it: a gate with no
  driver does not exist. This fans it over every repo carrying `.claude-plugin/plugin.json` and adds
  the four assertions nothing on the machine performs, each with a real failure mode: every skill
  junction resolves (a repo move silently empties the agent's library and no error is raised
  anywhere), visibility PUBLIC implies a `pii-guard` CI workflow, a resolved real-run data directory
  is **not** sitting inside a git worktree, and the `pii-guard` CI that the whole doctrine calls
  "the authority" is actually green. That fourth one is the inverse of `data_boundary.py`: the
  boundary proves the repo holds no real-run output, this proves the output directory is not itself
  a repo, and in the 2026-07 leak both halves were needed and only one existed. There is **no
  `--fix` and never will be**: several of the directories it inspects hold live secrets and
  uncommitted state, so "auto-converge" is a data-loss button with a helpful label. It exits nonzero
  on any FAIL and writes a UTC-stamped status JSON, so a scheduled caller can verify the run
  HAPPENED (freshness) separately from whether it PASSED, which an exit code alone cannot express.
  Anything it cannot observe (gh missing, unauthenticated, rate limited, workflow never run) is
  reported UNKNOWN and never blocks.
- **`scripts/bump_version.py`, the missing half of the version rule.** `scaffold_skill.py` stamped
  the five version sites once at creation and `check_conformance.py` only read them, so every
  release was five hand edits in the right order across five files, with no feedback until someone
  ran the linter. Most repos ended up drifted, usually as a half-applied release (plugin.json and
  CHANGELOG moved, the README badges and ROADMAP did not). The bumper rewrites all five together,
  demotes the previous `## vX.Y.Z (current)` ROADMAP heading, and opens a dated CHANGELOG section
  that absorbs any `## [Unreleased]` body. Two refusals are the point of it: it **exits nonzero on
  an already-drifted repo** and prints the diff, because bumping over drift greens the linter while
  erasing which site was left behind; and it **never commits, tags or pushes**, because cutting a
  release is a human decision. A badge pre-release marker (`Roadmap-v0.2.2%20alpha-purple`)
  round-trips rather than being flattened.
- `scripts/version_sites.py`, one definition of where a version lives. The scaffolder, the linter
  and the bumper now share it, so a bump cannot stamp a shape the linter rejects.
- `tests/test_bump.py`, 17 tests covering the five sites moving together, the drift refusal writing
  nothing, Unreleased absorption, pre-release round-trip, and rollback leaving no half-bumped repo.

### Fixed
- **`check_conformance.py` reported conforming repos as broken.** The version regex demanded a bare
  `Roadmap-vX.Y.Z-purple` badge, so a repo carrying a deliberate pre-release marker
  (`Roadmap-v0.2.2%20alpha-purple`, which is how shields.io encodes `v0.2.2 alpha`) read as having
  no version at all and failed the sync check while all five of its sites agreed. Same fault in the
  Languages badge check: an exact substring test meant a repo that also shipped Spanish
  (`Languages-EN%20%2F%20CN%20%2F%20ES-blue`) was marked as missing the badge, penalizing it for
  translating more. A linter that cries wolf gets muted, which is worse than no linter.
- **The scaffolded PII gate was 113 lines behind the canonical scanner**, so every repo skill-smith
  created was born with a downgraded backstop (no cross-repo token loading, no machine-path
  detector, no repo-slug self-exclusion). `assets/pii-guard/` is re-vendored from canonical:
  `pii_guard.py` +113 lines, `test_pii_guard.py` +110, `data_boundary.py` +1, `datadir.py` reworded.

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
