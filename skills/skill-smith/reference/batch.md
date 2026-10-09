# Batch creation and the whole-library budget

A batch shares the host's description budget with the existing library. Descriptions omitted from
the current host listing may prevent skill selection, so admitting candidates requires a measured
library-wide budget and an explicit decision for each candidate that does not fit.
The earlier ~15k-character rule and the 2026-08-01 observation of 21,565 visible characters from
53,821 declared describe historical assumptions and one machine; they do not establish current
capacity. Use a current captured listing and policy for G3.

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

- Run per-skill gates in parallel, then evaluate budget and dedup once across the complete set.
  A candidate that passes its own gates may still need to be deferred to stay within the budget.
- Rank by measured lift and list every deferred candidate with its reason.
- Keep each skill focused (P5); use composition for broader coverage.
- Re-run `budget_check.py` after admission. If a later batch exceeds capacity, include merging or
  pruning existing low-lift skills in the decision. A required removal remains BLOCKED until
  resolved; a projected saving is not a measured G3 pass.

## Output

Return the admitted set with its authorized deployment and self-evolve handoff state, a ranked
scoreboard with measured lift per skill, and the deferred list with reasons such as over budget,
low lift or merged into another skill. Use the same per-candidate documentation and review duties
in [documentation.md](documentation.md).
