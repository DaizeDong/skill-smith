# skill-smith

Create Claude Code skills, one or a whole series, to an industry-leading, tested-real bar: research the field first, scaffold to spec, then refuse to ship anything that does not pass a hard acceptance gate.

[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-orange?style=flat)](https://docs.anthropic.com/en/docs/claude-code)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Research-first](https://img.shields.io/badge/Design-research--first-green?style=flat)](skills/skill-smith/reference/research-first.md)
[![Acceptance gate](https://img.shields.io/badge/Ships-only%20if%20it%20passes-green?style=flat)](skills/skill-smith/reference/acceptance-gate.md)
[![Languages](https://img.shields.io/badge/Languages-EN%20%2F%20CN-blue?style=flat)](#languages)
[![Roadmap](https://img.shields.io/badge/Roadmap-v0.1.2-purple?style=flat)](ROADMAP.md)

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
python skills/skill-smith/scripts/budget_check.py                            # library token budget
python skills/skill-smith/scripts/dedup_check.py                             # description overlap
```

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
