# Source catalog API, version 1

`skill_smith.catalog.discover(request: dict) -> dict` reads explicitly supplied
sources and returns a JSON-compatible snapshot. It performs no writes, network
requests, model calls, service starts, authentication probes or installations.
The package lives alongside the existing scripts and can be built as a wheel
from the root `pyproject.toml`.

After installing the package into the caller's chosen runtime, use
`python -m skill_smith --request request.json`, or pass a request on stdin.
The CLI writes JSON to stdout. Exit 0 means discovery completed, including an
explicitly unchecked snapshot; exit 1 means partial coverage; exit 2 means the
request could not be read. Callers must inspect coverage, not just the exit code.
Captured snapshots contain operational paths and inventory and belong in the
caller's private data store. The catalog has no default output or cache path.

## Request

All paths are caller supplied. The core has no home-directory defaults and never
searches arbitrary checkout directories. Relative declaration components must
stay under their declared root. Absolute paths are recommended for request roots.

| Field | Shape and meaning |
| --- | --- |
| `profile_home` | Base directory for the external manifest's relative roots. |
| `external_skill_repos` | Path to the existing external-skill-repos JSON manifest. |
| `approved_roots` | Additional directories that resolved links may target. |
| `skill_roots` | List of objects with `path`, optional stable `namespace`, `client`, `scope` (default `user`), `max_depth` (default 1), and `approved_roots`. These are installed entrypoint roots. |
| `repo_roots` | List of objects with `path`, optional `namespace` and `approved_roots`. Enumerates direct child working copies, including `.git` files. |
| `plugin_registries` | List of objects with `path`, `client` (default `claude`), `scope` (default `user`), optional `scope_path`, `settings_path`, and `approved_roots`. |
| `private_bindings` | Path to an object containing `bindings`: typed objects with `id`, `kind` (`mcp_binding` or `app_connector`), `server` or `connector`, and optional `authenticated` observation. Unknown fields, including credentials, are not copied. |
| `runtime_discovery` | Path to an object containing `entrypoints`: exact observations with `source_id`, `kind`, `name`, `client`, `scope`, optional `discovered`, `compatible`, and `observed_at`. |

Plugin registries use the existing `plugins` object keyed by the full
`name@marketplace` string. An installation can be an object or list of objects
with `installPath`, `version`, `scope`, `projectPath` and `gitCommitSha`.
The descriptor supplies the client identity; `projectPath` distinguishes project
scopes. Settings use `enabledPlugins` with the same full registry keys. Missing
settings or missing keys mean enablement is unknown. Supply effective settings
for the client/scope being observed; the catalog does not implement settings
inheritance. Without explicit plugin approved roots, the registry's parent
directory is the read boundary.

Settings apply only to the descriptor's exact client, scope and project path.
Other installations in the same registry remain inventoried with unknown
enablement until their own effective settings are supplied. Plugin entrypoints
keep `install_name` and `relative_path` independently of frontmatter `name`.
Runtime observations may include either field to identify one of several
entrypoints with the same frontmatter name; ambiguous observations update none.

An omitted input has `coverage.status = unchecked`. An explicitly supplied empty
list is checked and empty. A missing, malformed, inaccessible, escaping or
ambiguous configured source produces partial coverage and a problem. Other valid
declarations remain in the result. There is no recovery by choosing a similarly
named directory or a newer cache version.

## Identity and observations

Records include `source_id`, `kind`, `origin`, `registry_key`, `relative_path`,
`version`, `source_hash`, `entrypoints`, `dependencies`, `status`, and `evidence`.
The envelope has `schema_version`, `observed_at`, `records`, `coverage`, `problems`
and conservative aggregate `status` values, which remain unknown. Records are
sorted by source ID. Observation timestamps change between calls.

`source_id` is SHA-256 over a JSON tuple, with a kind prefix. External skill
identity uses the exact registered upstream identifier and relative upstream
path. Plugin identity uses the full registry key, client, scope and scope path.
Revision, selected cache directory, installation alias and content hash are
separate. Upstream identifiers are not heuristically equated across SSH aliases
and HTTPS URLs. A local scan uses its declared namespace and relative path;
without a namespace it falls back to the explicit root identity and therefore
does not promise identity across root relocation.

Checkout resolution is `profile_home / skillRepoRoot / repo.dir / skill.subPath`.
Vendored resolution is `profile_home / vendoredRoot / vendored.name`.
`vendored.subPath` belongs to upstream provenance only. Branch, commit and
vendoring date remain recorded. Frontmatter names and installation aliases remain
separate. Conflicting paths or revisions for one identity are ambiguous.

Exact resolved paths connect installed entrypoints to a declared source across
clients. Matching names alone yield `candidates`; they never transfer ownership.
`cc-setup` has an explicit `external-installer` ownership and installation strategy
exception, including when it is found by scanning. No record authorizes deletion.

Each status dimension (`declared`, `enabled`, `cached`, `installed`, `resolved`,
`discovered`, `compatible`) uses `yes`, `no`, `unknown` or `not_applicable`.
Evidence includes its reason and observation time. Filesystem presence does not
establish runtime discovery, compatibility or general availability. Runtime
observations update only a unique exact typed entrypoint, never a same-name peer.
They do not imply that every entrypoint in the owning plugin is available.

Plugin skill, command and agent-template files remain typed entrypoints. A
selected plugin's `.mcp.json` yields individual MCP binding records and typed
dependencies. Server configuration, commands, environment values and headers are
not copied into the catalog and are never executed. Authentication is unknown
until supplied as a specific binding observation; there is no plugin-wide
authentication Boolean. Private binding IDs are their own identities in this
version; merging private observations with plugin MCP records is a consumer
integration concern and is not inferred by server name.

Skill `source_hash` hashes the observed SKILL.md bytes. Plugin `source_hash`
hashes the sorted typed entrypoint paths, names and content hashes. It is an entrypoint
content digest, not verification of an entire repository or a vendored pin.
The registered version/pin is retained as a declaration, not claimed as a Git
verification. Linked worktree discovery recognizes the Git marker without
traversing its metadata directory or asserting Git health.

Path observations retain the requested path, direct reparse target and final
resolved target. Both lexical and final paths must be within approved roots.
UNC device prefixes are normalized without losing the server/share boundary.
Missing paths and unreadable paths are different observations. These are
read-time checks, not a sandbox or a guarantee against concurrent replacement.

## Existing readers

`budget_check.py`, `dedup_check.py` and `fleet_check.py` accept `--catalog-json`.
Their Python entrypoints can also accept a snapshot, so discovery can occur once
and every reader can analyze the same captured files and metadata.

The legacy startup arguments still construct catalog requests. Budget retains
its tier rules, per-skill cap, capacity arithmetic and plugin cost deduplication
across scopes. All unresolved scopes remain visible in its problem list.
Dedup retains Jaccard description overlap and its historical two-level scan.
Its `--code-root` option supplies the approved target root for skill junctions.
Fleet shares one local snapshot between repository, junction and budget readers;
remote compliance checks retain their separate transport and verdict rules.

`--settings` on budget/fleet supplies exact plugin enablement. Without settings,
registered installs remain measurable with enablement unknown, preserving the
legacy report's arithmetic. Disabled entries in a supplied snapshot add no cost.
An arithmetic OK result does not turn partial catalog coverage into a complete
inventory. Conflict selection, policy and workflow overlays are outside this
producer API.
