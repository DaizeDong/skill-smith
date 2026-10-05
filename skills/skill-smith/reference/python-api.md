# Python catalog and runtime adapter API

The `skill_smith` package provides a shared catalog, exact source selection and
validated runtime descriptors. It is built from `skills/skill-smith/scripts/skill_smith`
by the root `pyproject.toml`. The package version follows the plugin manifest.
`bump_version.py` updates the five skill release surfaces; package release
preparation must also set `project.version` in `pyproject.toml` to the same value.
The wheel CI rejects a mismatch.

## Build and dependencies

Use Python 3.10+ and a reviewed distribution of the declared `fleet-guards`
dependency. Build a wheel with:

```bash
python -m pip wheel --no-deps --wheel-dir OUTPUT_DIRECTORY .
```

`--no-deps` limits that build command to this package; it does not establish that
the caller's runtime dependencies are installed. Install the resulting wheel
with pip and supply the reviewed dependency wheels through `--find-links` when
they are not available from the configured package index.

Filesystem discovery, selection and descriptor validation use the standard
library. Optional execution and native discovery use the installed `llmcall`
interface. The `runtime` extra declares `llmcall>=0.2.0`; install `.[runtime]` from
reviewed sources when these APIs are needed. The selected llmcall distribution
must provide `ExecutionRequirements`, `ModelSelection` and its process context
API. A version number alone does not establish those interfaces; clients missing
them raise `ValueError` with `llmcall_contract_unavailable` before execution or
workflow construction. Explicit test clients may supply their own inert `process`
context. Native acquisition additionally requires llmcall's Windows Job owner. Missing
capabilities remain explicit failures. No provider routing or model is selected
by this package's installation metadata.

## Catalog and selection

| API | Contract |
|---|---|
| `catalog.discover(request, *, now=None)` | Read caller-supplied roots, registries, bindings and observations; return a JSON-compatible schema 1 snapshot |
| `paths.normalize(path)` | Normalize local and Windows/UNC path identities |
| `conflicts.select(request, capabilities, policy, snapshot)` | Select an exact typed entrypoint or return ambiguity, missing capability or unavailable source |
| `conflicts.validate_policy(policy)` / `validate_capabilities(capabilities)` | Validate input shapes without authorizing execution |
| `conflicts.fingerprint(value)` | Hash a JSON-compatible selection input |

Catalog requests support `skill_roots`, `repo_roots`, `plugin_registries`,
`plugin_descriptors`, `external_skill_repos` with `profile_home`, `private_bindings`,
`workflow_roots`, and `runtime_discovery`. Roots and registries are explicit;
`approved_roots` bounds resolved links. An omitted source is unchecked. Missing,
malformed, unreadable or ambiguous supplied inputs produce partial coverage.
Record identity and declared/enabled/cached/installed/resolved/discovered/compatible
observations remain separate. Filesystem presence cannot establish runtime use.

On Windows, resolved containment expands 8.3 spellings of approved roots without
following their junction or symlink targets. A short spelling of the same root
works; a link that escapes it still requires its target to be approved separately.
The initial path must also be lexically within an approved root. If Windows cannot
expand a root spelling, its original spelling remains the containment boundary.

`python -m skill_smith` and `skill-smith-catalog` read a request from stdin or
`--request FILE` and print JSON. Exit 0 includes an unchecked catalog, exit 1
indicates partial coverage, and exit 2 indicates an unreadable request. Consumers
must inspect the coverage fields. The catalog has no output or cache directory.
Captured inventories, private policies and raw observations belong in verified
PRIVATE versioned storage governed by the caller's storage contract.

An explicit `runtime_discovery_policy.max_age_seconds` checks each supplied
observation's timestamp. Refreshing the envelope does not refresh old evidence.
Without that policy, freshness remains unassessed.

## Descriptors and execution

`overlays.build(record, target_runtime, capabilities, selector=...)` validates
an exact source entrypoint and its relative resources. A ready descriptor binds
source, resource, capability and transform hashes. `overlays.validate` rechecks
those bytes; `overlays.digest` hashes a descriptor value. Missing or escaping
resources, unsupported workflow syntax and changed pinned sources remain blocked.
Source-specific recipes apply only to the exact revisions in `source_workflows`.
A ready descriptor does not establish deployment or native runtime discovery.
The `llmcall-contexts-v5` transform requires verified private storage in generated
review instructions. Descriptors from v4 or earlier must be rebuilt; validation
rejects their old output policy even when source files have not changed.

`role_entrypoints.invoke` runs an agent template through `llmcall.call`.
`WorkflowSession` preserves explicit review context and completed-step results
in memory. Independent review requires provider-reported model families; unknown
identity cannot qualify. Source restrictions reach llmcall as execution
requirements, and callers can narrow them. The caller owns durable private state,
deployment, replay protection and any separately authorized project writes.

`source_workflows.cli_request` translates a supported argv list to llmcall intent.
It never executes shell text or restores a native session. Unsupported permission
or approval flags fail instead of disappearing during conversion.

Native inventory is separately opt-in through `native_discovery`. It requires
Windows and explicit absolute paths for `executable`, `codex_home` and `cwd`.
The executable must be named `codex.exe`; its provenance remains the caller's
responsibility. A bounded temporary process performs only initialize and
`skills/list`, with fixed arguments, deadline and output limits. The llmcall Job
owner cleans up the process tree. No model turn or persistent helper is created
by this adapter, and raw diagnostics are not copied into catalog records.

## Validation scope

The package regression tests use generated synthetic files and a stub llmcall
client. Native cleanup tests use a synthetic Python child and require Windows;
they never start Codex or a model provider. The package CI builds and independently
imports the wheel on Linux and Windows, checks its version, and runs the deterministic catalog,
selection, resource, conversion and injected agent-context contracts. Windows
package CI requires the native 8.3 alias and junction boundary tests to execute.
Windows cleanup tests additionally require the reviewed llmcall process runtime.

These checks do not prove a live loader, provider permissions, deployment,
authentication or persistent workflow recovery. The standalone budget, dedup,
fleet and acceptance scripts keep their current command-line contracts.
