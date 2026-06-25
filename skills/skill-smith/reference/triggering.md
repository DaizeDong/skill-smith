# Step 4 — Draft the SKILL.md body + optimize the triggering description

The single biggest reason skills fail in the wild is **they never trigger** (~50% with default passive
descriptions). The `description` field is the whole activation mechanism — treat it as the highest-
leverage line in the skill.

## Body (progressive disclosure)

- Keep `SKILL.md` thin: overview, when-to-use, core steps, hard rules. Push anything large into
  `reference/<shard>.md` loaded on demand. (Mirror this repo's own structure.)
- One job, ≤3 modules (P5). If it sprawls, split into a set (-> `batch.md`).

## Triggering description — two complementary methods

**A. The 6-lens manual pass (cheap, do always).** Rewrite the `description` through each lens, saving
each draft so the change is auditable:
1. *Gist* — would a stranger know what it does from this line alone?
2. *Name+desc pairing* — do the name and description reinforce, not repeat?
3. *False-positive / false-negative* — list 3 queries it SHOULD fire on and 3 it must NOT; does the
   wording separate them?
4. *Overfocus* — is it too narrow (misses real variants) or too broad (fires on everything)?
5. *Human-scan* — readable in one glance, no jargon wall.
6. *Every word earns its place* — cut anything that does not change when it fires.

**B. The official trigger-rate optimizer (rigorous, for flagship skills).** Delegate to Anthropic's
`skill-creator` `run_loop.py` (do not reimplement): it generates ~20 should / should-not-trigger
queries, splits **60% train / 40% held-out**, runs each query 3x for a reliable rate, proposes
improved descriptions from failures, and returns `best_description` **selected by held-out score**
(anti-overfit). Record the resulting held-out trigger rate — the gate (Step 5) needs it.

## Output

A SKILL.md whose description has a **measured** held-out trigger rate (method B) or at least a
documented 6-lens pass (method A), plus the should/should-not query set saved for regression use.
"It looks like a good description" is not acceptance — a number is.
