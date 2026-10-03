# Hand off to a supported iteration provider

After acceptance, supply self-evolve with the brief, candidate snapshot, frozen policy, evaluator
artifacts and remaining capability limits. Reuse its existing loop; do not build a second engine.

| Task | Evidence provider |
|---|---|
| Deterministic outputs | A: actual test/programmatic results |
| External source of truth | B: dated anchor verification |
| Subjective prose/judgment | C: scenario/rubric/human or heterogeneous-judge evidence, only if implemented and available |

Preflight the actual installed provider. A documented scenario-eval design is not an executable
provider; return unavailable when it is missing. No plan or fixture can substitute for measured
quality. Agent and judge work uses installed llmcall current policy and records actual backend
identity; aliases of the same family do not establish heterogeneity.

Keep evaluator expectations out of implementation prompts and freeze their hashes. Same-account
private paths are procedural separation; claim physical isolation only after testing read denial.
Resume by run ID with unchanged candidate/policy. Changes invalidate prior evidence and reset clean
review rounds. Preserve original worktree changes and require authorization already present in the
user request before installation, publication or other external actions.
