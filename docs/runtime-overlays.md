# Runtime selection and llmcall producer contract

The three modules are additive consumers of catalog schema 1. They do not scan
installed sources, render client configuration, install files, delete caches,
register native roles, or write operational data. The bridge remains the sole
renderer and deployment writer. A producer `ready` result means its supported
conversion is prepared, never that a runtime discovered or executed it.

## Selection

`skill_smith.conflicts.select(request, capabilities, policy, snapshot)` consumes
caller-supplied dictionaries. Private policy belongs in the companion repository's
`data/runtime-selection.json`; there is no public-tree fallback or automatic
policy loader. Requests contain `task`, optional `format`, `requires`, and
`override` (policy entry ID or exact typed catalog selector).

Policy schema 1 contains `entries`: each has `id`, `selector`, `tasks`, `formats`,
`requires`, and `tier` (`main`, `fallback`, or `specialist`). Selectors compare
source_id/kind/name/client/scope/relative_path/install_name exactly. Missing
metadata never authorizes a same-name substitution.

The order is explicit user selection, task/format applicability, required
capabilities, main/fallback preference, then ambiguity. Explicit formats prefer
matching format specialists; generic requests retain primary runtimes. An explicit
selection can bypass applicability and tier preferences, but cannot bypass a
missing capability, disabled source, or unresolved source. All candidates remain
in the result. Two equal candidates return `ambiguous` instead of a name-sorted
winner. This is a consumer decision, not a native-loader priority mechanism.

Capability snapshots use `capabilities: {name: {status, evidence}}`. Only
`supported` with nonempty evidence qualifies at selection. This snapshot cannot
authorize a hard execution boundary; llmcall reassesses ExecutionRequirements at
execution. Missing or unverified hard capability observations remain blocked.

The companion policy covers native image generation with an API fallback, Excel
for general spreadsheets with xlsx as an explicit format specialist, PowerPoint
for general decks with slides as a fallback and pptx/potx as format specialists,
and research/iterative review requiring validated overlays and independent review.
Upstream templates and every explicitly selectable specialist remain available.

## Source and overlay

`overlays.build(record, target_runtime, capabilities, selector=...,
resource_root=None, workflow_kind=None)` returns a JSON-compatible descriptor. The source record and
its exact entrypoint come from the existing catalog. It verifies the entrypoint
bytes against source_hash before converting. A descriptor pins the parent record
hash, entrypoint hash, transform version, target runtime, capability snapshot hash,
resource file hashes and descriptor hash. `validate(descriptor, record=...,
target_runtime=...)` rechecks these before rendering or executing. Source edits,
resource edits/additions, changed parent snapshots, wrong target runtimes and
transform changes invalidate the output.

Relative Markdown links, reference-style links and inline resource paths are
resolved against the original source file. `${CLAUDE_PLUGIN_ROOT}` retains the
actual plugin root. An explicit `resource_root` may cover shared sibling resources;
the producer never guesses a broader root. Every resolved path must stay inside
that explicit boundary. Missing resources and escaping links are unsupported.
The bridge must preserve relative layout using the returned resource manifest;
it must not copy only SKILL.md into an unrelated directory. These are read-time
checks; bridge transaction/source preconditions still guard concurrent changes.

Inline examples distinguish a static resource from a direct script command.
For example, `scripts/check.sh agents/[identifier].md --strict` pins only the
script; the caller's output placeholder stays verbatim in the template. A
resource-prefixed argument, including `--schema=references/schema.json`, is a
separate required input and is hashed independently. Other arguments remain
opaque; the parser does not infer arbitrary command options or output paths.
Explicit Markdown links always declare inputs unless an exact-source recipe
classifies a particular link as an output example. Missing linked files and
dynamic resource paths do not become optional merely because they look like
placeholders.

The bounded command grammar accepts direct `.sh`, `.py`, `.ps1`, and `.js`
paths, or a script preceded by `sh`, `bash`, `python`, `python3`, or `node`.
Paths use forward slashes. Quote paths with spaces in inline code; use angle
brackets for Markdown link destinations containing spaces. Ambiguous unquoted
paths, unknown wrappers, shell operators, substitutions, environment variables,
and resource globs are unsupported. Parsing neither executes commands nor
expands shell text. `${CLAUDE_PLUGIN_ROOT}` is a literal catalog-root anchor,
not an environment lookup. Existing `../` references still require containment
within the source root or an explicitly supplied ancestor boundary.

A source-relative token that actually belongs to a sibling skill requires a
reviewed binding in `source_workflows.RESOURCE_BINDINGS`. A binding matches the
entrypoint name, kind, relative path and source hash, then maps one token to
one plugin-root-relative file with an expected helper hash. Both the binding
and the resolved file hash enter the descriptor and are rechecked by `validate`.
Changed or missing bound helpers fail closed; another same-named helper cannot
substitute. The resolver never searches plugin subdirectories for candidates.
`resource_root` remains a containment boundary covering the source, not a new
base directory for relative paths and not a resource-binding map. The reviewed
agent-creator binding therefore needs no broader resource-root policy entry.

Resource parsing and binding use transform version `llmcall-contexts-v4`;
descriptors from older transforms must be rebuilt before validation. This
change supplies resource evidence only. Capability and permission evidence,
runtime equivalence, rendering and publication retain their existing gates.

The converter adapts the prior ARIS converters' per-file, frontmatter/body and
fenced-call structure. It does not perform global substitutions or delete native
parameters. The supported grammar is one mapping per fenced YAML/text/JSON call,
with two-space parameter indentation, scalar values and literal prompt blocks.
Review conversion requires explicit `workflow_kind="review"`; arbitrary agent work
is never silently converted to text judgment. Native spawn, send_input/target, Codex MCP start/reply and Claude-review MCP
start/reply/status map to explicit start/reply/poll steps. Polls return the stored
synchronous result and never repeat a call. Original parameters remain provenance.
Source model and effort hints are recorded, not made into routing policy.

Unknown fields/layouts/tools, implicit forked context, specialized native roles,
unmapped provider configuration, unsupported approval modes or instruction-hierarchy overrides, direct provider CLI
and external review routes without adapters return `unsupported`. A source's
sandbox requirement maps to ExecutionRequirements and remains blocked without
hard permission evidence. A source with extra unknown workflow constructs must
not be deployed by using only its successfully parsed subset. In particular,
provider-native resume requires a dedicated adapter rather than a fresh call
pretending to have restored that session.

## Role and context execution

`role_entrypoints.invoke(descriptor, prompt, inherited=..., exact_model=...,
effort=..., requirements=..., cwd=..., env=..., cancel=..., timeout=...)` reads and
validates the resolved template, then calls `llmcall.call(..., mode="agent")`.
The optional `client` argument is the llmcall interface, used by synthetic tests.
Omitted chain/model/effort/timeout are left to llmcall. A supplied session model is
propagated with ModelSelection(prefer); an explicit exact model uses
ModelSelection(exact), so llmcall can reject substitution or unverified identity.
The source's frontmatter model never overrides the session. Cwd is the task
workspace; source/resource roots are separately supplied in the prompt.

Source tool restrictions are preserved as required_tools/tool_allowlist/access.
Caller restrictions can narrow authority and add requirements. They cannot remove
the source restrictions. llmcall owns enforcement and returns capability_unavailable
when support is unavailable or unverified. Prompt promises are not enforcement.
No module in llmcall imports the catalog.

`WorkflowSession(descriptor, inherited=...).run_step(index, producer=Result,
inputs=..., ...)` executes explicitly ordered text review rounds. Each context
retains its full prompt/response transcript, current supplied inputs and producer
text, with no silent truncation. This adapter is for explicit text review of supplied
materials; a file path alone is not equivalent to supplying that file's contents. The producer must have a provider-reported model
family; the call passes that family through llmcall's `avoid` contract and checks
the returned Result's reported family. Unknown or same-family identity is not an
independent review. Distinct contexts require explicit keys when source handles
would be ambiguous. Repeated completed step IDs return their recorded result;
failed rounds stop progression and side-effectful histories cannot be replayed.
Per-context model/effort choices and hard requirements persist into followups.
Session state is in memory; a caller needing durable state must use private data.

`coverage_descriptors(snapshot, capabilities)` accounts for the seven known
unrestricted upstream roles and the three restricted plugin-development roles.
It inventories source templates only: it makes no claim about native registration
ownership, invocation counts, runtime discovery or deployment equivalence. User
custom entries are untouched. The bridge may retire only its own native entries,
and only after separate runtime equivalence validation.

## Validation

The focused tests use generated synthetic files via `tools/make_fixtures.py` and
a synthetic llmcall interface. They never invoke providers or native agents.
Run `python -m pytest tests/test_resource_resolution.py tests/test_runtime_overlays.py
tests/test_t10_source_workflows.py tests/test_agent_entrypoints.py
-q -p no:cacheprovider` from the repository root in an isolated test environment.
Runtime skills/list, real permission enforcement, loader behavior, durable review
recovery and removal of managed native registrations require later bridge and
runtime acceptance. Producer tests do not claim those checks passed.
