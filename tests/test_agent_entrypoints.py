"""Synthetic llmcall stub only; no provider transports, agents or CLI calls."""
from dataclasses import dataclass
from pathlib import Path
import json

import pytest
from test_runtime_overlays import source, caps
from skill_smith import overlays, role_entrypoints as roles


@dataclass
class Selection:
    intent: str = "inherit"
    model: str | None = None


@dataclass
class Requirements:
    workspace: str | None = None
    access: str = "read_only"
    tool_network: str = "default"
    required_tools: tuple = ()
    required_mcp: tuple = ()
    tool_allowlist: tuple | None = None
    replay: str = "never_after_start"


@dataclass
class Result:
    text: str = ""
    provider: str | None = None
    model_source: str = "unknown"
    model_family: str | None = None
    effective_model: str | None = None
    error: str | None = None
    outcome: str | None = None
    execution_started: bool = False
    effects: str = "none"

    def __bool__(self):
        return self.provider is not None


class Stub:
    Result = Result
    ExecutionRequirements = Requirements
    ModelSelection = Selection

    def __init__(self):
        self.calls = []
        self.family = "review-family"
        self.model_source = "provider_reported"
        self.refuse_permissions = False

    def call(self, prompt, **options):
        self.calls.append((prompt, options))
        if self.refuse_permissions and options.get("requirements") is not None:
            return Result(error="capability_unavailable", outcome="capability_unavailable")
        return Result(text="Synthetic response " + str(len(self.calls)), provider="stub",
                      model_source=self.model_source, model_family=self.family,
                      effective_model="synthetic-model", outcome="success", execution_started=True)


def producer():
    return Result(text="Complete producer output", provider="stub", model_source="provider_reported", model_family="author-family")


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
    assert options["selection"] == Selection("exact", "user-exact-model")
    assert options["chain"] == ["session-route"] and options["effort"] == "medium"
    assert options["mode"] == "agent"
    assert "model" not in options


def test_role_inherits_without_a_new_provider_chain(tmp_path):
    built = overlays.build(source(tmp_path, "Role", kind="agent_template"), "codex", caps("llmcall.agent"))
    stub = Stub()
    roles.invoke(built, "Task", client=stub)
    assert "chain" not in stub.calls[0][1] and "selection" not in stub.calls[0][1]
    roles.invoke(built, "Task", inherited={"model": "session-model", "effort": "high"}, client=stub)
    assert stub.calls[1][1]["selection"] == Selection("prefer", "session-model")


def test_restricted_permissions_reach_llmcall_and_never_degrade(tmp_path):
    rec = source(tmp_path, "Read synthetic input.", kind="agent_template", metadata='tools: ["Read", "Grep", "Glob"]\n')
    built = overlays.build(rec, "codex", caps("llmcall.agent", "llmcall.permissions"))
    stub = Stub()
    stub.refuse_permissions = True
    result = roles.invoke(built, "Check input", client=stub)
    assert result.outcome == "capability_unavailable"
    assert len(stub.calls) == 1
    req = stub.calls[0][1]["requirements"]
    assert req.tool_allowlist == ("Read", "Grep", "Glob") and req.access == "read_only"
    result = roles.invoke(built, "Check input", requirements=Requirements(access="workspace_write"), client=stub)
    assert result.outcome == "source_permissions_cannot_be_weakened"
    assert len(stub.calls) == 1


def workflow(tmp_path):
    body = ('```yaml\nspawn_agent:\n  message: First round\n  model: source-pin\n```\n'
            '```yaml\nsend_input:\n  id: returned-id\n  message: Second round\n```\n'
            '```yaml\nmcp__claude-review__review_status:\n  jobId: completed-job\n  waitSeconds: 1\n```')
    return overlays.build(source(tmp_path, body), "codex", caps("llmcall.contexts"), workflow_kind="review")


def test_multiround_passes_all_information_independence_and_cancellation(tmp_path):
    built = workflow(tmp_path)
    assert built["status"] == "ready", built
    stub = Stub()
    session = roles.WorkflowSession(built, client=stub, inherited={"chain": ["policy-route"], "effort": "high"})
    cancellation = object()
    first = session.run_step(0, producer=producer(), inputs={"paper": "a" * 9000}, exact_model="exact-review", cancel=cancellation, timeout=19)
    second = session.run_step(1, inputs={"revision": "Complete revised content"}, exact_model="exact-review", cancel=cancellation, timeout=19)
    assert first and second
    prompt, options = stub.calls[1]
    assert "a" * 9000 in prompt and first.text in prompt and "Complete revised content" in prompt
    assert "Complete producer output" in prompt
    assert options["avoid"] == "author-family"
    assert options["selection"] == Selection("exact", "exact-review")
    assert options["chain"] == ["policy-route"] and options["effort"] == "high"
    assert options["cancel"] is cancellation and options["timeout"] == 19
    assert session.run_step(2) is second
    assert session.run_step(1) is second
    assert len(stub.calls) == 2


@pytest.mark.parametrize("kind", ["unknown-producer", "same-family", "unknown-reviewer"])
def test_independence_uses_actual_result_contract(tmp_path, kind):
    stub = Stub()
    origin = producer()
    if kind == "unknown-producer":
        origin.model_source = "configured"
    elif kind == "same-family":
        stub.family = origin.model_family
    else:
        stub.model_source = "configured"
    session = roles.WorkflowSession(workflow(tmp_path), client=stub)
    result = session.run_step(0, producer=origin)
    assert not result and result.outcome == "independent_reviewer_unavailable"
    assert len(stub.calls) == (0 if kind == "unknown-producer" else 1)


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
    from pathlib import Path
    Path(built["source_file"]).write_text("Changed", encoding="utf-8")
    stub = Stub()
    assert not roles.invoke(built, "Task", client=stub)
    assert stub.calls == []


def test_workflow_frontmatter_restrictions_cannot_disappear(tmp_path):
    rec = source(tmp_path, '```yaml\nspawn_agent:\n  message: Review\n```', metadata='allowed-tools: ["Read"]\n')
    built = overlays.build(rec, "codex", caps("llmcall.contexts", "llmcall.permissions"), workflow_kind="review")
    stub = Stub()
    stub.refuse_permissions = True
    result = roles.WorkflowSession(built, client=stub).run_step(0, producer=producer())
    assert result.outcome == "capability_unavailable"
    assert stub.calls[0][1]["requirements"].tool_allowlist == ("Read",)


def test_failed_round_cannot_be_retried_or_skipped_into_followup(tmp_path):
    stub = Stub()
    stub.family = "author-family"
    session = roles.WorkflowSession(workflow(tmp_path), client=stub)
    result = session.run_step(0, producer=producer())
    assert not result
    assert session.run_step(0) is result
    assert session.run_step(1).outcome == "workflow_previous_step_failed"
    assert len(stub.calls) == 1


def test_context_keeps_user_selection_and_permissions_across_rounds(tmp_path):
    stub = Stub()
    session = roles.WorkflowSession(workflow(tmp_path), client=stub)
    req = Requirements(tool_network="forbidden", tool_allowlist=("Read",))
    assert session.run_step(0, producer=producer(), exact_model="chosen-model", effort="medium", requirements=req)
    assert session.run_step(1)
    options = stub.calls[1][1]
    assert options["selection"] == Selection("exact", "chosen-model")
    assert options["effort"] == "medium"
    from dataclasses import replace
    assert Path(options['cwd']).is_absolute()
    assert options['requirements'].workspace == options['cwd']
    assert replace(options['requirements'], workspace=None) == req
