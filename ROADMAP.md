# Roadmap

Current: **v0.2.0**

The plugin manifest defines the release version. [CHANGELOG.md](CHANGELOG.md) records released
changes and later Unreleased work; the current checkout does not imply another release or
production readiness.

## v0.2.0 (current)

- Research-first creation uses a concise SKILL entry, step-specific references and a deterministic
  Spec-v1 scaffolder. The scaffold pins Guards and Style, installs fail-closed hooks, and assigns
  the required documents. It produces a draft, not an accepted skill.
- Local conformance delegates documentation structure to the pinned Style checker. The dash
  workflow uses `./style/ci/dash-guard`; its scanner checks Markdown and Python comments without
  changing string literals or ASCII hyphens. SKILL and referenced-resource checks remain separate.
- Remote metadata tooling sets base-9 plus domain topics, description and homepage, and G6b checks
  the live repository after publication. Missing authentication or connectivity remains SKIP.
- G8 reads an explicit configuration applicability contract and preserves native lifecycle paths.
  Static declarations, blank-required rejection, deterministic templates and configured doctor
  evidence are separate. Smith declares runtime-storage-only applicability; external operators
  own initialization of its supplied configuration inputs.
- Report and trim writers use the pinned Guards artifact admission API. PRIVATE transport,
  committed storage, ownership, producer identity, ignore rules and source-contract freshness
  are checked before writes. Synthetic tests do not establish live fleet readiness.
- The Python package provides schema 1 source catalogs, exact selection, validated overlays and
  llmcall adapters. Synthetic contract and wheel checks are separate from live loader,
  provider-permission and deployment acceptance.
- The evidence CLI validates G1 paired scores, G2 held-out trials and required policy/candidate-bound
  artifacts. It reports contract-only verdicts and never grants acceptance.
- Evaluator policy and holdout freeze before implementation. Completed implementation, documentation
  and version metadata freeze before candidate-bound evidence and independent review.
- Library budget, dedup, private transport and remote workflow checks retain missing or unobserved
  states. Installed provider readiness, semantic accuracy and usefulness need their own evidence.
- Release preparation aligns version surfaces and refuses placeholders, invalid dates and
  non-advancing versions. It updates the existing current-version heading without adding ROADMAP
  sections or changing their prose. Current guidance is maintained in its authoritative sections;
  release history remains in CHANGELOG.

## Planned

- Verify reviewed retirement on large obsolete artifact groups while retaining
  compact final conclusions. Keep partial completion explicit and remove finished
  transaction plans after their receipts are saved.

### v0.2 follow-up, evaluator integration

- Integrate external measurements with the implemented contract validation, selecting only
  installed providers and preserving unavailable status.
- Keep final held-out triggering evaluation separate from selection and optimization.
- Expand measured provider readiness while retaining independent acceptance review.

### v0.3, self-evolve handoff

- Automate `iterate-handoff` to an accepted skill using the pytest, anchor or available
  scenario-eval provider, with regression-gated acceptance.

### v0.4, batch / series

- Implement the `batch.md` workflow fan-out and global library-budget manager, ranking candidates
  by measured lift and explicitly resolving over-budget candidates.

### v0.5, self-host

- Scaffold skill-smith with skill-smith and evolve it with `self-evolve --self`.

### Later

- Generation-backend adapters for Skill_Seekers, the official skill-creator interview and git history.
- Externalize templates from `scaffold_skill.py` into `assets/templates/`.
