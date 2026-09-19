"""Source-pinned, structural workflow conversion. No rendering or deployment."""
from copy import deepcopy
import ast
import hashlib
import json
from pathlib import Path
import re
import shlex

from .conflicts import capability_gaps, fingerprint, matches
from . import source_workflows

TRANSFORM_VERSION = "llmcall-contexts-v4"
OPERATIONS = {
    "spawn_agent": "start", "send_input": "reply",
    "mcp__codex__codex": "start", "mcp__codex__codex-reply": "reply",
    "mcp__claude-review__review_start": "start",
    "mcp__claude-review__review_reply_start": "reply",
    "mcp__claude-review__review_status": "poll",
}
FIELDS = {"message", "prompt", "id", "target", "threadId", "jobId", "context", "model",
          "reasoning_effort", "agent_type", "fork_context", "config", "sandbox",
          "approval-policy", "base-instructions", "developer-instructions", "waitSeconds"}
FENCE = re.compile(r"^(`{3,}|~{3,})([^\n]*)\n(.*?)^\1[ \t]*$", re.M | re.S)
LINK = re.compile(r"\[[^\]\n]*\]\(([^)\n]+)\)|^\[[^\]\n]+\]:[ \t]*([^\n]+)", re.M)
INLINE_RESOURCE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
RESOURCE_PREFIX = r"(?:\$\{CLAUDE_PLUGIN_ROOT\}/|\.{1,2}/|(?:references?|resources?|scripts|assets|tools)/)"
RESOURCE_START = re.compile(RESOURCE_PREFIX)
RESOURCE_MENTION = re.compile(r"(?:^|[\s\"'=])" + RESOURCE_PREFIX)
SCRIPT_SUFFIXES = {'.sh', '.py', '.ps1', '.js'}
INTERPRETERS = {'sh', 'bash', 'python', 'python3', 'node'}
NATIVE_CALL = re.compile(r"\b(?:spawn_agent|send_input|mcp__[\w-]+__[\w-]+)\b")
CLI = re.compile(r"\b(?:codex\s+(?:exec|resume)|claude\s+(?:-p|--print)|gemini\s+-p)\b")


class Unsupported(ValueError):
    pass


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def split_template(text):
    """Read top-level metadata without interpreting description examples."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise Unsupported("unterminated_frontmatter")
    meta = {}
    for line in lines[1:end]:
        match = re.match(r"^([\w-]+):\s*(.*)$", line.rstrip())
        if match:
            key, value = match.groups()
            if key in meta:
                raise Unsupported("duplicate_frontmatter_field")
            meta[key] = value
    unknown = set(meta) - {"name", "description", "model", "color", "tools", "allowed-tools", "license"}
    if unknown:
        raise Unsupported("unknown_frontmatter:" + ",".join(sorted(unknown)))
    for key in ("tools", "allowed-tools"):
        if key in meta:
            try:
                value = ast.literal_eval(meta[key])
            except (ValueError, SyntaxError):
                value = [v.strip() for v in meta[key].split(",")]
            if not isinstance(value, list) or not value or any(not isinstance(v, str) or not re.fullmatch(r"[\w-]+", v) for v in value):
                raise Unsupported("unsupported_tool_restriction")
            meta[key] = value
    return meta, "".join(lines[end + 1:])


def _scalar(value):
    if value.startswith(("{", "[", '"', "'")):
        try:
            return json.loads(value)
        except ValueError:
            try:
                return ast.literal_eval(value)
            except (ValueError, SyntaxError):
                raise Unsupported("unsupported_structured_scalar") from None
    if value in {"true", "false"}:
        return value == "true"
    return value


def _call_block(content):
    """Accept a bounded YAML mapping with literal prompt blocks or JSON.

    Unknown fields, YAML tags/anchors, nested objects other than config, and
    trailing prose fail closed. This is deliberately not a general YAML loader.
    """
    text = content.strip()
    if text.startswith("{"):
        if not NATIVE_CALL.search(text):
            return None
        try:
            value = json.loads(text)
        except ValueError:
            raise Unsupported("invalid_call_json") from None
        if len(value) != 1:
            raise Unsupported("call_requires_one_operation")
        op, fields = next(iter(value.items()))
    else:
        lines = text.splitlines()
        if not lines or not re.fullmatch(r"[\w-]+:", lines[0]):
            return None
        op = lines[0][:-1]
        if op not in OPERATIONS:
            if NATIVE_CALL.search(op):
                raise Unsupported("unknown_operation:" + op)
            return None
        fields = {}
        i = 1
        while i < len(lines):
            if not lines[i].strip():
                i += 1
                continue
            match = re.fullmatch(r"  ([\w-]+):(?: (.*))?", lines[i])
            if not match:
                raise Unsupported("unsupported_call_layout")
            key, value = match.group(1), match.group(2) or ""
            if key in fields:
                raise Unsupported("duplicate_call_field")
            i += 1
            if value in {"|", "|-", "|+"}:
                block = []
                while i < len(lines) and (lines[i].startswith("    ") or not lines[i].strip()):
                    block.append(lines[i][4:] if lines[i].strip() else "")
                    i += 1
                value = "\n".join(block)
            else:
                is_handle = key in {"id", "target", "threadId", "jobId"} and value.startswith("[") and value.endswith("]")
                if not is_handle:
                    value = _scalar(value)
            fields[key] = value
    if op not in OPERATIONS:
        raise Unsupported("unknown_operation:" + str(op))
    if not isinstance(fields, dict) or set(fields) - FIELDS:
        raise Unsupported("unknown_call_fields")
    return op, fields


def _step(op, fields, index, contexts):
    action = OPERATIONS[op]
    step = {"index": index, "operation": action, "source_operation": op,
            "source_parameters": deepcopy(fields), "requirements": None}
    if action == "start":
        context = fields.get("context", "review-" + str(index))
        if not isinstance(context, str) or context in contexts:
            raise Unsupported("invalid_or_duplicate_context")
        contexts.append(context)
    else:
        context = fields.get("context") or fields.get("id") or fields.get("target") or fields.get("threadId") or fields.get("jobId")
        # A single conversation's returned source handle has one unambiguous
        # destination. Multiple conversations require an explicit context key.
        if context not in contexts:
            if len(contexts) != 1:
                raise Unsupported("ambiguous_context_reference")
            context = contexts[0]
    step["context"] = context
    if action == "poll":
        if set(fields) - {"jobId", "context", "waitSeconds"}:
            raise Unsupported("unsupported_poll_fields")
        step["semantics"] = "return completed synchronous llmcall result; never invoke again"
        return step
    prompt = fields.get("prompt", fields.get("message"))
    if not isinstance(prompt, str) or not prompt:
        raise Unsupported("missing_prompt")
    if "prompt" in fields and "message" in fields:
        raise Unsupported("duplicate_prompt")
    if fields.get("fork_context") not in (None, False):
        raise Unsupported("implicit_fork_context_requires_explicit_input")
    if fields.get("agent_type") not in (None, "default"):
        raise Unsupported("native_role_requires_role_resolver")
    config = fields.get("config", {})
    if not isinstance(config, dict) or set(config) - {"model_reasoning_effort"}:
        raise Unsupported("unsupported_provider_config")
    if fields.get("approval-policy") not in (None, "never"):
        raise Unsupported("approval_policy_not_enforceable")
    if "sandbox" in fields:
        access = {"read-only": "read_only", "workspace-write": "workspace_write"}.get(fields["sandbox"])
        if access is None:
            raise Unsupported("sandbox_not_enforceable")
        step["requirements"] = {"access": access, "replay": "never_after_start"}
    if "approval-policy" in fields:
        # No approval-mode field exists in the current ExecutionRequirements.
        raise Unsupported("approval_policy_contract_missing")
    if any(key in fields for key in ("base-instructions", "developer-instructions")):
        raise Unsupported("instruction_hierarchy_contract_missing")
    step.update(prompt=prompt,
                model_policy="inherit_or_user_exact", effort_policy="inherit_or_user_override",
                independent_review=True, mode="judge")
    return step


def _link_destination(reference):
    """A link is a static destination, never an argv example."""
    match = re.fullmatch(r'''\s*(?:<([^<>]+)>|(\S+?))(?:\s+(?:"[^"]*"|'[^']*'))?\s*''', reference)
    if not match:
        raise Unsupported("ambiguous_resource_reference")
    return match.group(1) or match.group(2)


def _inline_resources(example):
    """Lex a bounded direct-script example; never execute or expand shell text.

    Only resource-prefixed arguments denote bundled inputs. Caller filenames
    such as agents/[identifier].md remain opaque example arguments. Static
    resources containing spaces must be quoted; filesystem existence cannot
    decide whether whitespace separates a path or arguments.
    """
    if not RESOURCE_MENTION.search(example):
        return []
    literal = example.replace('${CLAUDE_PLUGIN_ROOT}', '')
    if re.search(r'[$;&|<>\\\r\n]|%[^%]+%', literal):
        raise Unsupported("unsupported_resource_command")
    try:
        argv = shlex.split(example, comments=False, posix=True)
    except ValueError:
        raise Unsupported("unsupported_resource_command") from None
    if argv[0] in INTERPRETERS:
        argv = argv[1:]
        if not argv or Path(argv[0]).suffix not in SCRIPT_SUFFIXES:
            raise Unsupported("unsupported_resource_command")
    if not argv or not RESOURCE_START.match(argv[0]):
        raise Unsupported("unsupported_resource_command")
    if len(argv) == 1:
        return argv
    if Path(argv[0]).suffix not in SCRIPT_SUFFIXES:
        raise Unsupported("ambiguous_resource_reference")
    refs = [argv[0]]
    for arg in argv[1:]:
        value = arg.partition('=')[2] if arg.startswith('-') and '=' in arg else arg
        if RESOURCE_START.match(value):
            refs.append(value)
    return refs


def _resources(body, source_file, root, plugin_root=None, entry=None):
    links = [m.group(1) or m.group(2) for m in LINK.finditer(body)]
    refs = [(ref, _link_destination(ref)) for ref in links]
    refs += [(ref, ref) for m in INLINE_RESOURCE.finditer(body)
             for ref in _inline_resources(m.group(1))]
    result = []
    for ref, value in sorted(set(refs)):
        resource_ref = source_workflows.resource_reference(entry or {}, value)
        if resource_ref is None:
            continue
        binding = source_workflows.resource_binding(entry or {}, resource_ref)
        value = binding['path'] if binding else resource_ref
        if value.startswith(("https://", "http://", "mailto:", "#")):
            continue
        value = value.split("#", 1)[0]
        base = source_file.parent
        if value.startswith("${CLAUDE_PLUGIN_ROOT}/"):
            base, value = plugin_root or root, value[len("${CLAUDE_PLUGIN_ROOT}/"): ]
        if not value or re.search(r'[$*?\[\]{}<>\\]', value) or "://" in value:
            raise Unsupported("unresolved_resource_reference")
        target = (base / value).resolve()
        if not target.is_relative_to(root):
            raise Unsupported("resource_outside_source_root")
        if not target.exists():
            raise Unsupported("resource_missing:" + ref)
        files = sorted(target.rglob("*")) if target.is_dir() else [target]
        members = []
        for path in files:
            resolved = path.resolve()
            if not resolved.is_relative_to(root):
                raise Unsupported("resource_link_escape")
            if path.is_file():
                members.append({"relative_path": path.relative_to(root).as_posix(),
                                "resolved_path": str(resolved), "hash": digest(path.read_bytes())})
        resource = {"reference": ref, "resolved_path": str(target),
                    "relative_path": target.relative_to(root).as_posix(), "files": members}
        if binding:
            if not target.is_file() or len(members) != 1 or members[0]['hash'] != binding['hash']:
                raise Unsupported("resource_binding_drift")
            resource['binding'] = deepcopy(binding)
        result.append(resource)
    return result


def build(record, target_runtime, capabilities, *, selector=None, resource_root=None, workflow_kind=None):
    """Return a descriptor for the bridge; unsupported output is never runnable."""
    base = {"schema_version": 1, "status": "unsupported", "target_runtime": target_runtime,
            "transform_version": TRANSFORM_VERSION, "source_id": record.get("source_id"),
            "source_record_hash": record.get("source_hash"), "runtime_discovery": "unchecked",
            "deployment": "not_requested", "capability_snapshot_hash": fingerprint(capabilities)}
    try:
        if target_runtime not in {"codex", "claude"}:
            raise Unsupported("target_runtime")
        entries = [e for e in record.get("entrypoints", []) if e.get("kind") in {"skill", "command", "agent_template"}
                   and (selector is None or matches(e, selector))]
        if len(entries) != 1:
            raise Unsupported("entrypoint_not_unique")
        ep = entries[0]
        if record.get("status", {}).get("resolved") != "yes":
            raise Unsupported("source_unresolved")
        if record.get("status", {}).get("enabled") == "no":
            return dict(base, status='blocked', reasons=['source_disabled'])
        path = Path(ep["resolved_path"]).resolve()
        root = Path(record.get("resolved_path") or path.parent).resolve()
        if root.is_file():
            root = root.parent
        if not path.is_relative_to(root):
            raise Unsupported("entrypoint_outside_source_root")
        source_root = root
        if resource_root is not None:
            explicit_root = Path(resource_root).resolve()
            if not root.is_relative_to(explicit_root):
                raise Unsupported("source_outside_explicit_resource_root")
            root = explicit_root
        raw = path.read_bytes()
        if digest(raw) != ep.get("source_hash"):
            raise Unsupported("source_drift")
        meta, body = split_template(raw.decode("utf-8-sig").replace("\r\n", "\n"))
        adapted = source_workflows.adapt(ep, body, _call_block, FENCE)
        if CLI.search(body) and adapted is None:
            raise Unsupported("provider_cli_requires_dedicated_adapter")
        if meta.get('license') == 'Proprietary. LICENSE.txt has complete terms':
            body += '\n[License](LICENSE.txt)\n'
        if (ep.get('name') in {'xlsx', 'pptx'} and
            ep.get('source_hash') == source_workflows.RESOURCE_REVISIONS.get(ep.get('name'))):
            # These reviewed packages contain sibling helper imports and prose
            # references to bare filenames. Preserve their complete local tree.
            body += '\n[Bundled source resources](.)\n'
        resources = _resources(body, path, root, source_root, ep)
        resource_body = body
        resource_templates = {}
        for resource in resources:
            for member in resource['files']:
                converted = source_workflows.resource_template(ep, member['relative_path'], member['hash'])
                if converted is not None:
                    resource_templates[member['relative_path']] = converted
        if re.search(r"\boracle-pro\b", body) and adapted is None:
            raise Unsupported("external_review_route_requires_adapter:oracle-pro")
        steps, contexts, pieces = [], [], []
        if adapted is not None:
            workflow_kind = adapted['workflow_kind']
            for op, fields in adapted.get('calls', []):
                steps.append(_step(op, fields, len(steps), contexts))
            body = adapted['template']
        end = 0
        for match in FENCE.finditer(body):
            pieces.append(body[end:match.start()])
            parsed = _call_block(match.group(3))
            if parsed:
                step = _step(*parsed, len(steps), contexts)
                steps.append(step)
                pieces.append("```json\n" + json.dumps({"llmcall_workflow_step": step}, indent=2) + "\n```")
            else:
                if NATIVE_CALL.search(match.group(3)):
                    raise Unsupported("unparsed_native_call")
                pieces.append(match.group(0))
            end = match.end()
        pieces.append(body[end:])
        if steps and workflow_kind != "review":
            raise Unsupported("explicit_review_workflow_contract_required")
        if not steps and NATIVE_CALL.search(body):
            raise Unsupported("native_workflow_requires_structured_adapter")
        required = ["llmcall.agent" if ep["kind"] == "agent_template" or workflow_kind == 'cli_compat' else "llmcall.contexts"]
        if adapted and workflow_kind == 'review':
            required.append('llmcall.independent_review')
        gaps = capability_gaps(required, capabilities)
        restrictions = meta.get("tools", meta.get("allowed-tools"))
        requirements = None
        if restrictions is not None:
            requirements = {"tool_allowlist": restrictions, "required_tools": restrictions,
                            "access": "workspace_write" if "Write" in restrictions else "read_only",
                            "replay": "never_after_start"}
        if requirements is not None or any(step.get("requirements") for step in steps):
            gaps += capability_gaps(["llmcall.permissions"], capabilities)
        base.update(status="blocked" if gaps else "ready", reasons=["capability:" + c for c in gaps],
                    entrypoint={k: deepcopy(v) for k, v in ep.items() if k != 'evidence'},
                    source_hash=ep["source_hash"], source_root=str(source_root), resource_root=str(root),
                    source_file=str(path), metadata=meta, resources=resources, steps=steps,
                    resource_body=resource_body, resource_templates=resource_templates,
                    recipe=adapted.get('recipe') if adapted else None,
                    template="".join(pieces), requirements=requirements,
                    execution_instructions='Use installed profile_bridge.workflows for durable steps and skill_smith.role_entrypoints.invoke for role templates. All nested model/agent work MUST use llmcall.call; agent work uses mode="agent", text decisions use judge mode. Never use native spawning or provider CLIs, including examples in source templates/resources. Current session options and exact user choices control model/effort; source hints are provenance. Preserve hard requirements and report missing capabilities explicitly.',
                    context_contract={"transport": "llmcall.call", "history": "full explicit transcript per context",
                                      "independence": "llmcall avoid plus provider-reported result family",
                                      "model": "inherited; explicit user selection is exact",
                                      "source_model_hints": "retained as provenance, not routing policy",
                                      "workflow_kind": workflow_kind})
        base["artifact_hash"] = fingerprint(base)
        return base
    except (Unsupported, OSError, ValueError, KeyError) as error:
        return dict(base, status="unsupported", reasons=[str(error)])


def validate(overlay, *, record=None, target_runtime=None):
    """Recheck source/resources immediately before bridge render or execution."""
    if overlay.get("status") not in {"ready", "blocked"}:
        return False
    if overlay.get("transform_version") != TRANSFORM_VERSION:
        return False
    if target_runtime is not None and overlay.get("target_runtime") != target_runtime:
        return False
    if record is not None and (record.get("source_id") != overlay.get("source_id") or record.get("source_hash") != overlay.get("source_record_hash")):
        return False
    copy = dict(overlay)
    expected = copy.pop("artifact_hash", None)
    if fingerprint(copy) != expected:
        return False
    try:
        if digest(Path(overlay["source_file"]).read_bytes()) != overlay["source_hash"]:
            return False
        if str(Path(overlay["source_file"]).resolve()) != overlay['source_file']:
            return False
        return _resources(overlay.get('resource_body', overlay["template"]), Path(overlay["source_file"]), Path(overlay["resource_root"]), Path(overlay["source_root"]), overlay['entrypoint']) == overlay["resources"]
    except (OSError, ValueError, KeyError):
        return False
