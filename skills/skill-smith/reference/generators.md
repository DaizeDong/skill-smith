# Step 2, Select a generation backend

Select an available generator for the input identified in the Step-0 brief. Integrate its draft
with the Spec-v1 scaffold, then complete triggering and acceptance work:

| Input you have | Backend | Why | Notes |
|---|---|---|---|
| A repeated task / fuzzy intent | **official `skill-creator`** (anthropics/skills) interview | Canonical interview -> SKILL.md + built-in eval/`run_loop`; the reference standard | single-skill, human-in-loop; bundled in Claude Code |
| A docs site / GitHub repo / PDF corpus | **Skill_Seekers** (`pip install skill-seekers`) | Real batch generation from 18 source types, caching/checkpoint | generates FROM knowledge sources, not from a task spec; needs LLM key |
| Your own git history / session patterns | **affaan-m/ECC** `/skill-create`, `/learn`, `/evolve` | Mines your repo history into skills + instincts | repository popularity and capability claims require independent verification |
| A high-quality SKILL.md structure to copy | **lexler/skill-factory** (6-lens) + Skill Repo Spec templates | docs-grounded structure + description method | use the documented method without running it |

## Rules

- Prefer an available generator for the first draft unless the skill is small enough to author
  directly. Research (Step 0), triggering (Step 4) and acceptance (Step 5) remain required.
- Whatever the backend, the output is **re-homed into the Spec-v1 skeleton** from `scaffold.md` (so the
  repo is conformant regardless of generator), and the description is re-optimized in Step 4.
- Do not select `Romanescu11/hermes-skill-factory`: its platform is outside this
  workflow and its implementation is unverified. Use stale generators without an iteration path as template sources only.
- If no backend fits, hand-author the body, but still pass it through the same scaffold + gate.

## Output

Deliver a draft repository and assign a generation owner to complete it under
[documentation.md](documentation.md). Integrate new guidance into the existing authoritative
sections, resolve placeholders and superseded copies, and preserve current EN/CN meaning before
the final candidate snapshot. Triggering and evaluator evidence still require the frozen policy;
generator output alone does not satisfy acceptance.
