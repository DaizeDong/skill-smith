# skill-smith, Design Philosophy

skill-smith creates skills through research, guarded scaffolding and independent review of measured
evidence. Generated instructions can appear complete while failing to trigger or improve a task.
The design therefore addresses the problem and its evaluation before implementation, and requires
approval of the completed candidate and actual measurements before acceptance.

## P1, Research-first

Every creation task starts with research into existing implementations, relevant methods and
known failure modes. Claims about improvement require an explicit comparison with those references.
The research also identifies how task usefulness can be measured, supplying the evaluation design
for P2. Delegate this work to `market-intel`, with an available equivalent and an explicit capability
gap when needed. [research-first.md](skills/skill-smith/reference/research-first.md) defines Phase 0;
research remains required even when a generator can produce an immediate draft.

## P2, Evidence-based acceptance

Activation alone does not demonstrate task improvement. Acceptance requires measured lift against
a no-skill baseline, held-out triggering, whole-library budget and dedup checks, security review,
local conformance, focus, and applicable configuration evidence. This applies self-evolve's
verification requirement at creation time. Missing or failed gates remain explicit.

The [acceptance gate](skills/skill-smith/reference/acceptance-gate.md), `budget_check.py`,
`dedup_check.py` and `check_conformance.py` validate the required contracts. The evidence CLI never
grants acceptance: independent reviewers inspect actual evaluator results for the same completed
candidate. A hash protects artifact integrity but cannot authenticate a claimed measurement.

## P3, Delegate existing engines

Research, generation, evaluation, iteration and distribution have separate implementations:
`market-intel`, Skill_Seekers or the official skill-creator, agent-skills-eval or scenario-eval,
`self-evolve`, and `npx skills`. Select only capabilities that are implemented and available.
skill-smith owns their handoffs, acceptance contracts, repository conformance and batch budgeting.
It does not reimplement the skill-creator interview, trigger optimizer or self-evolve loop.

The Python API follows this division. Catalogs describe exact source observations, selection
preserves ambiguity, and descriptors bind source and resource bytes. Execution uses the installed
llmcall interface. The caller owns deployment and durable private state; an importable package or
ready descriptor does not establish runtime readiness.

## P4, Whole-library budget

The host has limited space for skill descriptions. Capacity must be observed on the current host
with its active library; descriptions omitted from the host's listing can prevent skill selection.
A batch must therefore fit valuable candidates within the shared budget, including skills outside
this repository. The batch manager ranks candidates by measured lift and explicitly identifies
candidates to defer, merge or remove.

`budget_check.py` checks the whole library, and [batch.md](skills/skill-smith/reference/batch.md)
defines the shared budget manager. A current captured listing establishes visibility; historical
capacity is advisory. A required removal decision remains BLOCKED with its projected cost until
resolved. It cannot be reported as a completed budget measurement.

## P5, One job per skill

Overlapping descriptions can select the wrong skill. One job and at most three modules keep
routing, proof cases and scope reviewable. Broader coverage comes from composing focused skills.
The focus gate and library-wide dedup check require an overlapping or oversized scope to be
revised or split before acceptance.

## P6, Apply the same standards to skill-smith

The builder must meet the same conformance and acceptance requirements as its outputs.
Self-hosting remains a roadmap goal, and skill-smith is a valid target for `self-evolve --self`;
provider availability and actual verification limits remain explicit.

The [documentation contract](skills/skill-smith/reference/documentation.md) requires useful
rationale, current instructions and preserved history. Update authoritative sections and link
detailed rules from entry documents. Documentation changes invalidate the candidate review;
structural checks and independent semantic review have separate responsibilities.

## P7, Explicit applicability and storage admission

Selecting DATA with an environment variable does not create a settings lifecycle.
`config.contract.json` declares repository kind and configuration ownership; missing declarations
remain unknown. Native schemas and initializers retain their identities. Blank-required rejection,
deterministic templates and configured synthetic switching require separate observations.

The source owns the [storage contract](storage.contract.json), and the private companion links to
it. PRIVATE storage determines where real data may live. Retention follows each artifact's consumer,
recovery needs and final-deliverable obligations: keep current runtime data and necessary evidence,
extract unique useful work once, then retire development copies when their dependencies are cleared.
The [storage checker](skills/skill-smith/reference/storage-contract.md) reports undeclared paths and
budgets before explicitly authorized removal.

Before writing, the producer needs a declared artifact, a committed PRIVATE repository, and an
admissible path under current ignore rules. Guards owns these shared checks; Smith adds its report
and retirement workflow. A changed contract or publication state invalidates a prior write receipt.

P1 and P2 take precedence over convenience: a faster workflow must still perform research and
satisfy the acceptance requirements.
