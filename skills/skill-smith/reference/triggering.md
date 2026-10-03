# Step 4, Draft the SKILL.md body + optimize the triggering description

The single biggest reason skills fail in the wild is **they never trigger** (~50% with default passive
descriptions). The `description` field is the whole activation mechanism, treat it as the highest-
leverage line in the skill.

## Body (progressive disclosure)

- **`SKILL.md` is measured, not "thin".** Budget: **warn above 12,000 characters, fail above
  16,000**, enforced by `check_conformance.py`. This file is paid for on every invocation of the
  skill, so it holds overview, when-to-use, core steps and hard rules only. Everything else goes in
  `reference/<shard>.md`, loaded on demand. (Mirror this repo's own structure.)
  "Thin" is what the rule used to say, and because nothing could measure it, the fleet drifted to a
  41,959-character always-loaded file. Files already over the line on 2026-07-31 are grandfathered
  by name in `check_conformance.py` at their measured size and may shrink, never grow. Every
  grandfathered entry also carries a dated shrink target, WARNs on every run, is counted on the
  repo's summary line as `N grandfathered, M chars over target`, and FAILS once its target date
  passes. A grandfather clause with no expiry is a permanent exemption with a reassuring name.
- **Every relative path you name must resolve.** A shard pointer the agent cannot open is an
  instruction it cannot follow, and nothing surfaces it until a run needs that shard. Pointers
  resolve against the skill directory first, then the repo root.
- **State the rule, not the version delta.** A sentence shaped like the first line below tells the
  reader what changed, not what to do, and assumes they know which iteration they are in. Write the
  second. The history belongs in `CHANGELOG.md`.

  ```text
  bad:  Phase 5 adds a catalyst modifier to the score.
  good: A T1-evidenced catalyst adds one modifier point to the score.
  ```
- One job, ≤3 modules (P5). If it sprawls, split into a set (-> `batch.md`).

## Triggering description, two complementary methods

**A. The 6-lens manual pass (cheap, do always).** Rewrite the `description` through each lens, saving
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
