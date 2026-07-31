---
name: skill-smith
description: Create, scaffold, or batch new Claude Code skills to a tested-real bar: research-first design, spec scaffold, eval+budget acceptance gate, then self-evolve iteration.
---

# skill-smith, a skill that creates skills

> Governing principle (full text in the repo's `PHILOSOPHY.md`): **a skill is done when it is
> *proven*, not when it is *generated*.** Research before you design (P1); generation != usable, so
> nothing ships without passing the acceptance gate (P2); own the seam and delegate the engines (P3).

## When to stop and route elsewhere (decide first)

- **Improving / fixing an EXISTING skill** -> this is `self-evolve`'s job. Route there, do not recreate.
- **"Is there a ready-made skill for X?"** -> `market-intel`'s `ready-skills` domain. Route there.
- **Creating a NEW skill, or a batch of new skills** -> continue here.

## Workflow (thin, load the named `reference/<shard>.md` only for the step you are on)

| # | Step | Load | Delegates to |
|---|---|---|---|
| **0** | **Research-first (MANDATORY)**, survey best references + frontier designs + anti-patterns before any design | `reference/research-first.md` | **market-intel** (deep scale) |
| 1 | Triage + dedup, overlap with existing library? single vs batch? | `reference/scaffold.md` §dedup + `scripts/dedup_check.py` | none |
| 2 | Choose generation backend | `reference/generators.md` | Skill_Seekers / official skill-creator |
| 3 | Scaffold Spec-v1 repo (add `--with-config` if config-bearing) | `scripts/scaffold_skill.py` + `reference/config-spec.md` | none |
| 4 | Draft SKILL.md + optimize triggering description | `reference/triggering.md` | official `run_loop.py` (60/40) |
| 5 | **Acceptance gate** (all must pass; any fail = explicit reject) | `reference/acceptance-gate.md` + `budget_check.py` + `dedup_check.py` + `check_conformance.py` + `check_config_conformance.py` (G8) | agent-skills-eval / scenario-eval |
| 6 | Hand off to auto-iteration | `reference/iterate-handoff.md` | **self-evolve** |
| 7 | Batch a series (if multiple) | `reference/batch.md` | Workflow + library-budget manager |
| 8 | Deploy (junction + GitHub publish; then MANDATORY set remote metadata + verify) | `reference/deploy.md` + `scripts/set_repo_metadata.py` + `scripts/check_remote_conformance.py` | npx skills / gh |

> **Config-bearing skills** (need per-user keys / installed-tool registry / endpoints) are a
> first-class case: decide at Step 1, scaffold with `--with-config` (Step 3), and they MUST pass the
> **config standard (E1 to E7)** at the gate (Step 5, G8). Authority: `reference/config-spec.md`.

## Hard invariants (never violate, these are P1/P2/P4/P5 in force)

1. **Research before design.** Never scaffold a skill without the Phase-0 market-intel recon. If
   market-intel is unavailable, fall back to `deep-research` and SAY SO, never skip silently.
2. **No skill is "accepted" without passing the full gate.** Eval lift vs baseline + held-out trigger
   rate + library token budget + dedup + security audit + spec conformance + single-responsibility.
   Failure is surfaced as an explicit gap, never a silent ship.
3. **The token budget is library-wide, and it is already blown.** Past the cutoff the loader drops
   descriptions silently, so the skill exists and never fires. The written rule says ~15k chars; the
   cutoff OBSERVED on this machine 2026-07-31 is ~20k, and four installed skills are past it right
   now. Run `budget_check.py`, believe the observed number, and never add without pruning. Our own
   descriptions are capped at **180 chars** each, the part that is ours to fix.
4. **One skill, one job (<=3 modules).** Sprawl is rejected and split.
5. **Conform or it is not a DaizeDong skill, locally AND on the remote.** Output must pass
   `check_conformance.py` (G6: local files, 7 files, philosophy-first bilingual README, badge block,
   version four-source-synced, plugin fingerprint) **and**, once published, `check_remote_conformance.py`
   (G6b: the live GitHub repo carries the base-9 + domain topics and a description). These are **two
   layers**: a plain `git push` sets no remote metadata, so passing G6 alone is how the topics=null
   incident happened. Deploy (Step 8) MUST run `set_repo_metadata.py` then G6b, neither layer is
   optional. **Never hand-edit the five version sites**: use `scripts/bump_version.py` (see
   `reference/scaffold.md` §bump). A five-file manual ritual is not a process, it is a pending
   bug, which is why most repos drifted as half-applied releases.
6. **Config-bearing = configurable-by-anyone, or rejected.** If a skill needs a companion config
   (keys / registry / endpoints), it MUST pass the seven-element config standard (E1 to E7) via
   `check_config_conformance.py` (G8): documented schema, env-var discovery mount, deterministic
   `init`, a `verify` doctor, two configs hot-swappable by env var, secrets gitignored (Mode B), and
   a README Config section. "Works on my machine" config is a reject. See `reference/config-spec.md`.

## After the gate: the fleet, not just the new skill

`check_conformance.py` was correct for weeks and surfaced nothing, because nothing ran it. A gate
with no driver does not exist, and the missing piece was never more judgment. `scripts/fleet_check.py`
is that driver: **read-only, no `--fix` and never one**, it fans the linter over every plugin repo and
adds what nothing else checks (skill junctions resolve, visibility PUBLIC implies every guard
workflow -- `pii-guard` and `dash-guard` -- is on the repo's REMOTE default branch, the installed
library still fits in the system prompt, a resolved real-run data dir is not inside a git worktree,
and each of those guard workflows is actually green, one row per repo and workflow). It exits nonzero
on any FAIL and writes a UTC-stamped status JSON, so a scheduled caller checks the artifact's
freshness to know the run HAPPENED rather than trusting an exit code that only says whether it
PASSED. Run it by hand with `python scripts/fleet_check.py [--offline]`.

Three rules keep that report honest. The workflow check interrogates the REMOTE, never the working
tree, because a guard file on your disk that was never pushed is not CI. `UNKNOWN` means only
"could not observe" (no `gh`, unauthenticated, rate limited, offline) which is why it never affects
the exit code, while a definitive negative from a remote that did answer is a `FAIL`; `WARN` means
observed, not clean, and unfixable by any edit available today. And the run ends in one **VERDICT**
line carrying a coverage fraction, which the caller quotes verbatim: the nightly digest once turned
"pass 86, fail 0, skip 82" into the words "all green" over a fleet in which every defect of the next
day's audit was already present. If you add a check here, put it on one side of those lines and say
which.

## Progressive loading

This `SKILL.md` is the only always-loaded file. Read `reference/<shard>.md` on demand, one at a time,
for the step you are executing. Never read the whole `reference/` directory at once.
