---
name: skill-smith
description: "Create or batch new skills with research, a guarded scaffold, and evidence-based acceptance. Use for new skills; route repairs to self-evolve."
---

# skill-smith

A skill is accepted after independent approval of its measured evidence. The evidence CLI validates
contracts and cannot award acceptance. Follow
`PHILOSOPHY.md`: research before design, require measured proof, and delegate existing engines.

## Route and collect the brief

- Improve an existing skill: use `self-evolve`; keep its missing capabilities visible.
- Find an existing skill: use `market-intel` and its ready-skills research.
- Create or batch new skills: collect task, audience, inputs, expected deliverables, platforms,
  configuration, existing alternatives and proof cases together. Infer answers already provided;
  ask only for missing decisions. See `reference/intake-delivery.md`.

## Workflow

| Step | Work | Resource |
|---|---|---|
| 0 | Research references, designs, anti-patterns and how usefulness is measured | `reference/research-first.md` |
| 1 | Check overlap, one job and single versus batch scope | `scripts/dedup_check.py`, `reference/batch.md` |
| 2 | Delegate generation through an available capability | `reference/generators.md` |
| 3 | Scaffold the guarded repo; use `--with-config` for user configuration | `scripts/scaffold_skill.py`, `reference/config-spec.md` |
| 4 | Draft instructions and measure held-out positive and negative triggering | `reference/triggering.md` |
| 5 | Validate evidence against a frozen independent policy and current candidate | `scripts/acceptance_gate.py`, `reference/acceptance-gate.md` |
| 6 | Hand off accepted evidence to a supported iteration provider | `reference/iterate-handoff.md` |
| 7 | Install or publish within authorization, then verify that layer | `reference/deploy.md` |

## Invariants

1. Research cannot be skipped. If the research capability is unavailable, report the gap and use
   an available equivalent explicitly; a generated outline is not research evidence.
2. G1 measured paired lift and G2 held-out triggering are mandatory. Missing, extrapolated,
   synthetic-only, unavailable and skipped evidence cannot produce acceptance. The gate validates
   external evaluator artifacts; it does not itself run models or discover improvements.
3. Use installed `llmcall` current policy for model and agent work. Do not pin a provider, model,
   timeout or fallback ladder. Record actual backend metadata for independence; two aliases of one
   backend are not heterogeneous judges.
4. Freeze the evaluator-owned policy and holdout before implementation. Keep exact holdout answers
   out of implementation prompts. A private path under the same account is procedural separation,
    not proven physical read isolation. Use a separate validation split for selection; only an
    untouched evaluator-owned final test supplies G2. Candidate or oracle changes invalidate prior review streaks.
5. Measure the whole installed library for G3/G4. Our descriptions are capped at 180 characters;
   use current observed host capacity and listing, not a historical machine snapshot. A required
   removal decision is BLOCKED, not a clean budget result. G3/G4 use the same user and active-plugin
   inventory; retain UNKNOWN and unresolved counts. Preserve disabled alternatives.
6. One job, at most three modules. G5 security, G6 local conformance and G7 focus are required.
   Declare configuration applicability in source `config.contract.json`; G8 follows
   `reference/config-spec.md`. Storage-only tools require E8 with E1-E7 not applicable;
   missing declarations stay unknown. G6b is required after
   publishing; local checks do not prove remote metadata or CI.
7. Public examples are generated synthetic fixtures. Real inputs, transcripts, prompts, results and
    reports, including the complete research brief, belong in a verified PRIVATE versioned companion.
    Public design rationale contains only reusable TOOL documentation and generated synthetic examples.
    Never fall back into the tool repo.
8. Scaffold tracked `.githooks` forwarders and pin both kits. Empty, wrong or incomplete submodules
   fail. Hooks use `.githooks`, never the potentially empty `guards/hooks` directory directly.
9. Use `scripts/bump_version.py` to align version surfaces. Verify the installed alias, resources and
   published tree separately from the current worktree.
10. Complete applicable documents under `reference/documentation.md`. Record `docs_impact` per
    affected behavior; freeze final implementation/docs/version bytes before evidence and independent
    review. Draft scaffolds and structural checks alone cannot establish document completion.

## Deliver and resume

Return the candidate diff, brief, frozen policy hash, manifest, per-gate results, unresolved gaps,
installation state and external-readiness matrix. A plan is not a measured result. Resume only the
failed or missing gates while candidate and policy are unchanged; changes require fresh evidence.
Include the reviewed document impact record. See `reference/intake-delivery.md` for the handoff
contract and `reference/documentation.md` for its documentation duties.

## Fleet checks

`scripts/fleet_check.py` checks junctions, local conformance, whole-library budget, DATA boundaries,
remote guard actions and every remote default-branch workflow. It does not repair repositories.
Scaffold metadata validation and remote action inspection require PyYAML; unavailable remote parsing is reported as unobserved.

Reports use the shared companion resolver and pinned Guards artifact admission before writing.
The path must have one declared owner, match the writer's artifact, remain unignored and have
committed PRIVATE storage. Source-contract and transport changes invalidate prior admission.
`--no-status` is console-only. `--offline` reports remote rows unobserved, never passed. Quote the
full verdict with its coverage fraction.

Remote identity checks support GitHub URLs and static SSH aliases proven by the local SSH config;
unsupported hosts and complex alias rules remain unknown. Git inspection failures remain visible
in inventory coverage. Trim worklists and backups use the same PRIVATE storage checks as reports.

An explicit `--workflow-policy` maps repository slugs to `skill`, `security-kit` or `style-kit` with
a reviewed reason for a non-skill role. Public security remains required for every role. A style
kit without its own security action remains a failure. CI distinguishes recorded execution from
zero-step/no-runner failure; that distinction alone does not identify the admission cause.

Load only the reference needed for the current step. Preserve user changes and use isolated
worktrees for repairs; this acceptance command does not authorize external actions.
