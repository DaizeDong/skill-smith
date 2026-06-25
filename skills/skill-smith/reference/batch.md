# Step 7 — Batch / series (P4: the library token budget is the real constraint)

"Create a series of skills" is NOT "generate N SKILL.md files." The system prompt has a hard budget
(~15k chars / ~4k tokens of skill descriptions); past it, descriptions are **silently truncated and
the skills become invisible**. So a batch is "fit the most valuable skills within one global budget."

## Pipeline

```
candidate list (from Step-0 brief: the focused jobs)
      │  Workflow fan-out (parallel) — each candidate runs Steps 1-5 independently
      ▼
[ scaffold → generate → trigger-optimize → single-skill gate (G1,G2,G5,G6,G7) ]
      │
      ▼  global LIBRARY-BUDGET MANAGER (the barrier — needs all candidates together)
   rank accepted candidates by measured eval-lift (G1)
   greedily admit, summing descriptions, until budget_check would fail (G3)
   over-budget remainder: merge related skills, tighten descriptions, or DEFER (explicit)
      │
      ▼  cross-batch dedup (G4) across the admitted set + existing library
      ▼  hand admitted set to self-evolve (Step 6); deploy admitted set (Step 8)
```

## Rules

- **Per-skill gates run in parallel; the budget + dedup gates run once over the whole set** (a barrier).
  A skill that is great alone can still be deferred because the set would overflow — that is correct.
- **Rank by proven lift, not by count.** The output of a batch is a *ranked, budget-fit, deduped set*,
  with the deferred remainder listed explicitly (never silently dropped).
- **Prefer a clean set of focused skills over a few fat ones** (P5): coverage comes from composition.
- Re-run `budget_check.py` after admission; if a future batch pushes the library over budget, the
  manager must prune/merge existing low-lift skills, not just refuse the new ones.

## Output

An admitted set (deployed + handed to self-evolve), a ranked scoreboard (lift per skill), and an
explicit deferred list with the reason (over budget / low lift / merged-into-X).
