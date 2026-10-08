"""Resolved role and workflow entrypoints. Only llmcall owns model execution.

This module targets the llmcall 0.3.0 call contract:
``call(prompt, *, mode, chain, model, effort, gateway_best, timeout, web_search, avoid)``.
That contract has no per-call cwd, environment, cancellation or requirements
argument. Its client processes run in this process's working directory and
environment, so this module refuses work that would need anything else instead
of dropping the request silently. Requirements llmcall can enforce (a sandboxed
rung and its network switch) are mapped onto call options; the rest fail closed.
"""
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import fields, is_dataclass
import json
import os
from pathlib import Path

from . import overlays
from .conflicts import capability_gaps

# Public upstream identities, not a registry of user-owned native roles.
NATIVE_ROLES = (
    ("code-simplifier", "code-simplifier"),
    ("pr-review-toolkit", "code-reviewer"),
    ("pr-review-toolkit", "code-simplifier"),
    ("pr-review-toolkit", "comment-analyzer"),
    ("pr-review-toolkit", "pr-test-analyzer"),
    ("pr-review-toolkit", "silent-failure-hunter"),
    ("pr-review-toolkit", "type-design-analyzer"),
)
RESTRICTED_ROLES = (
    ("plugin-dev", "agent-creator"),
    ("plugin-dev", "plugin-validator"),
    ("plugin-dev", "skill-reviewer"),
)

# The llmcall surface this module calls. llmcall 0.2.0 exported neither
# rung_group nor model_group, so an older client is refused here, before any
# workflow state is written or any model is called.
CLIENT_CONTRACT = ("Result", "call", "active_chain", "rung_group", "model_group")
# Session options a context carries from turn to turn. "selection" is accepted
# only as a legacy input (llmcall 0.2.0 ModelSelection) and converted on read.
INHERITED_OPTIONS = frozenset({"chain", "model", "effort", "gateway_best", "timeout"})
REQUIREMENT_DEFAULTS = {"workspace": None, "access": "read_only", "tool_network": "default",
                        "required_tools": (), "required_mcp": (), "tool_allowlist": None,
                        "replay": "never_after_start"}
# Groups whose rungs llmcall runs inside a filesystem sandbox chosen by mode:
# Codex exec gets "-s read-only" in judge mode and "-s workspace-write" in agent
# mode. Claude rungs have no sandbox in judge mode and run with full permissions
# in agent mode, so they cannot carry a requirement.
SANDBOXED_GROUPS = frozenset({"codex"})
# Attempt reasons that mean the rung never launched a client process.
NOT_STARTED = frozenset({"not_installed", "budget_exhausted", "group_already_refused"})


def coverage_descriptors(snapshot, capabilities, target_runtime="codex"):
    """Account for all ten known templates, even absent or blocked ones.

    This is functional adapter coverage, not evidence of native registration,
    ownership, runtime discovery, successful invocation or permission support.
    """
    rows = []
    for plugin, name in NATIVE_ROLES + RESTRICTED_ROLES:
        found = [(r, e) for r in snapshot.get("records", [])
                 if r.get("registry_key") == plugin + "@claude-plugins-official"
                 for e in r.get("entrypoints", []) if e.get("kind") == "agent_template" and e.get("name") == name]
        row = {"role": plugin + ":" + name, "native_seven": (plugin, name) in NATIVE_ROLES,
               "restricted": (plugin, name) in RESTRICTED_ROLES, "status": "unavailable",
               "invocations": 0, "runtime_discovery": "unchecked",
               "native_registration_action": "none; bridge ownership and equivalence required"}
        if len(found) == 1:
            record, ep = found[0]
            overlay = overlays.build(record, target_runtime, capabilities, selector={
                k: ep.get(k) for k in ("source_id", "kind", "name", "relative_path", "client", "scope")})
            row.update(status=overlay["status"], reasons=overlay.get("reasons", []),
                       source_id=record["source_id"], source_hash=ep["source_hash"],
                       entrypoint=deepcopy(ep), requirements=overlay.get("requirements"))
            if row["restricted"] and capability_gaps(["llmcall.permissions"], capabilities):
                row.update(status="blocked", reasons=["hard_permissions_unverified"])
        elif found:
            row.update(status="ambiguous", reasons=["multiple_source_templates"])
        rows.append(row)
    return rows


def _client(client):
    if client is None:
        try:
            import llmcall
        except ImportError as error:
            raise ValueError("llmcall_contract_unavailable:import") from error
        client = llmcall
    missing = [name for name in CLIENT_CONTRACT if not callable(getattr(client, name, None))]
    if missing:
        raise ValueError("llmcall_contract_unavailable:" + ",".join(missing))
    return client


def _failure(client, reason):
    """A definite non-execution: no provider, so the Result is falsy."""
    return client.Result(error=reason)


def _raw(value):
    """Requirement fields as given, from a mapping or a legacy dataclass instance."""
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: getattr(value, f.name) for f in fields(value)}
    if isinstance(value, Mapping):
        return dict(value)
    raise ValueError("invalid_execution_requirements")


def _names(value):
    if not isinstance(value, (list, tuple)) or any(not isinstance(v, str) for v in value):
        raise ValueError("invalid_execution_requirements")
    return tuple(value)


def requirements_mapping(value):
    """Validate requirements and fill defaults; None stays None.

    Accepts a plain mapping, or a legacy llmcall 0.2.0 ExecutionRequirements
    instance (read field by field), so stored and caller-built values both work.
    """
    if value is None:
        return None
    data = _raw(value)
    if set(data) - set(REQUIREMENT_DEFAULTS):
        raise ValueError("invalid_execution_requirements")
    data = {**REQUIREMENT_DEFAULTS, **data}
    if (data["access"] not in ("read_only", "workspace_write")
            or data["tool_network"] not in ("default", "required", "forbidden")
            or data["replay"] not in ("never_after_start", "staged_idempotent", "read_only")
            or (data["workspace"] is not None and not isinstance(data["workspace"], str))):
        raise ValueError("invalid_execution_requirements")
    for key in ("required_tools", "required_mcp"):
        data[key] = _names(data[key])
    if data["tool_allowlist"] is not None:
        data["tool_allowlist"] = _names(data["tool_allowlist"])
    return data


def _requirements(declared, requested=None, workspace=None):
    """Intersect allowlists and union required capabilities; never weaken source."""
    if declared is None and requested is None:
        return None
    if declared is not None:
        requirements_mapping(declared)
    data = _raw(declared) if declared is not None else {}
    if requested is not None:
        incoming = requirements_mapping(requested)
        if data.get("access") == "read_only" and incoming["access"] != "read_only":
            raise ValueError("source_permissions_cannot_be_weakened")
        source_allow = data.get("tool_allowlist")
        user_allow = incoming["tool_allowlist"]
        if source_allow is not None and user_allow is not None:
            if not set(user_allow).issubset(source_allow):
                raise ValueError("source_permissions_cannot_be_weakened")
        incoming["tool_allowlist"] = source_allow if user_allow is None else user_allow
        for key in ("required_tools", "required_mcp"):
            incoming[key] = tuple(sorted(set(data.get(key) or ()) | set(incoming[key])))
        if data.get("tool_network", "default") != "default":
            if incoming["tool_network"] not in ("default", data["tool_network"]):
                raise ValueError("source_permissions_cannot_be_weakened")
            incoming["tool_network"] = data["tool_network"]
        if data.get("replay") == "never_after_start":
            incoming["replay"] = "never_after_start"
        data.update(incoming)
    if workspace is not None:
        if data.get("workspace") not in (None, workspace):
            raise ValueError("conflicting_workspace")
        data["workspace"] = workspace
    return requirements_mapping(data)


def normalize_inherited(inherited):
    """Session options for llmcall 0.3.0, converting a legacy ModelSelection.

    A 0.2.0 "exact" selection becomes model= plus gateway_best=False (the
    caller's model reaches gateway rungs too); "prefer" becomes a plain model=
    preference; "inherit" adds nothing.
    """
    if inherited is None:
        return {}
    if not isinstance(inherited, Mapping):
        raise ValueError("unknown_inherited_options")
    options = dict(inherited)
    if set(options) - INHERITED_OPTIONS - {"selection"}:
        raise ValueError("unknown_inherited_options")
    selection = options.pop("selection", None)
    if selection is not None:
        if isinstance(selection, Mapping):
            intent, model = selection.get("intent"), selection.get("model")
        else:
            intent, model = getattr(selection, "intent", None), getattr(selection, "model", None)
        if intent in ("exact", "prefer") and isinstance(model, str) and model.strip():
            options["model"] = model
            if intent == "exact":
                options["gateway_best"] = False
            else:
                options.pop("gateway_best", None)
        elif intent != "inherit" or model is not None:
            raise ValueError("invalid_model_selection")
    if "gateway_best" in options and type(options["gateway_best"]) is not bool:
        raise ValueError("unknown_inherited_options")
    return options


def _options(inherited, exact_model, effort, timeout):
    options = normalize_inherited(inherited)
    if exact_model is not None:
        options.update(model=exact_model, gateway_best=False)
    if effort is not None:
        options["effort"] = effort
    if timeout is not None:
        options["timeout"] = timeout
    return options


def _route(client, options, requirements, mode, avoid=None):
    """Call options under which llmcall itself enforces what the caller requires.

    An exact model narrows the chain to rungs of that model's group when the id
    is recognisable, so an unavailable model is a failure, not a substitution.
    Requirements narrow it to sandboxed rungs: read_only runs judge mode
    (read-only sandbox, which still lets Codex inspect files), workspace_write
    keeps the requested mode, and tool_network maps to web_search. Tool
    allowlists and required tools or MCP servers have no llmcall equivalent.
    """
    routed = dict(options)
    chain = routed.get("chain")
    kept = tuple(chain) if chain else tuple(client.active_chain())
    narrowed = False
    if routed.get("gateway_best") is False and routed.get("model"):
        group = client.model_group(routed["model"])
        if group:
            kept = tuple(c for c in kept if client.rung_group(c) == group)
            narrowed = True
            if not kept:
                raise ValueError("exact_model_unavailable")
    if requirements is not None:
        if requirements["tool_allowlist"] is not None:
            raise ValueError("execution_requirements_unenforceable:tool_allowlist")
        for key in ("required_tools", "required_mcp"):
            if requirements[key]:
                raise ValueError("execution_requirements_unenforceable:" + key)
        kept = tuple(c for c in kept if client.rung_group(c) in SANDBOXED_GROUPS)
        narrowed = True
        if not kept:
            raise ValueError("execution_requirements_unenforceable:no_sandboxed_rung")
        if requirements["access"] == "read_only":
            mode = "judge"
            # The read-only sandbox binds the filesystem only: Codex keeps its configured MCP
            # servers in judge mode, and an MCP tool runs outside the sandbox. Ask llmcall to
            # disable them. llmcall treats this as a verified best effort, not a boundary: when it
            # cannot verify the configuration the rung runs with its tools, and the Result does
            # not say so. That is why read_only is not a permission guarantee, and why the
            # llmcall.permissions capability stays unverified (which keeps every overlay whose
            # source restricts tools blocked before it can reach this function).
            routed["mcp_isolation"] = True
        if requirements["tool_network"] != "default":
            routed["web_search"] = requirements["tool_network"] == "required"
    if narrowed:
        if avoid is not None and all(client.rung_group(c) == avoid for c in kept):
            raise ValueError("independent_reviewer_unavailable")
        routed["chain"] = list(kept)
    if avoid is not None:
        routed["avoid"] = avoid
    routed["mode"] = mode
    return routed


def _same_path(left, right):
    return os.path.normcase(os.path.realpath(left)) == os.path.normcase(os.path.realpath(right))


def _dispatch_error(cwd, env, cancel):
    """What llmcall 0.3.0 cannot honour for this call, or None.

    Its clients run in this process's cwd and environment, and a started call
    is bounded by its timeout, not by a cancellation token. A token already set
    stops the call before it starts.
    """
    if cancel is not None:
        is_set = getattr(cancel, "is_set", None)
        if not callable(is_set):
            return "invalid_cancellation"
        if is_set():
            return "cancelled"
    if env is not None:
        if not isinstance(env, Mapping):
            return "invalid_environment"
        for key, value in env.items():
            if os.environ.get(key) != value:
                return "environment_override_unsupported:" + str(key)
    if cwd is not None and not _same_path(cwd, os.getcwd()):
        return "workspace_requires_process_cwd"
    return None


def result_group(result):
    """The policy group that answered, as llmcall reports it; None when unknown."""
    group = getattr(result, "group", None) if result is not None else None
    return group if isinstance(group, str) and group else None


def call_effects(result, mode):
    """"possible" when an agent-mode call may have started a client, else "none"."""
    if mode != "agent":
        return "none"
    if result:
        return "possible"
    attempts = getattr(result, "attempts", None) or ()
    return "possible" if any(getattr(a, "reason", None) not in NOT_STARTED for a in attempts) else "none"


def anchor_workspace(client, requirements, cwd, env=None, *, previous=None, allow_change=False):
    """Resolve through llmcall's caller context without mutating global cwd."""
    client = _client(client)
    process = getattr(client, "process", None)
    if process is None:
        try:
            from llmcall import process
        except ImportError as error:
            raise ValueError("llmcall_contract_unavailable:process") from error
    if not callable(getattr(process, "resolve_context", None)):
        raise ValueError("llmcall_contract_unavailable:process.resolve_context")
    if type(allow_change) is not bool:
        raise ValueError('workspace_transition_requires_boolean_authorization')
    requirements = requirements_mapping(requirements)
    workspace = requirements["workspace"] if requirements is not None else None
    old = (previous or {}).get('cwd')
    resolved = process.resolve_context(cwd or workspace or old, env).cwd
    if not isinstance(resolved, str) or not Path(resolved).is_absolute() or '\x00' in resolved:
        raise ValueError('workspace_must_resolve_absolute')
    if cwd is not None and workspace is not None:
        other = process.resolve_context(workspace, env).cwd
        if Path(other) != Path(resolved):
            raise ValueError('conflicting_workspace')
    if old is not None and Path(old) != Path(resolved) and not allow_change:
        raise ValueError('workspace_transition_requires_explicit_authorization')
    if requirements is not None:
        requirements = {**requirements, 'workspace': resolved}
    return requirements, resolved


def invoke(overlay, prompt, *, inherited=None, exact_model=None, effort=None,
           requirements=None, cwd=None, env=None, cancel=None, timeout=None, client=None):
    """Run one resolved role; source model hints never replace session policy."""
    client = _client(client)
    if overlay.get("status") != "ready" or not overlays.validate(overlay):
        return _failure(client, "overlay_unavailable_or_stale")
    if overlay["entrypoint"]["kind"] != "agent_template" or overlay["steps"]:
        return _failure(client, "role_requires_template_adapter")
    try:
        req = _requirements(overlay.get("requirements"), requirements, cwd)
        options = _route(client, _options(inherited, exact_model, effort, timeout), req, "agent")
    except (ValueError, TypeError) as error:
        return _failure(client, str(error))
    blocked = _dispatch_error(cwd, env, cancel)
    if blocked:
        return _failure(client, blocked)
    # Source directories are context for relative resources, not the task's cwd.
    text = (overlay['execution_instructions'] + "\n\nROLE TEMPLATE\n" + overlay["template"] + "\n\nSOURCE RESOURCE ROOT\n" +
            overlay["source_root"] + "\n\nRESOURCE MAP\n" + json.dumps(overlay["resources"]) +
            '\n\nADAPTED RESOURCE INSTRUCTIONS (authoritative)\n' + json.dumps(overlay.get('resource_templates', {})) +
            "\n\nUSER TASK\n" + prompt)
    return client.call(text, **options)


class WorkflowSession:
    """Explicit per-workflow context, with no provider-native session IDs.

    Followups include the complete transcript and caller-supplied current input.
    They are fresh text-only calls, not replays of side-effectful agent sessions.
    Polls consume stored results without a model invocation. Session persistence
    belongs in the caller's private state store, never in a public skill tree.
    ``last_effects`` reports whether the latest step may have changed anything.
    """
    def __init__(self, overlay, *, client=None, inherited=None):
        self.overlay = deepcopy(overlay)
        self.client = _client(client)
        self.inherited = dict(inherited or {})
        self.contexts = {}
        self.completed = {}
        self.last_effects = "none"

    def run_step(self, index, *, prompt=None, inputs=None, producer=None,
                 exact_model=None, effort=None, requirements=None,
                 cwd=None, env=None, cancel=None, timeout=None, allow_workspace_change=False):
        client = self.client
        overlay = self.overlay
        self.last_effects = "none"
        if overlay.get("status") != "ready" or not overlays.validate(overlay):
            return _failure(client, "overlay_unavailable_or_stale")
        turn = getattr(self, '_turn', None)
        if not isinstance(index, int) or index < 0 or (turn is None and index >= len(overlay["steps"])):
            return _failure(client, "unknown_workflow_step")
        if index in self.completed:
            return self.completed[index]
        if self.completed and not self.completed[max(self.completed)]:
            return _failure(client, "workflow_previous_step_failed")
        if index != len(self.completed):
            return _failure(client, "workflow_step_out_of_order")
        step = turn[1] if turn is not None else overlay["steps"][index]
        context_id = step["context"]
        if step["operation"] == "poll":
            state = self.contexts.get(context_id)
            if not state:
                return _failure(client, "context_unavailable")
            result = state["result"]
            self.completed[index] = result
            return result
        state = self.contexts.get(context_id)
        if step["operation"] == "reply" and state is None:
            return _failure(client, "context_unavailable")
        # A context without recorded effects is treated as possibly side-effectful.
        if state is not None and state.get("effects", "possible") != "none" and step['mode'] != 'agent':
            return _failure(client, "agent_replay_forbidden")
        # A producer's Result is required, not an alias inferred from a CLI name.
        origin = producer if producer is not None else (state["producer"] if state else None)
        origin_group = result_group(origin)
        if step.get("independent_review") and origin_group is None:
            return _failure(client, "independent_reviewer_unavailable")
        history = deepcopy(state["history"]) if state else []
        user_input = {"prompt": prompt if prompt is not None else step["prompt"],
                      "inputs": inputs if inputs is not None else {},
                      "producer_text": origin.text if origin is not None else None}
        transcript = [*history, {"role": "user", "content": user_input}]
        text = (overlay['execution_instructions'] + "\n" + overlay['template'] +
                "\nUse the complete supplied context. Source resources remain relative to " + overlay["source_root"] +
                ".\nRESOURCE MAP\n" + json.dumps(overlay["resources"]) +
                '\nADAPTED RESOURCE INSTRUCTIONS (authoritative)\n' + json.dumps(overlay.get('resource_templates', {})) +
                "\nWORKFLOW CONTEXT\n" + json.dumps({"context": context_id, "messages": transcript}, ensure_ascii=False))
        try:
            requirements, cwd = anchor_workspace(client, requirements, cwd, env, previous=state,
                                                  allow_change=allow_workspace_change)
            previous_req = state.get("requirements") if state else None
            if previous_req is not None and allow_workspace_change:
                previous_req = {**requirements_mapping(previous_req), 'workspace': cwd}
            requested = _requirements(previous_req, requirements, cwd)
            inherited_req = _requirements(overlay.get("requirements"), requested, cwd)
            req = _requirements(step.get("requirements"), inherited_req, cwd)
            inherited = state["inherited"] if state else self.inherited
            options = _options(inherited, exact_model, effort, timeout)
            routed = _route(client, options, req, step["mode"], origin_group)
        except (ValueError, TypeError) as error:
            return _failure(client, str(error))
        blocked = _dispatch_error(cwd, env, cancel)
        if blocked:
            return _failure(client, blocked)
        result = client.call(text, **routed)
        self.last_effects = call_effects(result, routed["mode"])
        # llmcall owns route filtering and the group that answered. As with its
        # refine contract, an unknown or same-group reply is no review.
        answered = result_group(result)
        if result and step.get('independent_review') and (answered is None or answered == origin_group):
            result.provider = None
            result.error = "independent_reviewer_unavailable"
        self.completed[index] = result
        if result:
            transcript.append({"role": "assistant", "content": result.text})
            self.contexts[context_id] = {"history": transcript, "producer": origin, "result": result,
                                         "requirements": req, "cwd": cwd, "effects": self.last_effects,
                                         "inherited": {k: v for k, v in options.items()
                                                       if k in INHERITED_OPTIONS}}
        return result

    def run_turn(self, *, context, operation, prompt, mode='judge', independent_review=True, **options):
        """One explicit recipe turn; the caller owns repetition and durability.

        Extends a validated recipe at call time rather than changing its pinned
        artifact. Agent followups include prior results but never replay old calls.
        """
        if not isinstance(context, str) or not context or operation not in {'start', 'reply', 'poll'}:
            return _failure(self.client, 'invalid_workflow_turn')
        if mode not in {'judge', 'agent'}:
            return _failure(self.client, 'invalid_workflow_mode')
        if operation == 'start' and context in self.contexts:
            return _failure(self.client, 'context_already_started')
        original = self.overlay
        if not overlays.validate(original):
            return _failure(self.client, 'overlay_unavailable_or_stale')
        # The transport below still validates the original pinned descriptor.
        index = len(self.completed)
        step = dict(index=index, context=context, operation=operation, prompt=prompt,
                    mode=mode, independent_review=independent_review, requirements=None)
        self._turn = (index, step)
        try:
            return self.run_step(index, prompt=prompt, **options)
        finally:
            self._turn = None
