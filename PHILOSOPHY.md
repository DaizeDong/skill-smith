# skill-smith, Design Philosophy

> One test governs every change: **does it fix the framing, or just patch a symptom?**
> A skill is done when it is *proven*, not when it is *generated*.

skill-smith exists because the ecosystem optimizes the wrong half. Dozens of generators can emit a
SKILL.md; almost none can tell you whether the result is industry-leading or even works. So this
skill owns the two halves nobody owns, **research before** and **proof after**, and delegates the
generation in the middle.

---

## P1, Research-first: design against the state of the art, surveyed not asserted

- **Symptom patch:** "ask the model to write a good skill." The model averages its priors; you get a
  plausible, median skill and call it "leading."
- **Root cause:** *leading* is a claim about the field, and you cannot make it without seeing the
  field. So **every create starts with a delegated recon** to `market-intel`, best reference
  implementations to match or beat, frontier designs to borrow (this is where innovation actually
  comes from), and documented anti-patterns to avoid. The recon also tells us *how the best ones
  prove they work*, which becomes the eval signal in P2.
- **Decision it produced:** Phase 0 of the workflow is `research-first.md`, and skipping it is a hard
  invariant violation, not a shortcut. No design blind.

## P2, Generation != usable: the acceptance gate (anti-self-deception)

- **Symptom patch:** ship the generated skill; if it looks right, it is right.
- **Root cause:** generated skills fail *silently*, ~50% never trigger, field audits put most below a
  usable bar, and "it triggered" is not "it worked." Looking right is not evidence. So skill-smith
  borrows `self-evolve`'s spine, *accepted = verified, not asserted*, and applies it at creation
  time: a skill is **accepted only after passing every gate** (measured eval lift vs a no-skill
  baseline, held-out trigger rate, token budget, dedup, security audit, spec conformance, focus).
  Any failure is an **explicit reject**, never a silent ship.
- **Decision it produced:** `acceptance-gate.md` + `budget_check.py` + `dedup_check.py` +
  `check_conformance.py`; the gate is mandatory and its failures are surfaced, mirroring self-evolve's
  no-silent-degradation invariant.

## P3, Thin delegation: own the seam, not the engines

- **Symptom patch:** build one mega-tool that generates, evaluates, and iterates.
- **Root cause:** those engines already exist and are better than a reimplementation would be,
  `market-intel` (research), Skill_Seekers / the official skill-creator (generation), agent-skills-eval
  / scenario-eval (evaluation), `self-evolve` (iteration), `npx skills` (distribution). skill-smith's
  only durable value is the **composition + the gate + spec conformance + batch budgeting**.
- **Decision it produced:** the SKILL.md is thin; each step delegates and the repo refuses to
  reimplement skill-creator's interview, run_loop trigger optimizer, or self-evolve's loop.

## P4, The real batch constraint is the *library* token budget, not the file

- **Symptom patch:** "batch-create a series" == generate many SKILL.md files.
- **Root cause:** the system prompt has a hard budget for skill descriptions (the written rule says
  ~15k chars; measured 2026-08-01 on this machine, 21,565 chars survived out of 53,821 declared).
  Past it, descriptions are **silently dropped and the skills become invisible**. So a series is not
  "make N files," it is "fit the most valuable N within one global budget." The batch manager ranks
  candidates by measured lift and prunes the rest, explicitly.
- **The corollary that cost a day and a half:** the budget is shared with skills nobody in this repo
  authored, so the gate can report a real condition with no fix available to its reader. An alarm
  that is red by construction is how every gate here has historically come to be ignored, so the
  verdict now follows the LEVER: red when keystrokes close it, amber when the only remaining move is
  a decision, and the amber row carries the price of that decision rather than a shrug.
- **Decision it produced:** `budget_check.py` is a *library-level* gate, and `batch.md` mandates a
  global library-budget manager, not a per-file loop.

## P5, Focused beats exhaustive: one skill, one job

- **Symptom patch:** cram capability into a big multi-purpose skill so it "covers more."
- **Root cause:** benchmarks show focused skills (<=3 modules) beat exhaustive bundles, and
  overlapping descriptions cause wrong-skill selection. Coverage comes from a *clean set of focused
  skills*, not from fat ones.
- **Decision it produced:** the gate enforces single-responsibility + a dedup check across the
  library; a sprawling skill is rejected and split.

## P6, Dogfood and stay evolvable

- **Symptom patch:** the skill-builder exempts itself from its own rules.
- **Root cause:** if the meta-skill cannot pass its own gate and conform to its own spec, the rules
  are theater. skill-smith conforms to Skill Repo Spec v1 (this repo passes `check_conformance.py`)
  and is itself a valid target for `self-evolve --self`.
- **Decision it produced:** v0.5 self-hosts (scaffold skill-smith with skill-smith) and the repo is
  built to be evolved, not frozen.

---

**Precedence:** P1 and P2 outrank convenience. If a faster path skips research or weakens the gate,
it is wrong by definition, that is the framing skill-smith exists to protect.
