# skill-smith

Create Claude Code skills, one or a whole series, to an industry-leading, tested-real bar: research the field first, scaffold to spec, then refuse to ship anything that does not pass a hard acceptance gate.

[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-orange?style=flat)](https://docs.anthropic.com/en/docs/claude-code)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Research-first](https://img.shields.io/badge/Design-research--first-green?style=flat)](skills/skill-smith/reference/research-first.md)
[![Acceptance gate](https://img.shields.io/badge/Ships-only%20if%20it%20passes-green?style=flat)](skills/skill-smith/reference/acceptance-gate.md)
[![Languages](https://img.shields.io/badge/Languages-EN%20%2F%20CN-blue?style=flat)](#languages)
[![Roadmap](https://img.shields.io/badge/Roadmap-v0.1.3-purple?style=flat)](ROADMAP.md)

[English](README.md) | [中文版](README_CN.md)

---

## ⭐ Read this first, the design philosophy

skill-smith is built on one principle: **a skill is not "done" when it is generated, it is done when it is proven.** Two ideas follow from that, and they shape every decision in this repo:

1. **Research before you design (P1).** You cannot build something "industry-leading" by guessing. Before a single line of a new skill is written, skill-smith delegates a broad recon to [`market-intel`](https://github.com/DaizeDong/market-intel), best reference implementations, frontier designs to borrow, and known anti-patterns to avoid. The design target is the state of the art, surveyed, not asserted.
2. **Generation != usable (P2).** The whole community ships auto-generated skills that look fine and silently fail (~50% never even trigger; field audits put a majority below a usable quality bar). So skill-smith treats "accepted" exactly the way [`self-evolve`](https://github.com/DaizeDong/self-evolve) treats "improved": only after an anti-self-deception **acceptance gate** (measured eval lift vs baseline + held-out trigger rate + token budget + dedup + security + spec conformance + single-responsibility focus).

So skill-smith does **not** try to be a bigger generator. It is a **thin orchestrator** that owns only the seam nothing else owns, and delegates the heavy parts to tools you already run.

📜 **[Read the full design philosophy -> PHILOSOPHY.md](PHILOSOPHY.md)** (6 principles, each with the patch-vs-root contrast and the real decision it produced).

---

## What it is (and isn't)

You already have the pieces: `market-intel` (research orchestration), `self-evolve` (anti-self-deception auto-iteration), and Skill Repo Spec v1 (output conventions). What was missing is the layer that **composes** them into "create a new skill, well." That is skill-smith.

It does **only what nothing else does**, and delegates everything else:

1. **Research-first recon**, delegate landscape + frontier-design survey to `market-intel` (front engine).
2. **Spec-conformant scaffolding**, deterministically emit a Skill-Repo-Spec-v1 repo skeleton (7 required files, badges, version four-source-synced, plugin fingerprint).
3. **Acceptance gate**, eval lift, trigger rate, system-prompt token budget, cross-library dedup, security audit, spec conformance, focus. Fail = explicit reject, never silent ship.
4. **Auto-iteration handoff**, hand the accepted skill to `self-evolve` (back engine) for regression-gated improvement.
5. **Batch**, fan out a *series* of candidate skills, each through the gate, under one global library-budget manager.

It is **not**: a from-scratch generator (it calls Skill_Seekers / the official skill-creator), an eval framework (it calls agent-skills-eval / scenario-eval), or an iteration engine (it calls self-evolve). It is the glue + the gate.

It is **not for**: improving an *existing* skill (that is `self-evolve`), or answering "is there a ready-made skill for X" (that is `market-intel`'s `ready-skills` domain).

## Install

```
/plugin install github:DaizeDong/skill-smith
```

Or clone manually:

```bash
git clone https://github.com/DaizeDong/skill-smith.git ~/.claude/plugins/skill-smith
```

(Maintainer setup: source lives in `CodesClaude/skill-smith`, deployed to `~/.claude/skills/skill-smith` via a PowerShell junction, see [`reference/deploy.md`](skills/skill-smith/reference/deploy.md).)

## Quick start

> "Use skill-smith to create a skill that <does X>."   (single)
> "Use skill-smith to batch-create skills for <A, B, C>."   (series)

skill-smith will: research the field via market-intel -> dedup-check your library -> scaffold a spec repo -> draft + trigger-optimize the SKILL.md -> run the acceptance gate -> hand off to self-evolve -> deploy.

You can also run the scripts directly:

```bash
python skills/skill-smith/scripts/scaffold_skill.py my-skill \
  --tagline "One line, verb-first, quantified." \
  --description "When to trigger + what it does + scope, one paragraph." \
  --topics "domain-a,domain-b"

python skills/skill-smith/scripts/check_conformance.py ~/CodesClaude/my-skill   # Spec v1 linter
python skills/skill-smith/scripts/bump_version.py ~/CodesClaude/my-skill --level patch  # all 5 sites
python skills/skill-smith/scripts/budget_check.py                            # library prompt budget
python skills/skill-smith/scripts/dedup_check.py                             # description overlap
python skills/skill-smith/scripts/fleet_check.py                             # whole fleet, read only
```

`check_conformance.py` also measures the SKILL.md itself, because that file is paid for on **every**
invocation of the skill: **warn above 12,000 characters, fail above 16,000**, every relative path it
names must resolve on disk, and instruction text must state the rule rather than which iteration
added it. Files already over the size line on 2026-07-31 are grandfathered by name at their measured
size and may shrink, never grow, so the allowlist can only get shorter. Each entry also carries a
**dated shrink target**: it WARNs loudly on every run with the arithmetic spelled out, the per-repo
summary line states `N grandfathered, M chars over target`, and once the target date passes with the
file still over target the entry FAILS. The allowlist was seeded with exactly the five files over the
line, so without that the gate's first fleet run had zero FAIL rows over 17% of the files and 40% of
the always-loaded characters, and a run with no failures reads as "the fleet is within budget".

`budget_check.py` answers the one question whose failure is invisible by construction: past a budget
the loader silently drops skill descriptions, so a skill keeps existing and simply never fires. It
reports three tiers separately (`ours`, `local` user skills, `plugin` skills), reads the plugin tier
from `installed_plugins.json` rather than globbing the cache (which holds 2 to 4 stale versions per
plugin), and prints both the documented 15,000-char budget and the capacity actually **measured** on
2026-08-01 by diffing a live skill listing against every `SKILL.md` on disk: 79 of 163 file-backed
skills kept their description, 84 appeared as a bare name, and the surviving lines totalled 21,565
chars against a declared library of 53,821.

That measurement retired three claims this tool used to make. Truncation is **not** a contiguous tail
in load order, so the tool no longer guesses victim names: without `--listing FILE` it prints a
**floor** on how many skills must lose their description and says the names are not derivable from
disk; with one, it **measures** them. The loss is not confined to the user tier, it falls mostly on
plugins. And uninstalling a plugin is not inert, it is the largest lever there is.

The verdict follows the **lever**, not the severity. A finding closable tonight by editing (one of
our descriptions over the 180-char cap, or an overflow small enough that trimming would clear it) is
**FAIL**, red, with the specific cuts named. An overflow that no amount of editing can absorb is
**BLOCKED**, amber, stated in full every run with the arithmetic on both sides and a ranked, priced
list of which plugin removals would clear it, because "uninstall something" without a number is a
shrug rather than a lever. Amber is not a softer red: it means the remaining move is a decision about
what to stop having, and a colour that never changes stops being read. Only the per-skill description
**cap** stays limited to our tier, because it is a Spec-v1 authoring rule for skills this repo
produces, not a judgement about skills that predate it. Run `--plugins` for the full ranking.

`fleet_check.py` is the driver the linter above never had. It fans `check_conformance.py` over every
plugin repo and adds what nothing else checks: skill junctions resolve, a repo marked PUBLIC carries
every guard workflow (`pii-guard` **and** `dash-guard`) **on its remote default branch**, the
installed library still fits in the system prompt, a resolved real-run data directory is not inside a
**PUBLIC or UNKNOWN** repo, and **every workflow on every repo of ours**, public and private alike,
is actually green **on the remote default branch**, one row per repo and workflow. It
is **read-only, with no `--fix`** and no `git fetch`, exits nonzero on any FAIL, and writes a
UTC-stamped status JSON so a scheduled caller can tell "the run happened" apart from "the run
passed". Add `--offline` to skip the network-backed probes.

Two of those answers were quietly about the wrong subject until 2026-07-31. The CI probe asked for
the newest run on **any ref**, so a green push to a topic branch was printed as the default branch's
status; on 2026-07-22 that would have shown a repo's `pii-guard` as PASS from a green topic-branch
run while its own `master` run was a FAILURE. It now filters on the default branch, and "no run on
the default branch" is `UNKNOWN` rather than a quiet fallback to whatever run exists. The visibility
answer behind the data-boundary check read a cached map **first** and asked `gh` only on a miss, so
one stale line of JSON could clear a data directory sitting in a public repo, forever, with nothing
on the machine refreshing that file. `gh` is now asked live and the map only votes when `gh` cannot
answer, and only while it is younger than its trust window: a cache that can never expire is not a
cache, it is an assertion.

The remote is the subject of that workflow check on purpose. It used to stat the local clone, so a
guard workflow that was committed but never pushed scored PASS for a PUBLIC repo whose remote carried
no guard at all. `UNKNOWN` now means one thing only, "this run could not observe the answer" (no
`gh`, unauthenticated, rate limited, offline), which is why it is safe for it to never affect the
exit code; a definitive negative from a remote that did answer is a `FAIL`. Unobserved rows are
printed under their own `UNOBSERVED` heading and listed in the status JSON, because a fleet nobody
could look at must not read like a clean one.

Every run ends with one **VERDICT** line carrying a coverage fraction, and a caller is meant to quote
that line rather than build its own sentence out of the counts. On 2026-07-30 the nightly digest
turned "pass 86, fail 0, skip 82" into the words "all green" while every defect the next day's audit
found was already in the fleet: nearly half the checked surface was never evaluated and the report
still read as a clean sheet. `GREEN` may now mean only "nothing that was evaluated failed", `AMBER`
means there are findings that no edit fixes today, and the same line says how much was looked at.

`bump_version.py` moves the version at all five sites at once (plugin.json, both README badges,
ROADMAP, CHANGELOG). It refuses on an already-drifted repo instead of papering over the drift, and
it never commits or pushes: cutting a release stays a human decision.

## How to invoke

Trigger words: *create a skill, build a skill, scaffold a skill, author a new skill, batch-create skills, make a series of skills, optimize a skill's trigger / description, skill factory.*

## Limitations

- v0.1 ships the **framework**: research-first workflow + deterministic scaffolder + Spec-v1 linter + budget/dedup checks. The acceptance gate's eval-lift wiring (agent-skills-eval / scenario-eval) and the self-evolve handoff land in v0.2/v0.3 (see [ROADMAP.md](ROADMAP.md)).
- It assumes `market-intel` and `self-evolve` are installed; without them it degrades to plain web research and a manual gate, and says so (never silently).
- It optimizes for *correct, focused, proven* skills, not raw volume, by design it will refuse to add a skill that overflows the library token budget.

## Languages

English (`README.md`, authoritative) · 中文 (`README_CN.md`)

## Roadmap · Contributing · License

See [ROADMAP.md](ROADMAP.md) · [CONTRIBUTING.md](CONTRIBUTING.md) · [LICENSE](LICENSE) (MIT).
