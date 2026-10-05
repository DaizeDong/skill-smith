"""T10 producer checks. All source files are generated synthetic fixtures."""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from tools.make_fixtures import text_file
from skill_smith import conflicts, overlays


def source(root, body, *, kind="skill", name="demo", metadata="", plugin="demo"):
    path = root / "skills" / name / "SKILL.md"
    raw = "---\nname: " + name + "\ndescription: Synthetic fixture.\n" + metadata + "---\n" + body
    text_file(path, raw)
    digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    ep = {"source_id": "plugin:synthetic-" + plugin, "kind": kind, "name": name,
          "relative_path": "skills/" + name + "/SKILL.md", "resolved_path": str(path),
          "client": "codex", "scope": "user", "source_hash": digest}
    return {"source_id": ep["source_id"], "kind": "plugin", "source_hash": digest,
            "registry_key": plugin + "@claude-plugins-official", "resolved_path": str(root),
            "status": {"resolved": "yes", "enabled": "yes"}, "entrypoints": [ep]}


def caps(*names):
    return {"capabilities": {name: {"status": "supported", "evidence": ["synthetic-test"]} for name in names}}


def rule(rec, name, *, tier="main", formats=None, requires=None):
    return {"id": name, "selector": {"source_id": rec["source_id"], "kind": "skill"},
            "tasks": ["spreadsheet"], "tier": tier, "formats": formats or [], "requires": requires or []}


def test_resource_resolution_preserves_source_layout_and_plugin_root(tmp_path):
    rec = source(tmp_path, "Read [guide](../../references/guide.md#part) and `scripts/run.py`.\nUse `${CLAUDE_PLUGIN_ROOT}/assets`.\n")
    text_file(tmp_path / "references/guide.md", "Synthetic guide")
    text_file(tmp_path / "skills/demo/scripts/run.py", "print('synthetic')")
    text_file(tmp_path / "assets/input.txt", "Synthetic asset")
    built = overlays.build(rec, "codex", caps("llmcall.contexts"), workflow_kind="review")
    assert built["status"] == "ready", built
    assert len(built["resources"]) == 3
    assert "../../references/guide.md#part" in built["template"]
    assert overlays.validate(built, record=rec, target_runtime="codex")
    assert not overlays.validate(built, target_runtime="claude")
    text_file(tmp_path / "assets/new.txt", "new resource")
    assert not overlays.validate(built)


def test_source_drift_and_transform_drift_invalidate(tmp_path):
    rec = source(tmp_path, "Synthetic body")
    built = overlays.build(rec, "codex", caps("llmcall.contexts"), workflow_kind="review")
    changed = copy.deepcopy(built)
    changed["transform_version"] = "unknown"
    assert not overlays.validate(changed)
    changed_rec = dict(rec, source_hash="sha256:" + "0" * 64)
    assert not overlays.validate(built, record=changed_rec)
    text_file(Path(built["source_file"]), "Changed source")
    assert not overlays.validate(built)
    assert overlays.build(rec, "codex", caps("llmcall.contexts"), workflow_kind="review")["reasons"] == ["source_drift"]


@pytest.mark.parametrize("body", [
    "```yaml\nspawn_agent:\n  message: review\n  unexpected: lose-me\n```",
    "```yaml\nspawn_agent:\n  message: review\n  fork_context: true\n```",
    "```yaml\nmcp__unknown__review:\n  prompt: review\n```",
    "```python\nspawn_agent(message='unknown call grammar')\n```",
    "```yaml\nmcp__codex__codex:\n  prompt: review\n  approval-policy: never\n```",
    "Use codex exec resume --last to continue.",
    '```yaml\nspawn_agent:\n  message: Review\n  developer-instructions: Preserve hierarchy\n```',
    "Read [outside](../../../escape.md).",
    "Read [missing](scripts/missing.py).",
])
def test_unknown_or_unenforceable_constructs_are_unsupported(tmp_path, body):
    built = overlays.build(source(tmp_path, body), "codex", caps("llmcall.contexts"), workflow_kind="review")
    assert built["status"] == "unsupported", built
    assert "template" not in built


def test_native_calls_are_structural_and_parameters_are_not_globally_replaced(tmp_path):
    body = ('Keep the word model in ordinary prose.\n```yaml\nspawn_agent:\n  model: source-model\n'
            '  reasoning_effort: high\n  message: |\n    First round\n    Complete context\n```\n'
            '```yaml\nsend_input:\n  id: returned-agent-id\n  message: Follow up\n```')
    built = overlays.build(source(tmp_path, body), "codex", caps("llmcall.contexts"), workflow_kind="review")
    assert built["status"] == "ready", built
    first, second = built["steps"]
    assert first["context"] == second["context"]
    assert first["source_parameters"]["model"] == "source-model"
    assert first["prompt"] == "First round\nComplete context"
    assert first["model_policy"] == "inherit_or_user_exact"
    assert "Keep the word model in ordinary prose." in built["template"]
    assert overlays.validate(built)


def test_ambiguous_primary_is_not_sorted_into_a_winner(tmp_path):
    one = source(tmp_path / "one", "One", plugin="one")
    two = source(tmp_path / "two", "Two", plugin="two")
    policy = {"schema_version": 1, "entries": [rule(one, "first"), rule(two, "second")]}
    snapshot = {"schema_version": 1, "records": [one, two]}
    original = copy.deepcopy((policy, snapshot))
    result = conflicts.select({"task": "spreadsheet"}, caps(), policy, snapshot)
    assert result["status"] == "ambiguous"
    policy["entries"][1]["tier"] = "fallback"
    assert conflicts.select({"task": "spreadsheet"}, caps(), policy, snapshot)["selection"]["policy_id"] == "first"
    policy["entries"][1]["tier"] = "main"
    assert (policy, snapshot) == original


def test_override_bypasses_applicability_but_not_capabilities(tmp_path):
    one = source(tmp_path / "one", "One", plugin="one")
    two = source(tmp_path / "two", "Two", plugin="two")
    policy = {"schema_version": 1, "entries": [rule(one, "main"), rule(two, "explicit", tier="fallback", requires=["image"]) ]}
    snapshot = {"schema_version": 1, "records": [one, two]}
    request = {"task": "unrelated", "override": "explicit"}
    assert conflicts.select(request, caps(), policy, snapshot)["status"] == "blocked"
    unknown = {"capabilities": {"image": {"status": "supported"}}}
    assert conflicts.select(request, unknown, policy, snapshot)["status"] == "blocked"
    assert conflicts.select(request, caps("image"), policy, snapshot)["selection"]["policy_id"] == "explicit"
    assert conflicts.select({"override": "missing"}, caps(), policy, snapshot)["status"] == "unavailable"


def test_unknown_capability_and_disabled_source_do_not_become_primary(tmp_path):
    one = source(tmp_path / "one", "One", plugin="one")
    two = source(tmp_path / "two", "Two", plugin="two")
    policy = {"schema_version": 1, "entries": [rule(one, "main", requires=["render"]), rule(two, "fallback", tier="fallback")]}
    snapshot = {"schema_version": 1, "records": [one, two]}
    assert conflicts.select({"task": "spreadsheet"}, caps(), policy, snapshot)["selection"]["policy_id"] == "fallback"
    two["status"]["enabled"] = "no"
    assert conflicts.select({"task": "spreadsheet"}, caps(), policy, snapshot)["status"] == "blocked"


def test_explicit_format_beats_generic_primary_without_removing_it(tmp_path):
    one = source(tmp_path / "primary", "Generic", plugin="primary")
    two = source(tmp_path / "format", "Specialist", plugin="format")
    policy = {"schema_version": 1, "entries": [rule(one, "primary"), rule(two, "xlsx", tier="specialist", formats=["xlsx"])]}
    snapshot = {"schema_version": 1, "records": [one, two]}
    assert conflicts.select({"task": "spreadsheet"}, caps(), policy, snapshot)["selection"]["policy_id"] == "primary"
    selected = conflicts.select({"task": "spreadsheet", "format": "xlsx"}, caps(), policy, snapshot)
    assert selected["selection"]["policy_id"] == "xlsx" and len(selected["candidates"]) == 2
    assert conflicts.select({"task": "spreadsheet", "format": "xlsx", "override": "primary"}, caps(), policy, snapshot)["selection"]["policy_id"] == "primary"


def test_shared_resource_root_must_be_explicit_and_stays_pinned(tmp_path):
    rec = source(tmp_path / "package", "Read `../../../shared-references/guide.md`.")
    text_file(tmp_path / "shared-references/guide.md", "Synthetic shared protocol")
    assert overlays.build(rec, "codex", caps("llmcall.contexts"), workflow_kind="review")["status"] == "unsupported"
    built = overlays.build(rec, "codex", caps("llmcall.contexts"), resource_root=tmp_path)
    assert built["status"] == "ready", built
    assert overlays.validate(built)
    text_file(tmp_path / "shared-references/guide.md", "Changed protocol")
    assert not overlays.validate(built)


def test_mcp_start_reply_and_saved_target_map_to_explicit_context(tmp_path):
    body = ('```yaml\nmcp__codex__codex:\n  prompt: Review\n  config: {"model_reasoning_effort": "high"}\n```\n'
            '```text\nsend_input:\n  target: [saved reviewer id from Step 2]\n  message: Follow up\n```\n'
            '```yaml\nmcp__codex__codex-reply:\n  threadId: saved-thread\n  prompt: Final follow up\n```')
    built = overlays.build(source(tmp_path, body), "claude", caps("llmcall.contexts"), workflow_kind="review")
    assert built["status"] == "ready", built
    assert [step["operation"] for step in built["steps"]] == ["start", "reply", "reply"]
    assert len({step["context"] for step in built["steps"]}) == 1


def test_sandbox_without_permission_evidence_stays_blocked(tmp_path):
    body = '```yaml\nmcp__codex__codex:\n  prompt: Review\n  sandbox: read-only\n```'
    built = overlays.build(source(tmp_path, body), "codex", caps("llmcall.contexts"), workflow_kind="review")
    assert built["status"] == "blocked"
    assert built["steps"][0]["requirements"]["access"] == "read_only"


def test_agent_work_is_not_silently_converted_to_text_review(tmp_path):
    rec = source(tmp_path, '```yaml\nspawn_agent:\n  message: Edit files\n```')
    result = overlays.build(rec, "codex", caps("llmcall.contexts"))
    assert result["status"] == "unsupported"
    assert result["reasons"] == ["explicit_review_workflow_contract_required"]


def test_optional_unmapped_review_route_blocks_whole_overlay(tmp_path):
    rec = source(tmp_path, 'Alternatively use oracle-pro.\n```yaml\nspawn_agent:\n  message: Review\n```')
    result = overlays.build(rec, "codex", caps("llmcall.contexts"), workflow_kind="review")
    assert result["status"] == "unsupported"
    assert "template" not in result
