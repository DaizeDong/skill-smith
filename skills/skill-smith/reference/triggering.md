# Step 4, Draft the SKILL.md body + optimize the triggering description

The `description` field controls activation and needs both positive and negative query tests.
Earlier guidance reports ~50% non-triggering with default passive descriptions without a linked
source. Treat that figure as unverified context; use current measurements to assess a candidate.

## Body and progressive loading

- `check_conformance.py` warns above **12,000 characters** and fails above **16,000**. Keep the
  overview, when-to-use guidance, core steps and required rules in SKILL.md; place larger details
  in `reference/<shard>.md` for on-demand loading.
- Files over the limit on **2026-07-31** have named exceptions in `check_conformance.py` at their
  measured sizes. They may shrink but never grow. Each exception has a dated shrink target,
  warns on every run, appears in `N grandfathered, M chars over target`, and fails after its target
  date. The original 41,959-character example and change history remain in
  [CHANGELOG.md](../../../CHANGELOG.md).
- Every required relative resource must resolve against the skill directory or repository root.
- Write the current rule in its existing authoritative section. Put version deltas in CHANGELOG,
  consolidate superseded instructions, and link detailed rules from the SKILL entry. Follow
  [documentation.md](documentation.md) for semantic preservation and document ownership.
- Keep one job and at most three modules (P5). Split broader work under [batch.md](batch.md).

## Triggering description, two complementary methods

**A. Required six-lens manual review.** Rewrite the `description` through each lens, saving
each draft so the change is auditable:
1. *Gist*, would a stranger know what it does from this line alone?
2. *Name+desc pairing*, do the name and description reinforce, not repeat?
3. *False-positive / false-negative*, list 3 queries it SHOULD fire on and 3 it must NOT; does the
   wording separate them?
4. *Overfocus*, is it too narrow (misses real variants) or too broad (fires on everything)?
5. *Human-scan*, readable in one glance, no jargon wall.
6. *Every word earns its place*, cut anything that does not change when it fires.

**B. Measured trigger optimization.** Use training queries to propose changes and a separate
validation split to select the description. Run model and agent work through the installed
`llmcall` interface and its current policy. A score used to select `best_description` is a
validation score, even if an optimizer calls that split "held-out". Record it as selection evidence.

Freeze a separate evaluator-owned final test set before implementation. Keep its queries and
answers out of the implementation and optimizer prompts. After selecting and freezing the
description, the evaluator measures that candidate on the untouched final test set. Only this
independent final score can satisfy G2. If its feedback informs another revision, retire that
test set from final acceptance and obtain a new untouched evaluator-owned set.

## Output

A SKILL.md candidate, its documented manual pass, training/validation results and the independent
final G2 measurement when available. Keep all real queries, prompts and evaluation artifacts in
verified PRIVATE versioned DATA. Training and validation queries can support regression tests;
the evaluator retains the final test set. A manual pass or selection score alone leaves G2 missing.
