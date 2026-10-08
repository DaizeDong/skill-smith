"""Synthetic llmcall stub only; no provider transports, agents or CLI calls."""
from dataclasses import dataclass, field
from pathlib import Path
import inspect
import json
import threading
from types import SimpleNamespace

import pytest
from test_runtime_overlays import source, caps
from skill_smith import overlays, role_entrypoints as roles
from tools.make_fixtures import synthetic_call_context

GROUPS = {"codexg": "codex", "codex": "codex", "cc": "claude", "claude": "claude"}
LADDER = ("codexg", "codex", "cc", "claude")


@dataclass
class Attempt:
    provider: str
    ok: bool
    ms: int = 0
    error: str | None = None
    reason: str | None = None


@dataclass
class Result:
    """The llmcall 0.3.0 Result shape."""
    text: str = ""
    provider: str | None = None
    data: object = None
    error: str | None = None
    attempts: list = field(default_factory=list)
    depth: int = 0
    group: str | None = None

    def __bool__(self):
        return self.provider is not None


@dataclass
class LegacyRequirements:
    """A caller still holding an llmcall 0.2.0 ExecutionRequirements value."""
    workspace: str | None = None
    access: str = "read_only"
    tool_network: str = "default"
    required_tools: tuple = ()
    required_mcp: tuple = ()
    tool_allowlist: tuple | None = None
    replay: str = "never_after_start"


class Stub:
    Result = Result
    Attempt = Attempt
    process = SimpleNamespace(resolve_context=synthetic_call_context)

    def __init__(self, ladder=LADDER):
        self.calls = []
        self.ladder = tuple(ladder)
        self.group = "review-group"

    def active_chain(self):
        return self.ladder

    def rung_group(self, name):
        return GROUPS.get(name, name)

    def model_group(self, model):
        if model.startswith("gpt-"):
            return "codex"
        if model.startswith("claude-"):
            return "claude"
        return None

    def call(self, prompt, **options):
        self.calls.append((prompt, options))
        return Result(text="Synthetic response " + str(len(self.calls)), provider="stub", group=self.group,
                      attempts=[Attempt("stub", True)])


def producer(group="author-group"):
    return Result(text="Complete producer output", provider="stub", group=group)


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    # llmcall 0.3.0 runs clients in the process cwd, so the workspace is the cwd.
    monkeypatch.chdir(tmp_path)


@pytest.mark.parametrize("operation", ["client", "invoke", "workflow", "workspace"])
def test_a_02_client_is_rejected_before_execution(monkeypatch, operation):
    # llmcall 0.2.0 had ModelSelection/ExecutionRequirements but no rung_group/model_group.
    legacy = SimpleNamespace(Result=Result, ModelSelection=object, ExecutionRequirements=object,
                             active_chain=lambda: LADDER, call=lambda *a, **k: pytest.fail("unexpected model call"))
    if operation == "client":
        import sys
        monkeypatch.setitem(sys.modules, "llmcall", legacy)
        run = lambda: roles._client(None)
    elif operation == "invoke":
        run = lambda: roles.invoke({}, "Synthetic task", client=legacy)
    elif operation == "workflow":
        run = lambda: roles.WorkflowSession({}, client=legacy)
    else:
        run = lambda: roles.anchor_workspace(legacy, None, None)
    with pytest.raises(ValueError, match="llmcall_contract_unavailable:rung_group,model_group"):
        run()


def test_emitted_options_are_accepted_by_the_installed_llmcall_call():
    llmcall = pytest.importorskip("llmcall")
    if not callable(getattr(llmcall, "rung_group", None)):
        pytest.skip("installed llmcall predates the 0.3.0 contract")
    accepted = set(inspect.signature(llmcall.call).parameters)
    emitted = {"mode", "chain", "model", "effort", "gateway_best", "timeout", "web_search", "avoid"}
    assert emitted <= accepted
    # The 0.2.0 per-call arguments are gone; this module must never send them.
    assert not {"selection", "requirements", "cwd", "env", "cancel"} & accepted
    roles._client(llmcall)


def test_explicit_client_context_does_not_import_a_runtime(monkeypatch, tmp_path):
    import sys
    monkeypatch.setitem(sys.modules, "llmcall", None)
    requirements, cwd = roles.anchor_workspace(Stub(), None, str(tmp_path))
    assert requirements is None and cwd == str(tmp_path)


def test_missing_process_context_is_explicit():
    client = Stub()
    client.process = SimpleNamespace()
    with pytest.raises(ValueError, match="llmcall_contract_unavailable:process.resolve_context"):
        roles.anchor_workspace(client, None, None)


def test_role_reads_source_and_propagates_exact_model_effort_chain(tmp_path):
    rec = source(tmp_path, "Review synthetic design.", kind="agent_template", metadata="model: upstream-pin\n")
    built = overlays.build(rec, "codex", caps("llmcall.agent"))
    stub = Stub()
    result = roles.invoke(built, "Check invariants", inherited={"chain": ["session-route"], "model": "session-model", "effort": "high"},
                          exact_model="user-exact-model", effort="medium", client=stub)
    assert result
    prompt, options = stub.calls[0]
    assert "Review synthetic design." in prompt and "Check invariants" in prompt
    assert "upstream-pin" not in prompt
    assert options["model"] == "user-exact-model" and options["gateway_best"] is False
    assert options["chain"] == ["session-route"] and options["effort"] == "medium"
    assert options["mode"] == "agent"
    assert not {"selection", "requirements", "cwd", "env", "cancel"} & set(options)


def test_role_inherits_without_a_new_provider_chain(tmp_path):
    built = overlays.build(source(tmp_path, "Role", kind="agent_template"), "codex", caps("llmcall.agent"))
    stub = Stub()
    roles.invoke(built, "Task", client=stub)
    assert set(stub.calls[0][1]) == {"mode"}
    roles.invoke(built, "Task", inherited={"model": "session-model", "effort": "high"}, client=stub)
    assert stub.calls[1][1] == {"mode": "agent", "model": "session-model", "effort": "high"}


def test_exact_model_of_a_known_group_never_falls_to_another_group(tmp_path):
    built = overlays.build(source(tmp_path, "Role", kind="agent_template"), "codex", caps("llmcall.agent"))
    stub = Stub()
    assert roles.invoke(built, "Task", exact_model="gpt-synthetic", client=stub)
    assert stub.calls[0][1]["chain"] == ["codexg", "codex"]
    only_claude = Stub(ladder=("cc", "claude"))
    result = roles.invoke(built, "Task", exact_model="gpt-synthetic", client=only_claude)
    assert not result and result.error == "exact_model_unavailable" and not only_claude.calls


@pytest.mark.parametrize("selection, expected", [
    (SimpleNamespace(intent="exact", model="legacy-model"), {"model": "legacy-model", "gateway_best": False}),
    ({"intent": "prefer", "model": "legacy-model"}, {"model": "legacy-model"}),
    ({"intent": "inherit", "model": None}, {}),
])
def test_legacy_model_selection_in_inherited_options_is_read(selection, expected):
    assert roles.normalize_inherited({"selection": selection, "effort": "high"}) == {**expected, "effort": "high"}


def test_invalid_legacy_selection_is_refused():
    with pytest.raises(ValueError, match="invalid_model_selection"):
        roles.normalize_inherited({"selection": {"intent": "exact", "model": ""}})


def test_tool_restrictions_fail_closed_and_never_degrade(tmp_path):
    rec = source(tmp_path, "Read synthetic input.", kind="agent_template", metadata='tools: ["Read", "Grep", "Glob"]\n')
    built = overlays.build(rec, "codex", caps("llmcall.agent", "llmcall.permissions"))
    stub = Stub()
    result = roles.invoke(built, "Check input", client=stub)
    assert not result and result.error == "execution_requirements_unenforceable:tool_allowlist"
    result = roles.invoke(built, "Check input", requirements={"access": "workspace_write"}, client=stub)
    assert result.error == "source_permissions_cannot_be_weakened"
    assert stub.calls == []


@pytest.mark.parametrize("requested, mode, extra", [
    ({"access": "read_only"}, "judge", {"mcp_isolation": True}),
    (LegacyRequirements(access="read_only", tool_network="forbidden"), "judge",
     {"web_search": False, "mcp_isolation": True}),
    ({"access": "workspace_write", "tool_network": "required"}, "agent", {"web_search": True}),
])
def test_enforceable_requirements_run_only_on_sandboxed_rungs(tmp_path, requested, mode, extra):
    built = overlays.build(source(tmp_path, "Role", kind="agent_template"), "codex", caps("llmcall.agent"))
    stub = Stub()
    assert roles.invoke(built, "Task", requirements=requested, client=stub)
    options = stub.calls[0][1]
    assert options["chain"] == ["codexg", "codex"] and options["mode"] == mode
    assert {k: options[k] for k in extra} == extra
    # Read-only asks llmcall to drop Codex MCP servers (a sandboxed judge keeps them otherwise);
    # an agent keeps its tools, and llmcall ignores the request for agent calls anyway.
    assert ("mcp_isolation" in options) is (mode == "judge")


def test_control_no_requirements_keeps_configured_mcp(tmp_path):
    built = overlays.build(source(tmp_path, "Role", kind="agent_template"), "codex", caps("llmcall.agent"))
    stub = Stub()
    assert roles.invoke(built, "Task", client=stub)
    assert "mcp_isolation" not in stub.calls[0][1]


def test_requirements_without_a_sandboxed_rung_fail_closed(tmp_path):
    built = overlays.build(source(tmp_path, "Role", kind="agent_template"), "codex", caps("llmcall.agent"))
    stub = Stub(ladder=("cc", "claude"))
    result = roles.invoke(built, "Task", requirements={"access": "read_only"}, client=stub)
    assert result.error == "execution_requirements_unenforceable:no_sandboxed_rung" and not stub.calls
    # Negative control: the same client runs when nothing is required.
    assert roles.invoke(built, "Task", client=stub) and len(stub.calls) == 1


@pytest.mark.parametrize("kind, reason", [
    ("cwd", "workspace_requires_process_cwd"),
    ("env", "environment_override_unsupported:SYNTHETIC_OVERRIDE"),
    ("cancelled", "cancelled"),
    ("opaque-cancel", "invalid_cancellation"),
])
def test_per_call_context_llmcall_cannot_honour_is_refused(tmp_path, kind, reason):
    built = overlays.build(source(tmp_path, "Role", kind="agent_template"), "codex", caps("llmcall.agent"))
    stub = Stub()
    event = threading.Event()
    event.set()
    options = {"cwd": {"cwd": str(tmp_path / "elsewhere")}, "env": {"env": {"SYNTHETIC_OVERRIDE": "1"}},
               "cancelled": {"cancel": event}, "opaque-cancel": {"cancel": object()}}[kind]
    result = roles.invoke(built, "Task", client=stub, **options)
    assert not result and result.error == reason and not stub.calls


def test_context_matching_this_process_is_allowed(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTHETIC_PRESENT", "1")
    monkeypatch.delenv("SYNTHETIC_ABSENT", raising=False)
    built = overlays.build(source(tmp_path, "Role", kind="agent_template"), "codex", caps("llmcall.agent"))
    stub = Stub()
    result = roles.invoke(built, "Task", cwd=str(tmp_path), cancel=threading.Event(), client=stub,
                          env={"SYNTHETIC_PRESENT": "1", "SYNTHETIC_ABSENT": None})
    assert result and len(stub.calls) == 1


def workflow(tmp_path, body=None):
    body = body or ('```yaml\nspawn_agent:\n  message: First round\n  model: source-pin\n```\n'
                    '```yaml\nsend_input:\n  id: returned-id\n  message: Second round\n```\n'
                    '```yaml\nmcp__claude-review__review_status:\n  jobId: completed-job\n  waitSeconds: 1\n```')
    return overlays.build(source(tmp_path, body), "codex", caps("llmcall.contexts", "llmcall.permissions"),
                          workflow_kind="review")


def test_multiround_passes_all_information_independence_and_cancellation(tmp_path):
    built = workflow(tmp_path)
    assert built["status"] == "ready", built
    stub = Stub()
    session = roles.WorkflowSession(built, client=stub, inherited={"chain": ["policy-route"], "effort": "high"})
    cancellation = threading.Event()
    first = session.run_step(0, producer=producer(), inputs={"paper": "a" * 9000}, exact_model="exact-review", cancel=cancellation, timeout=19)
    second = session.run_step(1, inputs={"revision": "Complete revised content"}, exact_model="exact-review", cancel=cancellation, timeout=19)
    assert first and second
    prompt, options = stub.calls[1]
    assert "a" * 9000 in prompt and first.text in prompt and "Complete revised content" in prompt
    assert "Complete producer output" in prompt
    assert options["avoid"] == "author-group"
    assert options["model"] == "exact-review" and options["gateway_best"] is False
    assert options["chain"] == ["policy-route"] and options["effort"] == "high"
    assert options["timeout"] == 19 and "cancel" not in options
    assert session.run_step(2) is second
    assert session.run_step(1) is second
    assert len(stub.calls) == 2


@pytest.mark.parametrize("kind", ["unknown-producer", "same-group", "unknown-reviewer"])
def test_independence_uses_actual_result_contract(tmp_path, kind):
    stub = Stub()
    origin = producer()
    if kind == "unknown-producer":
        origin.group = None
    elif kind == "same-group":
        stub.group = origin.group
    else:
        stub.group = None
    session = roles.WorkflowSession(workflow(tmp_path), client=stub)
    result = session.run_step(0, producer=origin)
    assert not result and result.error == "independent_reviewer_unavailable"
    assert len(stub.calls) == (0 if kind == "unknown-producer" else 1)


def test_sandboxed_review_cannot_avoid_its_only_group(tmp_path):
    body = '```yaml\nspawn_agent:\n  message: Review\n  sandbox: read-only\n```'
    stub = Stub()
    session = roles.WorkflowSession(workflow(tmp_path, body), client=stub)
    result = session.run_step(0, producer=producer(group="codex"))
    assert result.error == "independent_reviewer_unavailable" and not stub.calls
    fresh = roles.WorkflowSession(workflow(tmp_path, body), client=stub)
    assert fresh.run_step(0, producer=producer(group="claude"))
    options = stub.calls[0][1]
    assert options["chain"] == ["codexg", "codex"] and options["mode"] == "judge" and options["avoid"] == "claude"


def test_distinct_contexts_cannot_implicitly_share_reply(tmp_path):
    body = ('```yaml\nspawn_agent:\n  context: one\n  message: First\n```\n'
            '```yaml\nspawn_agent:\n  context: two\n  message: Second\n```\n'
            '```yaml\nsend_input:\n  id: unknown\n  message: Reply\n```')
    assert overlays.build(source(tmp_path, body), "codex", caps("llmcall.contexts"), workflow_kind="review")["status"] == "unsupported"


def test_coverage_accounts_for_seven_native_and_three_restricted_without_invocation(tmp_path):
    records = []
    for plugin, name in roles.NATIVE_ROLES + roles.RESTRICTED_ROLES:
        metadata = 'tools: ["Read"]\n' if (plugin, name) in roles.RESTRICTED_ROLES else "model: source-pin\n"
        records.append(source(tmp_path / plugin / name, "Synthetic role", kind="agent_template", name=name, metadata=metadata, plugin=plugin))
    custom = source(tmp_path / "custom", "Custom source", kind="agent_template", name="custom", plugin="custom")
    snapshot = {"schema_version": 1, "records": [*records, custom]}
    before = json.dumps(snapshot, sort_keys=True)
    rows = roles.coverage_descriptors(snapshot, caps("llmcall.agent"))
    assert len(rows) == 10
    assert sum(row["native_seven"] for row in rows) == 7
    assert sum(row["restricted"] for row in rows) == 3
    assert all(row["status"] == "blocked" for row in rows if row["restricted"])
    assert all(row["status"] == "ready" for row in rows if row["native_seven"])
    assert all(row["invocations"] == 0 for row in rows)
    assert json.dumps(snapshot, sort_keys=True) == before


def test_stale_template_blocks_before_llmcall(tmp_path):
    built = overlays.build(source(tmp_path, "Original", kind="agent_template"), "codex", caps("llmcall.agent"))
    Path(built["source_file"]).write_text("Changed", encoding="utf-8")
    stub = Stub()
    assert not roles.invoke(built, "Task", client=stub)
    assert stub.calls == []


def test_workflow_frontmatter_restrictions_cannot_disappear(tmp_path):
    rec = source(tmp_path, '```yaml\nspawn_agent:\n  message: Review\n```', metadata='allowed-tools: ["Read"]\n')
    built = overlays.build(rec, "codex", caps("llmcall.contexts", "llmcall.permissions"), workflow_kind="review")
    stub = Stub()
    result = roles.WorkflowSession(built, client=stub).run_step(0, producer=producer())
    assert result.error == "execution_requirements_unenforceable:tool_allowlist"
    assert stub.calls == []


def test_failed_round_cannot_be_retried_or_skipped_into_followup(tmp_path):
    stub = Stub()
    stub.group = "author-group"
    session = roles.WorkflowSession(workflow(tmp_path), client=stub)
    result = session.run_step(0, producer=producer())
    assert not result
    assert session.run_step(0) is result
    assert session.run_step(1).error == "workflow_previous_step_failed"
    assert len(stub.calls) == 1


def test_context_keeps_user_selection_and_permissions_across_rounds(tmp_path):
    stub = Stub()
    session = roles.WorkflowSession(workflow(tmp_path), client=stub)
    req = {"tool_network": "forbidden"}
    assert session.run_step(0, producer=producer(), exact_model="chosen-model", effort="medium", requirements=req)
    assert session.run_step(1)
    options = stub.calls[1][1]
    assert options["model"] == "chosen-model" and options["gateway_best"] is False
    assert options["effort"] == "medium"
    assert options["chain"] == ["codexg", "codex"] and options["web_search"] is False and options["mode"] == "judge"
    stored = session.contexts["review-0"]["requirements"]
    assert stored["workspace"] == str(tmp_path) and stored["tool_network"] == "forbidden"


def test_agent_context_forbids_a_judge_followup(tmp_path):
    stub = Stub()
    session = roles.WorkflowSession(workflow(tmp_path), client=stub)
    assert session.run_turn(context="work", operation="start", prompt="Change it", mode="agent",
                            independent_review=False)
    assert session.last_effects == "possible"
    result = session.run_turn(context="work", operation="reply", prompt="Judge it", mode="judge",
                              independent_review=False)
    assert result.error == "agent_replay_forbidden" and len(stub.calls) == 1
    assert session.last_effects == "none"


def test_agent_effects_follow_whether_a_client_started():
    assert roles.call_effects(Result(attempts=[Attempt("codex", False, reason="not_installed")]), "agent") == "none"
    assert roles.call_effects(Result(attempts=[Attempt("codex", False, reason="timeout")]), "agent") == "possible"
    assert roles.call_effects(Result(text="x", provider="codex"), "judge") == "none"
