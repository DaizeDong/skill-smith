# Step 0, Research-first

Research is required before design. Comparisons with existing work need current references,
documented limitations and a measurable improvement target. This step supplies the design brief
and evaluation basis required by P1 and P2 in [PHILOSOPHY.md](../../../PHILOSOPHY.md).

## Research scope

Delegate research to `market-intel` at **deep** scale, or **exhaustive** for a flagship skill.
Cover reference implementations, relevant methods, competing tools, known failure modes and
how the field evaluates usefulness. The relevant domains are:

- `ready-skills`: existing skills and plugins as comparison targets.
- `mcp-ecosystem` in Discovery, plus GitHub: related tools and repositories.
- `frontier-research`: papers and methods that can inform the design.
- `x-twitter` and `reddit-community` (HN/Reddit): practitioner observations and reported failures.

If `market-intel` is unavailable or disconnected, use the available `deep-research` harness and
report the capability change explicitly. Research remains required; an unavailable fallback
must remain a gap.

## Design brief

Produce a one-page brief for the rest of the workflow:

1. **Reference implementations:** the strongest 1 to 3 alternatives, their useful properties and
   concrete weaknesses the proposed skill could address.
2. **Relevant methods:** specific surveyed designs or methods to reuse or extend, with their sources.
3. **Failure modes:** documented risks and the design requirements they imply. Existing guidance
   includes a reported ~50% non-trigger rate, token-budget truncation, activation without task
   improvement, overlapping scope and prompt-injection exposure. Record the source and context of
   each observation; do not use an uncited rate as a measured result for the new candidate.
4. **Evaluation:** the baseline, signal and proof cases for acceptance (Step 5) and iteration (Step 6).
5. **Scope:** one job per skill. If the brief identifies 2+ jobs, plan a focused set under
   [batch.md](batch.md).

## Output contract

The brief identifies the current alternatives, intended improvement, excluded scope and how the
improvement will be measured. Resolve a missing evaluation method before scaffolding.
Store the complete real brief under `research/` in the verified PRIVATE versioned DATA directory
resolved by the consuming skill's guard resolver. Include its private artifact reference in the
implementation handoff. Missing private storage requires initialization; no public-tree fallback
is allowed.

The scaffold's `docs/design-rationale.md` holds reusable public TOOL documentation: behavior,
public interfaces, limitations and generated synthetic examples. Keep real briefs, user scope
decisions, prompts, observations and private artifact paths in PRIVATE DATA. Update the existing
rationale section when the design changes, following [documentation.md](documentation.md).
