# Changelog

All notable changes to this project are documented here (Keep a Changelog style).

## [Unreleased]
### Fixed
- **Three of the new gates were reassuring the reader, which is the failure mode they exist to
  prevent.** All three were found by an independent pass over the run they had just shipped, and all
  three were green for the wrong reason.
  **`load_budget.py` measured nothing and called it a clean result.** It knew one repo shape,
  `skills/<name>/SKILL.md`. Two repos here keep their single SKILL.md at the ROOT, and those two
  hold two of the largest always-loaded files on the machine. In both it printed "no SKILL.md found,
  nothing to measure" and exited on a code its own docstring called "a state, not a failure". It now
  discovers both layouts (the same resolution `check_conformance.py` uses, deliberately identical),
  and measuring nothing exits **3** and says FAIL. Exit 2 is retired rather than redefined, so a
  caller that special-cased it as benign breaks loudly instead of quietly agreeing. Newly measured:
  `self-evolve` clean, `small-cap-deepdive` BLOCK at 5.82% duplicated prose, both previously unseen.
  **The size gate could not fail.** Its allowlist was seeded with exactly the five files over the
  fail line, so the first fleet run produced zero FAIL rows over 17% of the SKILL.md files and 40%
  of the always-loaded characters. The threshold was not the thing to move. Each entry now carries a
  dated shrink target (all to the 16,000 fail line, staged 2026-08-31 through 2026-10-31), WARNs
  every run with the arithmetic spelled out, is restated in a GRANDFATHERED ALWAYS-LOADED DEBT block,
  is carried on the summary line as `N grandfathered, M chars over target`, and **FAILS once its
  target date passes**. A grandfather clause with no expiry is a permanent exemption with a
  reassuring name.
  **`budget_check.py` could not see the actual harm.** Four installed skills were past the observed
  truncation cutoff and invisible to the model, and the tool exited 1 for an unrelated reason: two of
  OUR descriptions were long. Trimming those two would have turned it green with four skills still
  missing from the prompt, which is exactly what happened while this change was being written. Being
  invisible is a capability loss whoever authored the description, so the CONDITION now fails
  regardless of tier. The operator still never edits a third-party description; the message names the
  two levers that exist, uninstalling one or trimming ours, because the cutoff is a running total.
  Only the per-skill description CAP stays limited to our tier.
- **The retrofit lint said "across N file(s)" where N was the number of files SCANNED**, so 8 markers
  in 5 files read as "8 retrofit marker(s) across 10 file(s)". It now reports both counts.
- **`fleet_check.py` double-counted the truncated skills** because it derived the count by grepping
  `budget_check.py`'s stdout for the phrases that name a victim, and those phrases now also appear in
  the FAIL list: four truncated skills were reported as eight. `budget_check.py` prints one
  machine-readable `TRUNCATED: N` line, unconditionally including the zero, and `fleet_check.py`
  reads it.

### Added
- **Three SKILL.md checks in `check_conformance.py`, and a WARN status to carry them.** The gate
  asked whether files EXIST and never what the always-loaded file costs or whether it keeps its
  promises, so the fleet drifted with nothing to notice: a 41,959-char SKILL.md paid for on every
  invocation, three shard pointers naming files that are not on disk, and instruction text telling
  the reader which iteration added a rule instead of what the rule is.
  **Size:** warn above 12,000 chars, fail above 16,000. These were not chosen so the fleet passes:
  measured 2026-07-31, five of thirty SKILL.md files are over the fail line and four more are in the
  warn band. Those five are grandfathered BY NAME at their measured size, which they may shrink below
  and may not exceed by a character, so the allowlist can only ever get shorter and an already
  oversized file cannot quietly keep growing.
  **Shard pointers:** every relative path a SKILL.md names must resolve, against the skill directory
  first and the repo root second. It only FAILS when something corroborates that the file was meant
  to be here (its parent directory exists under the skill root, or its basename exists exactly once
  elsewhere in the repo); anything else WARNs, because a runtime output path and a path in the user's
  private companion repo are both legitimate. Measured before shipping: 225 pointers resolved, 3
  FAILs all hand-verified as genuinely dangling, 3 WARNs all verified correct by design.
  **Retrofit markers:** an iteration marker next to a rule verb ("Phase 5 adds ...") is a WARN. The
  first draft of this lint matched seven patterns and hit 261 times across 48 files, three of them
  ordinary English; it was cut to the retrofit syntax alone and measured at 8 hits in 5 files, all
  genuine, before shipping. Fenced code blocks are exempt so a doc can show the bad shape.
- **`scripts/budget_check.py` rewritten around what the loader actually does.** It globbed
  `~/.claude/skills` and compared the total to a hardcoded 15,000, which was wrong in three ways at
  once. It now reads the plugin tier from `installed_plugins.json` (the cache holds 2 to 4 stale
  versions per plugin plus scratch clones, so a glob over it finds 1,431 SKILL.md where 88 are
  actually loaded), reports our tier, other user skills and plugin skills separately, and fails only
  on OURS, since a third-party description over budget is real and is not the operator's to edit. It
  prints the documented 15,000-char budget AND the cutoff observed on this machine, which is not the
  same number: the last skill to keep its description sat at a running total of 19,943 chars and the
  next four appeared with no description at all despite having one in their SKILL.md. Those four are
  named in the output, because a truncation is invisible by construction. Adds a 180-char per-skill
  cap for our tier.
- **A VERDICT line, and an escalation for RED.** `fleet_check.py` ends every run with one line
  carrying a verdict and a coverage fraction, mirrored into the status JSON (`schema` 2) as
  `verdict`, `digest` and `coverage`. The nightly caller now quotes that line instead of composing
  its own adjective from the counts, which is how "pass 86, fail 0, skip 82" came to be reported as
  "all green" on the night before an audit found every one of these defects already present. A RED
  verdict additionally sends its own notification and makes the nightly job exit nonzero, the same
  escalation the config-drift check already used, so a red gate cannot be a line nobody reads.
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
- **`fleet_check.py` certified two things it never actually checked.** All three failures were the
  same shape: a PASS printed by a code path that never observed the thing on the label.
  1. *The workflow check stat()ed the local clone.* `os.path.isfile(<repo>/.github/workflows/
     pii-guard.yml)` answers "is this file on my disk", and the claim on the label was "this PUBLIC
     repo is gated by CI". Those come apart the moment a workflow is committed but not pushed, and
     they had: `claude-codex-memory-sync` is PUBLIC, its remote default branch carries only
     `test.yml`, and it scored PASS for as long as the check existed. It now interrogates the REMOTE
     default branch over `gh`, falling back to `git ls-remote` plus a local `ls-tree` when the remote
     HEAD is already in the object store, and reports UNKNOWN (never PASS) when neither can answer.
     Still no `git fetch`: the tool does not write to repos.
  2. *The CI check asked about one workflow and reported on the category.* It queried `pii-guard`
     only, under a heading claiming the guard CI was green. On 2026-07-30 it printed a single
     confident PASS for `promotion-assistant` whose `dash-guard` had been failing since 2026-07-24.
     It now queries every guard workflow found on the remote and prints one row per repo and
     workflow, named, so a red guard cannot shelter behind a green sibling.
  3. *UNKNOWN was defined as never-failing, and was carrying findings.* That reasoning is correct for
     "gh is not installed" and wrong for "this public repo has no guard workflow at all", which is a
     real finding in an UNKNOWN costume. UNKNOWN now means exactly one thing, "this run could not
     OBSERVE the answer", and a definitive negative from a remote that did answer is a FAIL. Because
     UNKNOWN can no longer carry a finding, it is genuinely safe for it not to affect the exit code.
     Unobserved rows print under their own `UNOBSERVED` heading and land in the status JSON, so a
     fleet nobody could look at cannot be mistaken for a clean one.

  Same audit, same defect class, three more paths that could report success without testing their
  label: `in_git_worktree()` collapsed "git said no" and "git could not run" into one `False`, so a
  machine with no git on PATH cleared **every** data directory in the boundary check (proven: with
  the probe forced to fail, the old code returns PASS, the new one UNKNOWN); the junctions and CI
  checks could emit zero rows, which prints as `pass 0, fail 0` and reads like a clean sheet, so an
  empty or missing skills dir now says so; and `check_conformance` silently dropped repos with no
  `plugin.json` instead of listing them, which would have hidden a repo falling out of coverage.
  The first run after the fix moved the fleet from 1 failure to 3, all of them real.
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
