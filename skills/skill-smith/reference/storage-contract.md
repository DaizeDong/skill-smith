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

Artifact persistence defaults to `versioned`: a writer must refuse a Git-ignored path, including
an absent future file. A source may explicitly declare `persistence: transient` with a nonempty
`transient_reason` for an output that can be ignored. That choice requires reviewed operational
reasoning; a rebuildable retention class alone does not permit ignoring required history.
Retired artifacts cannot receive new writes under either persistence mode.

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

## Runtime discovery and outputs

`guards/tools/datadir.py` selects the first existing supported DATA candidate in this order:
`SKILL_SMITH_DATA_DIR`, `SKILL_SMITH_CONFIG`, `SKILL_SMITH_CONFIG_DIR`, a proven sibling companion,
`~/.skill-smith-config`, then `~/.skill-smith-data`. Companion-root candidates try `data/` first.
Writers require the declared layout: `data/fleet-check-status.json`, `data/worklist.json`
and `data/description-backups/`. Clear an inherited DATA_DIR override when switching CONFIG.
Unsupported root fallbacks and alternate output paths fail artifact admission, including explicit
`--status-json`, `--out` and `--backup-dir` destinations.

Before writing, refresh `~/.pii-guard/visibility.json` with the trusted collector. Its `_refreshed`
timestamp and every physical/effective fetch and push destination must be current and PRIVATE,
including URL rewrites, SSH aliases and additional push URLs. `gh repo view` does not refresh this
receipt; `.companion` establishes ownership only. Unsupported or unresolved routing fails. See
[Guards companion verification](../../../guards/COMPANION.md#verifying-a-companion) and the write
admission requirements below. Commit and push run data in the private companion. Restore by cloning
that companion, setting CONFIG, refreshing visibility proof and checking resolved paths before resuming.

`fleet_check.py --print-status-path` prints the default path selected by the report writer's
resolver. It does not inspect the fleet, create files or prove write readiness.
`fleet_check.py --no-status` is console-only and needs no report destination.
`trim_descriptions.py --scan` creates a private review worklist without changing descriptions;
apply requires reviewed authorization and PyYAML frontmatter validation.

[config.contract.json](../../../config.contract.json) declares Smith as runtime-storage-only:
G8 validates E8, with E1-E7 not applicable. Profile Sync and operators initialize the four external
input documents in [Shared runtime configuration inputs](#shared-runtime-configuration-inputs).
Smith does not create a settings registry. Static G8 conformance does not establish runtime storage
readiness.

## Shared CLI

Smith keeps only the current reviewed retirement plan under the private companion's
`data/retirement-plans/`. This transient family has a 16 MiB bound, including atomic
replacement files. It is separate from the 24 MiB maintenance bound: 3 MiB for
top-level core reports and staging files, and 21 MiB for nested historical artifacts
in a retirement transition. The existing maintenance writer ID covers top-level
paths; nested history rejects new writes. Immediate directory shells remain core.
Create batches that fit both the current plan and its replacement; preserve a
failed or interrupted plan until the remaining targets have been reconciled.
After a successful batch, keep counts, selection and plan digests in the compact
maintenance result and remove the completed transaction. The source contract
permits this transient family to be ignored by Git; final results remain versioned.

A complete target-to-anchor index required to recover deduplicated files is a core
maintenance deliverable. Retain the full index and its required anchors while the
recorded recovery obligation remains open. A digest or a repeated inventory cannot
replace the mapping.

Recovery-index v1 is gzip-compressed UTF-8 JSON with `schema_version: 1`, an `anchors`
array and a `targets` array. Each anchor is
`[group, retain_relative_posix_path, bytes, lowercase_sha256]`. Each target is
`[group, target_relative_posix_path, zero_based_anchor_index]`.

Paths follow the contract's canonical relative-path rules within the receipt-bound
namespace for their group. Each target appears exactly once and references a valid
index in the complete `anchors` array. Target and anchor groups must match; retained
anchors must be outside the deletion set. Each target must have been verified
byte-identical to its anchor before removal.

The companion receipt records SHA256 over the exact gzip bytes and exact decompressed
UTF-8 bytes, source identity and revision, group-to-namespace bindings, and anchor and
target counts. Verify and version the complete core index before removing its transient
plan copy. The existing core budget includes atomic staging space.

This format preserves necessary file-content recovery relationships. It does not admit
runtime logs or establish restoration of unrecorded filesystem metadata.

Protected paths retain prior policy refusals, unreviewed material, required recovery
and failure evidence, and temporary files. Changing a retention class does not
authorize deletion or override a prior refusal; each concrete selection still needs
its own review and current admission.

Pure contract validation, path matching and write admission live in the pinned Guards module
`guards/tools/storage_contract.py`. Smith's adapter reexports those primitives and owns the
inventory and reviewed-retirement CLI. Run that CLI from the canonical source checkout:

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

Runtime producers call `authorize_artifact_write(source_root, companion_root, relative_path,
artifact_id=EXPECTED_ID)` from the pinned Guards module immediately before each write. It requires
one declared owner, a matching producer artifact, a committed Git HEAD, current PRIVATE proof,
ordinary physical paths and admissible ignore rules. The immutable result binds the path, artifact,
contract hash and publication proof. Recheck before writes; no receipt locks the filesystem.
Directory admission covers only that directory, so authorize concrete leaves before creating
structural parents. Inventory transport checks are separate and never grant write permission.

Smith binds report JSON to `fleet-status`, exact atomic staging to `fleet-status-staging`, trim
worklists to `worklist`, and rollback leaves to `description-rollback`. Explicit output flags still
must match these source declarations. The contract and transport signature must stay unchanged
between admission and writing. An ignored staging path is refused, even if the final report path
would otherwise pass.

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

Superseded imported fleet observations are also temporary maintenance inputs.
Keep them while a specific review or rollback obligation remains unresolved;
retire them after the current report preserves the needed conclusion. A historical
observation is never a current fleet verdict. Private preservation receipts carry
the exact recovery location instead of embedding machine-specific archive labels
in the source contract.

## Legacy generated scratch

The retired scratch entries identify seven narrow regression namespaces at the
companion root and exact generated-input workspaces at the root and under `data/`.
They describe historical producer locations; they do not authorize future writes.
Unmatched names remain undeclared. Only `is40-*` children are covered inside
`.test-tmp`; other children still require an explicit declaration and review.

Recorded fixture hashes establish provenance for the inputs they name. They do
not establish that every file beneath the same workspace is generated or unused.
Before planning removal, prove the lineage of the selected files, retain useful
unique code and needed real data outside the group, and resolve current acceptance,
reference and rollback obligations. Pending obligations prohibit apply. Confirm
that readers and writers are inactive and that no surviving Git administration or
link depends on the selected paths. A namespace match, old activity observation or
successful contract validation does not satisfy those checks.

The bounded declaration review uses located producer scripts, recorded input
receipts and shallow directory metadata. It does not claim a full current tree
inventory, source-copy comparison or reference closure. Unreviewed scratch remains
an explicit gap; broaden neither `core` retention nor retired patterns to hide it.

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
