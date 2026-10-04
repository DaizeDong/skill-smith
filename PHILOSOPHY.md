# skill-smith, Design Philosophy

> One test governs every change: **does it fix the framing, or just patch a symptom?**
> A skill is done when it is *proven*, not when it is *generated*.

Generators can emit a plausible SKILL.md without evidence that it triggers or improves a task.
skill-smith puts research before generation and evidence review after it, delegating existing
engines. Acceptance needs independent approval of the completed candidate and actual measurements;
the CLI validates contracts and never grants acceptance.

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
- **Root cause:** generated skills can fail silently; activation alone does not prove task
  improvement. Looking right is not evidence. So skill-smith
  borrows `self-evolve`'s spine, *accepted = verified, not asserted*, and applies it at creation
  time: a skill is **accepted only after passing every gate** (measured eval lift vs a no-skill
  baseline, held-out trigger rate, token budget, dedup, security audit, spec conformance, focus).
  Any missing or failed gate remains explicit. A valid non-fixture bundle still needs independent
  review; a hash establishes integrity, not truth.
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
- **Root cause:** the host has limited space for skill descriptions. Capacity must be observed on
  the current host, with its active library. Past that space, descriptions may be omitted and skills
  become hard to select. So a series is not
  "make N files," it is "fit the most valuable N within one global budget." The batch manager ranks
  candidates by measured lift and prunes the rest, explicitly.
- **Tradeoff:** the budget is shared with skills outside this repository. A current captured listing
  establishes visibility; historical capacity is advisory. A required removal decision stays
  BLOCKED with its projected cost, rather than being presented as a clean budget measurement.
- **Decision it produced:** `budget_check.py` is a *library-level* gate, and `batch.md` mandates a
  global library-budget manager, not a per-file loop.

## P5, Focused beats exhaustive: one skill, one job

- **Symptom patch:** cram capability into a big multi-purpose skill so it "covers more."
- **Root cause:** overlapping descriptions can cause wrong-skill selection. The one-job and
  at-most-three-modules rule keeps routing and proof cases assessable. A set of focused skills
  provides coverage while keeping each skill's scope reviewable.
- **Decision it produced:** the gate enforces single-responsibility + a dedup check across the
  library; a sprawling skill is rejected and split.

## P6, Dogfood and stay evolvable

- **Symptom patch:** the skill-builder exempts itself from its own rules.
- **Root cause:** if the meta-skill cannot pass its own gate and conform to its own spec, the rules
  are theater. skill-smith must meet the same conformance rules
  and is itself a valid target for `self-evolve --self`.
- **Decision it produced:** self-hosting remains a roadmap goal, with actual provider limits kept
  visible. The [documentation contract](skills/skill-smith/reference/documentation.md) applies to
  this repo: useful rationale, current usage and preserved history are completion duties. Docs
  changes invalidate candidate review. Style checks structure; independent reviewers check meaning.

---

**Precedence:** P1 and P2 outrank convenience. If a faster path skips research or weakens the gate,
it is wrong by definition, that is the framing skill-smith exists to protect.
