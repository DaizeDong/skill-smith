# Source-owned storage contract

The source checkout is the deployable tool. Its root `storage.contract.json` is the
authority for companion paths. The companion README links here and to that file;
it does not duplicate the philosophy or maintain another policy.

Private storage answers where real data may live. It does not justify keeping
every output forever. Retain structured runtime data, necessary configuration and
recovery dependencies, and requested final deliverables. Extract useful unique
code or a result once, then retire its development group. Do not create another
archive of the same history.

## Contract format

Version 1 has `schema_version`, `tool`, `artifacts`, and an optional positive
`max_bytes` working-data budget, excluding Git administration. Each artifact declares `artifact_id`, `path_pattern`, `purpose`,
`schema`, `producer`, `consumer_or_final_deliverable`, `retention_rule` and
`rebuild_or_restore`. All fields except `retention_rule` are nonempty strings.
Retention has `class` (`core`, `rebuildable` or `retired`) and a concrete `rule`.
An artifact may also set a positive `max_bytes`. Set budgets for directories whose
writers could otherwise accumulate unlimited results. Exceeding a budget fails
inspection; it never grants deletion permission. `check` reports local `.git` bytes
separately. An external gitfile is reported without traversing its external admin
directory, so that row is not a complete repository-history size measurement.

Paths are relative to the companion repository root, use `/`, and reject traversal,
absolute paths and Windows aliases. `*` matches one path segment; `**` matches zero
or more segments. A root catch-all is forbidden. Files matching no artifact or
multiple artifacts are failures. `protected_paths` optionally identifies active or
recovery paths that must never be retired by this checker.

`schema` names the existing domain schema or manifest. The shared inventory checks
the contract structure, path coverage and sizes; it does not claim to validate
private file contents. Keep domain-specific checkers and stronger manifests in
place. Reference them instead of reproducing their schemas here.

The default layout is `separate_companion`. A private repository that deliberately
contains both source code and backups can declare `layout: combined_private_repo`
and a nonempty `data_roots` list of exact relative files or directories. That
exception requires the source and companion to be the same PRIVATE worktree.
PUBLIC and UNKNOWN still fail. Roots cannot overlap, contain globs or escape the
repository, and every artifact pattern must stay within a declared root.

For the combined layout, the checker inventories only those data roots and reports
root-level excluded source metadata separately without descending into it. Absent
data roots are listed as missing, which is normal after an allowed cleanup;
inaccessible paths and links in any existing ancestor are errors. The `bytes` and
`artifact_scope_bytes` fields measure the declared data scope. Whole-worktree size
is not claimed when source trees are excluded. Plans cannot retire anything
outside the declared data roots.

## Shared CLI

Run the single implementation from the canonical skill-smith source checkout:

```bash
python skills/skill-smith/scripts/storage_contract.py validate --repo SOURCE
python skills/skill-smith/scripts/storage_contract.py check --repo SOURCE --companion PRIVATE_COMPANION --json
python skills/skill-smith/scripts/storage_contract.py plan --repo SOURCE --companion PRIVATE_COMPANION --path cache/obsolete --reason "Selected result supersedes this cache" --inactive-evidence "Writer stopped and current references checked"
python skills/skill-smith/scripts/storage_contract.py apply --repo SOURCE --companion PRIVATE_COMPANION --plan PRIVATE_PLAN --approve-sha256 REVIEWED_PLAN_SHA256
```

All commands emit JSON. `check` is read-only. Exit 0 means the requested operation
passed; exit 1 means a failed or unobserved requirement. PRIVATE admission always uses
the shared checker's own pinned Guards proof and resolver, including for targets
that do not ship Guards. The resolver is explicitly bound to the target source
for companion discovery. There is no target/shared fallback. Unknown/public/unversioned
destinations fail. Inventory reports links without descending into them.

Save a plan only in a verified private location. Review its concrete paths,
reason, inactivity evidence and byte snapshots, then authorize its exact file
SHA256. Inactivity is an explicit operator assertion, not inferred from directory
age. Do not approve an unknown or active writer. Apply verifies current PRIVATE
identity, the contract and file hashes again. It rejects core/undeclared/ambiguous
items, active markers, protected paths, links, junctions and nested repositories.
Windows removal uses PowerShell `Remove-Item -LiteralPath` on individual leaves,
never recursive traversal. A mid-operation failure is visible and can leave a
partially removed disposable group; prepare a fresh plan after inspecting it.

The skill-smith companion has a 64 MiB working-data budget. The retired campaign is a temporary
classification for removal after dependency clearance, not an allowed future
output location. Old rounds, copied source trees and test workspaces are not core
DATA. Git history alone does not extend their retention period.

## Shared runtime configuration inputs

These four exact paths are operator-maintained private configuration inputs.
Keep them as `core` while configured consumers reference them; consumers read
these documents without initializing policy or guessing private bindings.

| Companion path | Existing schema and consumer |
|---|---|
| `data/runtime-selection.json` | Schema-version 1 entries with unique ids and exact selectors; optional task/format/requirement lists and tier; Profile Sync passes policy to Smith validation and selection. |
| `data/runtime-capabilities.json` | Capability observations with nonempty status and optional evidence list; Profile Sync passes observations to Smith validation and requirement checks. |
| `data/overlay-resource-roots.json` | Nonempty source-id to nonempty resource-root string map; the Profile Sync overlay bridge supplies reviewed bindings to Smith overlay construction. |
| `data/role-equivalence.json` | Nonempty receipt keys with status, artifact hash and evidence list; the overlay bridge validates shape and compares exact artifact receipts. |

Profile Sync supplies these through `--runtime-policy`, `--capability-snapshot`,
`--overlay-resource-roots` and `--role-equivalence`. Preserve explicit empty maps
while the configured file arguments reference them. Empty maps do not certify
resource bindings or role equivalence.

Selection task/format/requirement lists may be omitted or empty; tier defaults
to `main`. Capability evidence may be omitted or empty. Evidence items, when
present, are nonempty strings; Smith requires `supported` and nonempty evidence
before treating a requirement as supported. Role receipt hashes and evidence
may be empty, but retirement requires a ready descriptor, exact artifact hash,
`verified` status and nonempty evidence.

Keep current approved policy, bindings and useful observations. Review dated
capability evidence before use; continued reading does not make it current.
Reconcile consumers before removing superseded entries; replace old configuration
without copied history. Restore a reviewed PRIVATE revision or fresh evidence.
Consumers do not guess missing selectors, resource roots or equivalence; unresolved
support and incomplete receipts remain unverified.
