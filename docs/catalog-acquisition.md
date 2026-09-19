# Optional catalog acquisition and evidence age

This extends the version-one `skill_smith.catalog.discover` request. It uses the
existing shared catalog; consumers do not need another inventory or discovery
service. Filesystem-only requests retain their existing behavior. Explicit native
acquisition starts one temporary child process and always closes its Job.

## Explicit plugin descriptors

`plugin_descriptors: [{"name": "demo@example", "path": "C:/reviewed/plugin"}]`
works independently of `plugin_registries`. Without a registry, use the full
marketplace-qualified name. Bare names remain ambiguous. An omitted registry
remains unchecked even when descriptors were inspected successfully. The selected
record has `registry_path: null`; descriptor evidence does not claim a registry
was read. Settings-based enablement remains unknown without settings evidence.

Conflicting paths for one explicit identity are partial and yield no entrypoints.
When a registry is supplied, the existing exact identity/path resolution applies.
A descriptor that disagrees with the registry path is partial and cannot mark
that registry installation as an explicit selection.

## Native Codex skills discovery

Add this optional object to the existing catalog request:

```json
{
  "native_discovery": {
    "enabled": true,
    "executable": "C:/reviewed/codex.exe",
    "codex_home": "C:/reviewed/client-home",
    "cwd": "C:/reviewed/workspace",
    "timeout_seconds": 20,
    "max_output_bytes": 4194304
  }
}
```

These are synthetic example locations. The release owner supplies reviewed,
existing absolute paths. `executable` must resolve to a file named `codex.exe`;
home and cwd must resolve to directories. No PATH lookup, environment expansion,
shell wrapper, arbitrary command, custom arguments, or inferred home is accepted.
The caller remains responsible for executable provenance and approved client
configuration. The adapter checks path/type, not a signature or executable hash.

The schema accepts only the six keys above. `enabled` must be a Boolean and must
be present. `{"enabled": false}` is sufficient to disable acquisition. Supplied
optional fields are still validated. Timeout defaults to 20 seconds and accepts a
finite number from 1 through 60, inclusive, including cleanup. The per-stream
output byte limit defaults to 4 MiB and accepts an integer from 1024 through
16 MiB. Booleans are not numbers. Invalid configuration reports partial coverage
without launching a process. Omitted native configuration adds no coverage stage;
explicit disabled configuration reports unchecked native coverage.

Enabled acquisition currently requires Windows and an installed `llmcall` exposing
`process.WindowsJob`, `remaining_timeout`, `current_control`, and `current_context`.
The process owner is imported only for enabled acquisition. Packaging the optional
dependency belongs to the release owner. There is no alternative process owner.

The fixed command is `codex.exe app-server --strict-config` with the two fixed
configuration overrides `check_for_update_on_startup=false` and
`analytics.enabled=false`. The supplied home is passed as `CODEX_HOME`; the supplied
cwd is both the process cwd and the sole requested workspace. Ambient environment
is inherited from llmcall's execution context. No credentials or raw diagnostics
are copied into the catalog.

The complete outbound JSON-RPC sequence is:

1. `initialize`, with catalog client identity.
2. `initialized`, after a successful initialization response.
3. `skills/list`, with `cwds: [cwd]` and `forceReload: true`.

No thread, turn, model call, skill invocation, authentication probe, or persistent
service is created. This is a native inventory query; the selected client's own
normal initialization behavior still applies. Root performs the installed live
verification separately.

The Job contains the child before resume and owns descendants on every exit.
Pipe workers bound stdout and stderr separately, bound the response queue, and
keep blocked stdin off the supervisor. The overall deadline reserves up to two
seconds (20 percent of shorter budgets) for cleanup and respects llmcall's parent
deadline/cancellation. The Job is closed, the child reaped, workers joined, and
pipes closed before results are released. Cleanup failure overrides a successful
protocol result. Errors use fixed codes; stderr and JSON-RPC error bodies are
discarded. No disk capture/cache or persistent helper is created by this adapter.

## Exact mapping and partial evidence

Configure the existing `skill_roots` with `client: "codex"` and approved target
roots. Native results are matched by the resolved absolute `SKILL.md` path against
existing Codex skill entrypoints. The match must contain exactly one entrypoint,
including its source identity. Names and native scope labels never disambiguate
paths. Entries belonging to another client do not receive Codex evidence.

Successful acquisition adds `coverage.native_discovery` and a
`native_discovery: {observed_at, entrypoints}` result. Each observed row retains
the capture timestamp, path, Boolean `enabled` (or null), native scope when
provided, and a `match` value: `exact`, `unmatched`, or `ambiguous`. Exact rows
also include the existing `source_id`, `kind`, `name`, `client`, `scope`,
`relative_path`, `install_name`, and `discovered` state. No source identities are
invented for unmatched paths. Capture time is recorded when the response arrives,
not when a later catalog envelope is created.

Enabled observations set entrypoint discovery/enabled to yes; disabled observations
set them to no; missing/malformed flags remain unknown and partial. Duplicate
observations or catalog matches are ambiguous and cannot preserve an earlier yes
on the affected entrypoint. Missing paths, unexpected workspace groups, native
load errors and malformed data produce partial coverage while preserving valid
independent rows. Paths absent from the response are not negative observations.
Raw native names/descriptions/error messages are not copied. Compatibility and
authentication are never inferred; source-wide aggregate availability is not
promoted from one observed entrypoint.

If both supplied runtime evidence and native acquisition are configured, supplied
evidence is processed first. Exact native observations then replace discovery and
enabled evidence on matched Codex entrypoints, leaving separately supplied
compatibility evidence alone. Acquisition failure preserves the independent
inventory and reports partial coverage; it does not fabricate a fresh capture.

## Supplied runtime evidence age

The existing `runtime_discovery` filename and normalized `entrypoints` document
remain accepted. Add an explicit policy alongside the filename:

```json
{
  "runtime_discovery": "C:/reviewed/private/runtime-observation.json",
  "runtime_discovery_policy": {"max_age_seconds": 3600}
}
```

The policy accepts exactly `max_age_seconds`, an integer from 0 through 31536000.
Age is measured separately from the catalog envelope/cache. Evidence at the exact
age limit is current. Older, future-dated, missing, naive, or invalid timestamps
produce unknown discovery/compatibility and partial runtime coverage. The original
timestamp and supplied state remain in evidence; missing timestamps remain null.
A new envelope therefore cannot refresh expired evidence under this policy.

For backward compatibility, omission of the policy retains legacy supplied status
values with `freshness: "unassessed"`; it makes no freshness claim. Consumers that
need current observations must configure the policy. No default cadence is
invented. Evidence records expose `freshness` and `supplied_value`; runtime coverage
also reports the selected `max_age_seconds` (null when unassessed).

`discover(request, *, now=None)` provides a deterministic testing seam. `now` may
be an aware datetime or an ISO timestamp with timezone; omitted means current UTC.
It sets the evaluation/envelope time, never a native response's capture time.
Requests and supplied files are not mutated.

The console's `catalog_max_age_seconds` still controls catalog caching, not native
evidence age. A cache hit does not execute this producer. The integration owner
must choose cache and evidence windows together, pin private input files as
appropriate, install llmcall, and verify the selected native executable after
installation. Captured operational inventory belongs in the private data store.
