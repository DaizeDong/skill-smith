# Step 0 — Research-first (MANDATORY, the P1 承重墙)

**Why this is step zero:** "industry-leading" and "tested-real" are claims about the field. You
cannot make them by guessing from priors — you must look at the field first. Skipping this produces a
median skill dressed up as a leading one. This step is a hard invariant, not an optimization.

## What to do

Delegate a broad recon to **market-intel** (it is the research engine; do not re-implement it):

> Invoke market-intel at **deep** (or **exhaustive** for a flagship skill) scale with a query like:
> "调研 `<the skill's domain/task>` 的最佳实现/参考 skill、前沿设计与方法、competing tools、已知
> anti-patterns 与失败模式,以及业界如何证明这类工具真的可用(eval 方式)。"

market-intel will route across the domains that matter here:
- **`ready-skills`** — existing skills/plugins that already do this (match-or-beat targets).
- **`mcp-ecosystem`** (its Discovery meta-domain) + GitHub — tools/repos in the space.
- **`frontier-research`** — papers / SOTA methods to borrow for genuine innovation.
- **`x-twitter` / `reddit-community` (HN/Reddit)** — practitioner discourse: what works, what burns.

If market-intel is **not installed/connected**, fall back to the built-in `deep-research` harness and
**state the degradation explicitly** (P-no-silent-degradation). Never skip recon.

## What to extract (the deliverable of Step 0 = a one-page Design Brief)

Produce a short brief that the rest of the pipeline consumes:

1. **Best references (match-or-beat):** the 1–3 strongest existing implementations + what makes them
   good + their concrete weakness you can exceed.
2. **Frontier ideas to incorporate:** specific design/method ideas worth borrowing (this is where
   *innovation* enters — you are standing on the surveyed state of the art, then adding).
3. **Anti-patterns to avoid:** documented failure modes (e.g. from this ecosystem: ~50% non-trigger,
   token-budget truncation, faith-based "it triggered != it worked", skill sprawl, prompt-injection
   surface). Each becomes a thing the design must defend against.
4. **The proof bar:** how the best ones demonstrate they work -> this defines the eval signal the
   acceptance gate (Step 5) and self-evolve (Step 6) will use. "tested-real" starts here.
5. **Scope & focus decision:** confirm one-job framing; if the brief reveals 2+ jobs, plan a *set* of
   focused skills (-> batch, Step 7), not one fat skill.

## Output contract

The brief must explicitly answer: *what is the current best, what will we do better/new, what will we
NOT do, and how will we prove it works?* If you cannot answer the last one, you are not ready to
scaffold — loop the recon. This brief is attached to the skill's repo (e.g. `docs/design-brief.md`)
so the design rationale is auditable.
