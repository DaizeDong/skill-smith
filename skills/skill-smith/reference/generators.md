# Step 2 — Choose the generation backend (delegate, don't reimplement)

skill-smith does not generate skill bodies from scratch — it routes to the best existing generator
for the input you have, then wraps the output with scaffold + gate. Pick by **what you are generating
from** (informed by the Step-0 brief):

| Input you have | Backend | Why | Notes |
|---|---|---|---|
| A repeated task / fuzzy intent | **official `skill-creator`** (anthropics/skills) interview | Canonical interview -> SKILL.md + built-in eval/`run_loop`; the reference standard | single-skill, human-in-loop; bundled in Claude Code |
| A docs site / GitHub repo / PDF corpus | **Skill_Seekers** (`pip install skill-seekers`) | Real batch generation from 18 source types, caching/checkpoint | generates FROM knowledge sources, not from a task spec; needs LLM key |
| Your own git history / session patterns | **affaan-m/ECC** `/skill-create`, `/learn`, `/evolve` | Mines your repo history into skills + instincts | star count disputed, marketing-heavy — use selectively |
| A high-quality SKILL.md structure to copy | crib **lexler/skill-factory** (6-lens) + Skill Repo Spec templates | docs-grounded structure + description method | crib the method, no need to run it |

## Rules

- **Prefer delegation over hand-writing** unless the skill is tiny. The generator gives you a
  structured first draft; your value is the brief (Step 0), the trigger optimization (Step 4), and the
  gate (Step 5).
- Whatever the backend, the output is **re-homed into the Spec-v1 skeleton** from `scaffold.md` (so the
  repo is conformant regardless of generator), and the description is re-optimized in Step 4.
- **Avoid**: `Romanescu11/hermes-skill-factory` (wrong platform + vaporware), and stale single-purpose
  generators with no iteration story (treat as template sources only).
- If no backend fits, hand-author the body — but still pass it through the same scaffold + gate.

## Output

A first-draft SKILL.md body (whatever the source), re-homed into the conformant repo, ready for
trigger optimization (Step 4) and the acceptance gate (Step 5).
