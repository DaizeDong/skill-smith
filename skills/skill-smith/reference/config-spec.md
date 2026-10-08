# Configuration standard, G8

A source that owns settings declares their lifecycle outside the public tool repository, such as resource
roots, account preferences or credential references. Shipping an initializer proves that a template
can be generated. Configured operation requires a separate, measured lifecycle.

## Eight required elements

| Element | Requirement |
|---|---|
| E1 Schema | Document field names, types, required values and synthetic examples in CONFIG.md or the README. |
| E2 Discovery | Document the primary configuration environment variable, supported aliases and fallback order. |
| E3 Initialization and doctor | Generate the template and name missing configuration precisely. An unconfigured doctor must not report READY. |
| E4 Deterministic templates | Two initializations produce the same nonempty template tree, without author-specific paths or secrets. |
| E5 Configured A/B switching | After required values are filled, the doctor resolves and validates each selected root. |
| E6 Private state and secrets | Required runtime records and configuration belong in a verified PRIVATE versioned companion. Selected credentials may be included in its documented PRIVATE backup; credentials never enter the public tool repository. |
| E7 Documentation | English and Chinese README sections explain initialization, required setup, discovery and switching. |
| E8 Storage contract | The main tool repository contains a valid `storage.contract.json` declaring each permitted companion artifact, its consumer or final deliverable, recovery procedure and explicit retention rule. |

Missing or failed elements prevent G8 conformance. Not executed is distinct from passed.
Functional behavior and live integrations require their own evidence beyond these eight elements.

## Schema, discovery and initialization

Document the existing native settings schema, its version field, supported entries and each field's purpose.
A registry filename or a particular version-key spelling is not required.
Name required resource roots and the credential references needed for the selected capability.
Public examples must be synthetic and reproducible by `tools/make_fixtures.py`.

The primary convention is `<SKILL>_CONFIG`, with `<SKILL>_CONFIG_DIR` as an alias. Use the shared
companion resolver for the supported sibling/default paths and document the actual precedence.
Do not maintain a second resolver that can silently choose another root. Missing optional read
configuration may be reported as uninitialized; required operations and writes must fail clearly.
There is no public-tool fallback for private runtime data.

Declare the inspected native initializer and doctor paths in `config.contract.json`. Python and
PowerShell entrypoints keep their own names and flags; no cosmetic registry or doctor replaces them.
The initializer creates a template. The doctor validates the selected capability and reports missing
fields or resources. Template/schema validity is not a claim of configured functional readiness.

A generated template must not embed the author's machine paths. After initialization, a field may
legitimately require a user-supplied absolute resource directory. Each configured root owns those
values; changing the selected root must change the resources actually used.

## Configuration lifecycle

Use inspected, generated synthetic fixtures for acceptance:

1. Initialize independent A and B companion roots and retain the template hashes.
2. Run the doctor while required values are blank; retain its precise NOT READY result.
3. Fill required fields and resources using the synthetic fixture generator. Preserve the setup
   recipe; do not copy the operator's current configuration into public tests.
4. Point the primary environment variable to A, then B. Each doctor must resolve and validate the
   selected root. An inherited product-specific override must not accidentally select another root.
5. Exercise the relevant skill function on both roots and retain distinct expected outputs. For
   example, two synthetic documentation roots should produce their own source-specific answers.

Never change an honest doctor to pass a blank field merely to satisfy a generic gate. If a selected
live capability needs credentials or a service that is unavailable, keep that capability unverified.

## Explicit applicability

Every source has a root `config.contract.json` with integer `schema_version: 1`, a
`repository_kind` of `skill`, `software` or `combined`, a `configuration` of `settings`,
`runtime-storage-only` or `none`, a nonempty `rationale`, and `documentation` listing existing
relative source documents. Repository kind controls presentation duties; configuration controls
G8 applicability. The declaration belongs to the source and must agree with its actual consumers.
Missing, unreadable or malformed declarations fail with UNKNOWN applicability and all eight rows.
A keyword in prose or the absence of a familiar initializer never establishes applicability.

For `settings`, the `settings` object declares:

| Field | Meaning |
|---|---|
| `schema_document` | Relative existing document describing native types and required values |
| `discovery_document` | Relative existing document naming the primary selection variable and aliases |
| `environment` | Primary uppercase environment variable selected in A/B probes |
| `aliases` | Array of distinct supported uppercase aliases; may be empty |
| `precedence` | Nonempty ordered array explaining the actual selection order |
| `required_fields` | Nonempty array of required native field paths for the selected capability |
| `initializer` | Object with relative `.py` or `.ps1` `path` and string-array `args`, containing exactly one `{output}` placeholder |
| `doctor` | Object with relative `.py` or `.ps1` `path` and string-array `args`; selects the root through the declared environment |

The scaffolder generates these declarations; its generic doctor still proves template structure
only, so capability-specific E3 and E5 remain incomplete. Pure storage tools declare
`runtime-storage-only`: E1-E7 are individually NOT_APPLICABLE and E8 is required. Smith uses this
profile because external callers own initialization of its supplied runtime inputs. A `none`
declaration means no settings or runtime-storage producer; any present storage contract is still
validated. Independent review checks these ownership claims against code and docs.

## Checker behavior

```bash
python scripts/check_config_conformance.py TOOL_REPO --no-run
python scripts/check_config_conformance.py TOOL_REPO --run-synthetic --config-a SYNTHETIC_ROOT/A --config-b SYNTHETIC_ROOT/B --synthetic-root SYNTHETIC_ROOT
```

Native initializers that require PRIVATE versioned storage also receive `--template-a` and
`--template-b`, naming two prepared ordinary Git repositories with committed empty histories and
no working files, plus `--synthetic-home` containing generated visibility receipts. All five
directories, including the configured A/B roots, must be distinct, nonoverlapping children of
`--synthetic-root` and separate from the source. Generate these repositories and receipts with the
reviewed test fixture recipe; the checker does not initialize Git, approve visibility, or relax
native write admission. PUBLIC and UNKNOWN controls must remain refused. Fixture HOME is retained
for native visibility discovery while inherited global Git configuration stays disabled.

The default and `--no-run` execute no initializer or doctor. Static E1/E2/E6/E7/E8 results check
declarations, referenced files and representative ignore behavior, not semantic completeness or
configured readiness. E3 reports whether native entrypoints exist but remains NOT_RUN until blank
required configuration is tested; E4/E5 remain NOT_RUN. Any failure exits 1; applicable unmeasured
requirements exit 2. All applicable measured checks passing exits 0 without asserting live readiness.

`--run-synthetic` is explicit authorization to execute previously inspected fixture-safe entrypoints.
Review the native scripts and fixture recipe first. This is not an OS sandbox: scripts must confine
their work to generated fixtures, and must not invoke live models, services, credentials or producers.
The runner clears inherited credentials, selection aliases and user config, uses a temporary or
explicit generated home, and bounds template snapshots to 1024 files and 8 MiB. Each subprocess
defaults to 30 seconds; inspected native setup may request `--subprocess-timeout` up to 300 seconds. Python
runs directly; PowerShell runs without profiles or interactive input. Missing interpreters fail visibly.

E4 compares two nonempty generated working trees byte for byte. Only an ordinary root `.git`
directory is excluded from these comparisons; linked and nested Git administration is refused.
The comparison does not establish Git metadata integrity. E3 runs the blank template doctor and
requires nonzero status, exact selected root, explicit NOT READY and a required-field diagnosis.
A generic TEMPLATE CONFORMS result remains unmeasured. E5 requires two distinct existing roots
inside the explicitly reviewed synthetic directory. Each doctor must select its exact root, report
READY with exit zero and leave configuration bytes unchanged. Missing A/B fixtures stay
`configuration_required`; the checker never fills settings from a real installation.

Native doctor output may be JSON with Boolean `ready` (or `status: ready/not_ready`) and one
absolute `resolved_root`, `config_root` or `config_dir`; redundant identical aliases are allowed,
while conflicting states or roots are
rejected. Existing text output may use one `RESOLVED: PATH` or `resolved via SOURCE -> PATH` line,
plus explicit `READY:` or `NOT READY:`. Exit zero or schema-valid output alone cannot prove readiness.
The blank-template probe is not exhaustive field or capability coverage; retain the native domain
validator tests and functional A/B journey evidence separately. Timeouts and inspection errors
retain complete rows and cannot become an applicability exemption.

## Storage and documentation

Keep `storage.contract.json` in the main tool repository so the permitted companion contents are
reviewable with their producers and consumers. It contains `schema_version: 1`, a nonempty `tool`
identity and a nonempty `artifacts` array. Each artifact requires these nonempty string fields:

- `artifact_id`: unique stable identifier.
- `path_pattern`: relative POSIX path or bounded glob inside the companion; no absolute paths,
  traversal, repository metadata or unrestricted catch-all patterns.
- `purpose`: why this artifact is necessary.
- `schema`: the applicable domain schema, including its version when relevant.
- `producer`: the operation allowed to create or update it.
- `consumer_or_final_deliverable`: the actual consumer or required final deliverable.
- `rebuild_or_restore`: the supported reconstruction or restoration procedure.

Each artifact also requires `retention_rule`, with a `class` of `core`, `rebuildable` or `retired`
and a nonempty `rule` naming the condition for keeping, replacing or retiring it. Optional
`max_bytes` values must be positive integers; they bound working-data bytes across the companion
or for one artifact, excluding Git metadata. Git administration size is reported separately.
Declare core structured runtime records plus the minimum necessary configuration, recovery
instructions and final deliverables. A PRIVATE repository does not make development history,
intermediate reports or obsolete snapshots necessary to retain.

Before each write, use the pinned Guards `authorize_artifact_write` API with the expected
artifact id. It separately proves PRIVATE versioned storage, exact ownership, permitted producer
and current ignore behavior. Undeclared or retired artifacts must not be written. Existing undeclared paths require review and are not
deleted by default. A retention class does not itself authorize deletion: verify that producers,
consumers and active recovery needs permit retirement before applying a reviewed removal plan.
The scaffold contract covers the generated configuration skeleton, per-tool templates and minimal
recovery files, with a 64 MiB working-data budget excluding Git metadata. Exceeding the budget is
reported; it does not authorize deletion. Review a different budget when the declared capability needs one.
Declare capability-specific artifacts before adding their writers.

E8 validates this declaration through the pinned Guards `storage_contract.validate_contract(repo)`
API; the Smith module is a thin adapter. It does not read
the companion, prove its visibility or execute the referenced domain schemas. Actual storage and
PRIVATE-repository checks remain separate from this static schema result.

The companion must be separate from the public tool repository. Version the declared required
artifacts in that PRIVATE companion; do not put them in an unversioned loose directory. Real credentials must
never enter the public tool repository. Generated `.gitignore` rules such as `secrets/*` and
`*.env` protect against accidental staging while retaining synthetic templates and a secrets README.
The operator may deliberately include selected credentials in a verified PRIVATE companion's
versioned backup, or back them up separately. Document that choice and its restore procedure in
the companion. Ignore rules do not prevent explicit tracking, and the generic doctor does not
verify tracked contents or remote visibility. Verify effective push destinations before storing
real credentials; committed credentials remain in history and must themselves be rotated.
Never echo secret values in reports.

`README.md` needs `## Config`; `README_CN.md` needs `## 配置`. Each section links the schema,
names the environment variable and fallback order, and shows `init -> fill required values -> doctor`
plus switching instructions. The scaffolder's `--with-config` option emits a starting template for
these files. The skill author must implement and verify capability-specific readiness before G8
and the broader acceptance process can be completed.
