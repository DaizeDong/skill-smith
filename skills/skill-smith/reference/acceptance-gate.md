# Evidence contracts and independent acceptance

The gate reads results produced by existing evaluators. It never launches a provider, sends a
message or substitutes a fixture for live measurement. It validates the supplied contract and always
leaves `accepted: false`; independent reviewers approve actual evaluator results. General model and agent work uses installed
`llmcall` and inherits its current policy.

| Gate | Required evidence |
|---|---|
| G1 | At least three distinct paired proof tasks; finite scores in [0,1]; positive mean lift meeting the frozen minimum |
| G2 | Frozen held-out query IDs/content hashes and labels; no training overlap; both positive activation and negative rejection rates meet a threshold of at least 0.9 |
| G3 | Current whole-library prompt budget result, not historical capacity |
| G4 | Current overlap/dedup result across user skills and active plugins, with no unresolved inventory |
| G5 | Independent security review and relevant scans |
| G6 | Local Spec-v1 conformance on this candidate |
| G7 | Review of one job and at most three modules against the brief |
| G8 | Configuration standard; only an independently documented not-applicable decision can exclude it |
| G6b | Remote conformance after publication; required by the published stage |

## Prepare once

G3 and G4 share `--skills-dir` and `--installed-plugins` inputs. Both read the active install paths
from the manifest and retain missing, unreadable or conflicting entries as `UNKNOWN`. G3 prints
`BUDGET: ... unresolved=N`; G4 prints `DEDUP: ... unresolved=N`. Known overflow and overlap findings
keep their failure status even when coverage is incomplete. An empty plugin set must be an explicit
manifest with `plugins: {}`, not a missing file. These measurements do not authorize trimming or
uninstalling anything.

The evaluator owns a private policy JSON with `schema: 1`, a `brief` containing task, inputs,
deliverables, platforms and at least three distinct `proof_tasks` IDs, plus `proof_task_sha256` mapping every task ID to its frozen input hash. It also contains `min_lift`
(default 0, but measured lift must be positive), `trigger_threshold` (default/minimum 0.9), `queries`
(each with id, query_sha256 and boolean expected), and `training_query_sha256`. Each held-out query
appears once in the canonical result. An evaluator with repeated trials must preserve its raw
trials and declare its aggregation before freezing the policy.

The only supported exclusion is `not_applicable: ["G8"]`, together with a nonempty
`config_not_applicable_reason`. An exclusion is an evaluator-owned applicability decision; the
implementation agent cannot lower thresholds or introduce exclusions to clear failures.

Freeze the policy hash before implementation and retain it independently of the manifest. Store
policy, raw observations and results in the verified PRIVATE versioned companion. Paths in a
shared-account filesystem are not physically unreadable; hash integrity is not isolation.

## Run against the exact candidate

From the skill-smith repository:

```bash
python skills/skill-smith/scripts/acceptance_gate.py --repo TARGET_REPO --snapshot
python skills/skill-smith/scripts/acceptance_gate.py --repo TARGET_REPO --manifest PRIVATE_MANIFEST --policy PRIVATE_POLICY --policy-sha256 FROZEN_SHA256
```

Add `--stage published` after publication to require G6b. Version-2 snapshot hashes cover tracked,
deleted and untracked non-ignored file bytes and kinds, index modes, executable bits where the OS
exposes them, submodule gitlinks, checked-out revisions and their inspected working trees. They describe the current working tree,
not a claim about HEAD or installed content. Keep base HEAD and installed source identity in the
handoff too.

The manifest is a JSON object with `schema: 1`, `candidate_sha256`, `policy_sha256`, and `gates`.
Each gate maps to an artifact reference with a relative `path` and `sha256`. Artifact paths must
remain inside the manifest directory. The independently supplied policy pin must match the file;
the manifest cannot choose its own policy hash.

Every artifact, including G1/G2, carries its `gate` ID, `status: "passed"`, integer `exit_code: 0`,
schema, candidate/policy hashes, `measurement: "measured"`, and provenance:
`evaluator`, `request_id`, `backend`, and boolean `fixture`. The actual evaluator/backend identity
must be reported; route names alone do not prove heterogeneous judges.

G1 adds `pairs`, with one record per frozen task ID, matching `input_sha256`, and `without_skill`/`with_skill` scores. G2 adds
`held_out: true` and `trials`, each with the frozen id/query_sha256/expected plus boolean `triggered`.
The gate recomputes lift and both trigger rates rather than trusting a supplied aggregate score.
All records attest to external checks; retain their raw logs for independent review. Hashing a claimed
pass does not authenticate that the check actually ran.

The public `tools/make_fixtures.py` generator creates test bundles with `fixture: true`. They may
produce `contract_valid: true`, but always `accepted: false`, `verdict: "synthetic_only"`, exit 1.
They are examples of format and gate behavior, never evidence of real skill effectiveness.

## Result and resume

The command prints JSON. Valid synthetic evidence yields `synthetic_only`; valid non-fixture
attestations yield `independent_review_required`. Both have `contract_valid: true`, `accepted: false`
and exit 1. Relabeling fixture provenance cannot grant acceptance. Independent reviewers must inspect
the actual evaluator results and approve the frozen candidate outside this contract checker.
Missing, malformed, stale, extrapolated, skipped, failed or unavailable results also exit nonzero, with
per-gate reasons and `resume_gates`. Retain the JSON in the private evidence bundle.

Resume failed/missing gates with existing evaluators. Do not resend successful external actions.
A changed candidate or policy invalidates evidence tied to the old hash. Two independent clean
review rounds must bind the same candidate, policy and raw results; any change resets the streak.
The command checks evidence integrity and numeric contracts, not real-world truth or universal
absence of defects. Installation, external readiness and publication need their own actual proof.
