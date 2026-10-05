# Configuration standard, G8

A configuration-bearing skill needs settings outside the public tool repository, such as resource
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

Document `registry.json` and its `schema_version`, the supported entries and each field's purpose.
Name required resource roots and the credential references needed for the selected capability.
Public examples must be synthetic and reproducible by `tools/make_fixtures.py`.

The primary convention is `<SKILL>_CONFIG`, with `<SKILL>_CONFIG_DIR` as an alias. Use the shared
companion resolver for the supported sibling/default paths and document the actual precedence.
Do not maintain a second resolver that can silently choose another root. Missing optional read
configuration may be reported as uninitialized; required operations and writes must fail clearly.
There is no public-tool fallback for private runtime data.

Ship `scripts/init_config.py` and `scripts/verify_config.py` or the documented hyphenated equivalents.
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

## Checker behavior

```bash
python scripts/check_config_conformance.py TOOL_REPO --no-run
python scripts/check_config_conformance.py TOOL_REPO --config-a SYNTHETIC_CONFIG_A --config-b SYNTHETIC_CONFIG_B
```

`--no-run` retains all eight rows. E4 and E5 are `static_not_executed`; an otherwise clean result is
INCOMPLETE, exit 2. Without configured A/B roots, E4 can pass but E5 remains
`configuration_required`, also exit 2. A failure exits 1. All eight passing elements exit 0.
Non-configuration-bearing skills are explicitly not applicable, without claiming readiness.
When a tool has `storage.contract.json` but no settings-configuration signals, the checker validates
E8 and marks E1-E7 `NOT_APPLICABLE`. This supports runtime-data tools without requiring an invented
settings schema or initialization doctor. A valid storage-only declaration exits 0; an invalid one
exits 1. For configuration-bearing tools, a missing or invalid contract fails E8.

E4 runs the target initializer twice in temporary directories and compares the generated bytes.
E5 runs the target doctor against supplied, distinct existing configuration directories. The checker
does not fill required values or infer functional success from the doctor; retain the lifecycle and
function evidence separately. Inspect the target initializer and doctor before authorizing their
execution. Use synthetic setup appropriate to those scripts and the selected capability.

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

Undeclared artifacts must not be written. Existing undeclared paths require review and are not
deleted by default. A retention class does not itself authorize deletion: verify that producers,
consumers and active recovery needs permit retirement before applying a reviewed removal plan.
The scaffold contract covers the generated configuration skeleton, per-tool templates and minimal
recovery files, with a 64 MiB working-data budget excluding Git metadata. Exceeding the budget is
reported; it does not authorize deletion. Review a different budget when the declared capability needs one.
Declare capability-specific artifacts before adding their writers.

E8 validates this declaration through `storage_contract.validate_contract(repo)`. It does not read
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
