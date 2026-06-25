# Step 6 — Hand off to self-evolve (auto-iteration, don't reimplement)

Once a skill is **accepted** (Step 5), ongoing improvement is `self-evolve`'s job — it is the
anti-self-deception iteration engine ("被采纳 = 真改进", regression-gated, sandboxed). skill-smith does
NOT build its own loop; it sets self-evolve up correctly and gets out of the way.

## Choose the signal provider (self-evolve's A/B/C)

The Step-0 brief's "proof bar" tells you where the eval signal comes from. Map it to a provider:

| Skill type | Provider | Signal |
|---|---|---|
| Has deterministic outputs (code/format/parse) | **A** | `pytest` / programmatic adjudication |
| Grounded in an external source of truth (filings, prices, APIs) | **B** | anchor verification (e.g. EDGAR) |
| Subjective / judgment / prose | **C** | scenario-eval (scenarios + rubric + heterogeneous judges) |

`scenario-eval` is the universal load-bearing fallback — **there is no un-evolvable skill** (this is
self-evolve's correction to the early "markdown skill can't be tested" mistake). Even a pure-prose
skill gets a C-provider eval.

## Set it up

1. Freeze the eval signal once (the should/should-not query set from Step 4 + the brief's proof tasks
   become the frozen eval; hold-out stays physically unreadable).
2. Point self-evolve at the accepted skill repo; it runs reflect -> propose -> evaluate -> judge ->
   accept inside a git worktree sandbox, promoting only changes that improve held-out **without
   regression**.
3. Keep the default **dual codex&claude cross-check** on for high-stakes edits (heterogeneous judges).
4. In-sandbox is fully automatic; **out of the sandbox goes to human review** (self-evolve invariant).

## Why the seam matters

skill-smith's gate (Step 5) proves the skill is good *at creation*; self-evolve keeps it good *over
time* as the world drifts. Same anti-self-deception spine, two moments. Do not collapse them into a
home-grown loop — reuse self-evolve so the safety guarantees come for free.
