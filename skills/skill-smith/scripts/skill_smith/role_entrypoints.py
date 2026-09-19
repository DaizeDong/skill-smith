"""Resolved role and workflow entrypoints. Only llmcall owns model execution."""
from copy import deepcopy
import json

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
        import llmcall
        return llmcall
    return client


def _failure(client, reason):
    return client.Result(error=reason, outcome=reason, execution_started=False)


def _requirements(client, declared, requested=None, workspace=None):
    """Intersect allowlists and union required capabilities; never weaken source."""
    if declared is None and requested is None:
        return None
    data = deepcopy(declared or {})
    if requested is not None:
        if not isinstance(requested, client.ExecutionRequirements):
            raise ValueError("invalid_execution_requirements")
        incoming = dict(vars(requested))
        if data.get("access") == "read_only" and incoming["access"] != "read_only":
            raise ValueError("source_permissions_cannot_be_weakened")
        source_allow = data.get("tool_allowlist")
        user_allow = incoming["tool_allowlist"]
        if source_allow is not None and user_allow is not None:
            if not set(user_allow).issubset(source_allow):
                raise ValueError("source_permissions_cannot_be_weakened")
        incoming["tool_allowlist"] = source_allow if user_allow is None else user_allow
        for key in ("required_tools", "required_mcp"):
            incoming[key] = tuple(sorted(set(data.get(key, ())) | set(incoming[key])))
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
    for key in ("required_tools", "required_mcp", "tool_allowlist"):
        if key in data and data[key] is not None:
            data[key] = tuple(data[key])
    return client.ExecutionRequirements(**data)


def _options(client, inherited, exact_model, effort, requirements, cwd, env, cancel, timeout):
    inherited = inherited or {}
    unknown = set(inherited) - {"chain", "model", "effort", "selection", "timeout"}
    if unknown:
        raise ValueError("unknown_inherited_options")
    options = dict(inherited)
    if exact_model is not None:
        options.pop("model", None)
        options["selection"] = client.ModelSelection("exact", exact_model)
    elif options.get("model") is not None and "selection" not in options:
        # Explicit propagation must not be erased by gateway_best's legacy path.
        options["selection"] = client.ModelSelection("prefer", options.pop("model"))
    if effort is not None:
        options["effort"] = effort
    if timeout is not None:
        options["timeout"] = timeout
    options.update(requirements=requirements, cwd=cwd, env=env, cancel=cancel)
    return options


def anchor_workspace(client, requirements, cwd, env=None, *, previous=None, allow_change=False):
    """Resolve through llmcall's caller context without mutating global cwd."""
    from llmcall import process
    from pathlib import Path
    if type(allow_change) is not bool:
        raise ValueError('workspace_transition_requires_boolean_authorization')
    if requirements is not None and not isinstance(requirements, client.ExecutionRequirements):
        raise ValueError('invalid_execution_requirements')
    workspace = requirements.workspace if requirements is not None else None
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
        requirements = client.ExecutionRequirements(**{**vars(requirements), 'workspace': resolved})
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
        req = _requirements(client, overlay.get("requirements"), requirements, cwd)
        options = _options(client, inherited, exact_model, effort, req, cwd, env, cancel, timeout)
    except (ValueError, TypeError) as error:
        return _failure(client, str(error))
    # Source directories are context for relative resources, not the task's cwd.
    text = (overlay['execution_instructions'] + "\n\nROLE TEMPLATE\n" + overlay["template"] + "\n\nSOURCE RESOURCE ROOT\n" +
            overlay["source_root"] + "\n\nRESOURCE MAP\n" + json.dumps(overlay["resources"]) +
            '\n\nADAPTED RESOURCE INSTRUCTIONS (authoritative)\n' + json.dumps(overlay.get('resource_templates', {})) +
            "\n\nUSER TASK\n" + prompt)
    return client.call(text, mode="agent", **options)


class WorkflowSession:
    """Explicit per-workflow context, with no provider-native session IDs.

    Followups include the complete transcript and caller-supplied current input.
    They are fresh text-only calls, not replays of side-effectful agent sessions.
    Polls consume stored results without a model invocation. Session persistence
    belongs in the caller's private state store, never in a public skill tree.
    """
    def __init__(self, overlay, *, client=None, inherited=None):
        self.overlay = deepcopy(overlay)
        self.client = _client(client)
        self.inherited = dict(inherited or {})
        self.contexts = {}
        self.completed = {}

    def run_step(self, index, *, prompt=None, inputs=None, producer=None,
                 exact_model=None, effort=None, requirements=None,
                 cwd=None, env=None, cancel=None, timeout=None, allow_workspace_change=False):
        client = self.client
        overlay = self.overlay
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
        if state is not None and state["result"].effects != "none" and step['mode'] != 'agent':
            return _failure(client, "agent_replay_forbidden")
        # A producer's Result is required, not an alias inferred from a CLI name.
        origin = producer if producer is not None else (state["producer"] if state else None)
        if step.get("independent_review"):
            if origin is None or origin.model_source != "provider_reported" or not origin.model_family:
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
                previous_req = client.ExecutionRequirements(**{**vars(previous_req), 'workspace': cwd})
            requested = _requirements(client, vars(previous_req) if previous_req else None, requirements, cwd)
            inherited_req = _requirements(client, overlay.get("requirements"), requested, cwd)
            req = _requirements(client, step.get("requirements"), inherited_req, cwd)
            inherited = state["inherited"] if state else self.inherited
            options = _options(client, inherited, exact_model, effort, req, cwd, env, cancel, timeout)
        except (ValueError, TypeError) as error:
            return _failure(client, str(error))
        if origin is not None:
            options["avoid"] = origin.model_family
        result = client.call(text, mode=step["mode"], **options)
        # llmcall owns route filtering, exact identity and reported model family.
        # As with its refine contract, an alias or unverified reply is no review.
        if result and step.get('independent_review') and (result.model_source != "provider_reported" or not result.model_family or result.model_family == origin.model_family):
            result.provider = None
            result.error = "independent_reviewer_unavailable"
            result.outcome = "independent_reviewer_unavailable"
        self.completed[index] = result
        if result:
            transcript.append({"role": "assistant", "content": result.text})
            self.contexts[context_id] = {"history": transcript, "producer": origin, "result": result,
                                         "requirements": req, "cwd": cwd, "inherited": {k: v for k, v in options.items()
                                            if k in {"chain", "model", "effort", "selection", "timeout"}}}
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
