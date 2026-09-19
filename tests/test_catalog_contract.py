"""Public catalog contract; all files are generated synthetic inputs."""
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from tools.make_fixtures import external, plugins, skill, text_file, write_json


def discover(request):
    assert importlib.util.find_spec("skill_smith"), "catalog package has not been implemented"
    from skill_smith.catalog import discover as implementation
    return implementation(request)


def test_unconfigured_sources_are_unchecked_not_a_trusted_empty_catalog():
    snapshot = discover({})
    assert snapshot["schema_version"] == 1
    assert snapshot["records"] == []
    assert set(snapshot["coverage"]) == {
        "external_skill_repos", "skill_roots", "repo_roots", "plugin_registries",
        "private_bindings", "runtime_discovery", "workflow_roots", "plugin_descriptors",
    }
    assert all(c["status"] == "unchecked" for c in snapshot["coverage"].values())
    assert all(value == "unknown" for value in snapshot["status"].values())


def test_plugin_identity_keeps_marketplace_client_scope_and_selected_version(tmp_path):
    request = plugins(tmp_path)
    descriptor = request["plugin_registries"][0]
    extra = copy.deepcopy(descriptor)
    extra["client"] = "codex"
    request["plugin_registries"].append(extra)
    data = json.loads(Path(descriptor["path"]).read_text())
    rec = copy.deepcopy(data["plugins"]["demo@market-b"][0])
    rec["scope"] = "project"
    rec["projectPath"] = str(tmp_path / "project")
    data["plugins"]["demo@market-b"].append(rec)
    write_json(descriptor["path"], data)
    snapshot = discover(request)
    records = [r for r in snapshot["records"] if r["kind"] == "plugin"]
    assert len(records) == 6
    assert len({r["source_id"] for r in records}) == 6
    assert {r["registry_key"] for r in records} == {"demo@market-a", "demo@market-b"}
    disabled = next(r for r in records if r["registry_key"] == "demo@market-a")
    assert disabled["version"] == "1"
    assert disabled["status"]["enabled"] == "no"
    assert disabled["status"]["cached"] == "yes"
    assert disabled["status"]["installed"] == "yes"
    assert disabled["status"]["discovered"] == "unknown"
    assert disabled["status"]["compatible"] == "unknown"
    assert "authenticated" not in disabled["status"]
    assert all(ep["name"] != "stale" for r in records for ep in r["entrypoints"])


def test_conflicting_versions_in_one_scope_are_ambiguous_not_latest(tmp_path):
    request = plugins(tmp_path)
    path = request["plugin_registries"][0]["path"]
    data = json.loads(Path(path).read_text())
    conflicting = copy.deepcopy(data["plugins"]["demo@market-a"][0])
    conflicting["version"] = "99"
    conflicting["installPath"] = str(tmp_path / "cache" / "market-a" / "99")
    data["plugins"]["demo@market-a"].append(conflicting)
    write_json(path, data)
    snapshot = discover(request)
    record = next(r for r in snapshot["records"] if r["registry_key"] == "demo@market-a")
    assert record["resolution"] == "ambiguous"
    assert record["status"]["resolved"] == "unknown"
    assert not record["entrypoints"]
    assert snapshot["coverage"]["plugin_registries"]["status"] == "partial"


def test_source_identity_survives_revision_changes_and_root_relocation(tmp_path):
    first_request = external(tmp_path / "first")
    second_request = external(tmp_path / "second")
    for request in (first_request, second_request):
        root = Path(request["profile_home"])
        skill(root / "repos/demo-kit/skills/invoice", "source-name")
        skill(root / "vendor/local-copy", "vendored-name")
    first = discover(first_request)
    path = second_request["external_skill_repos"]
    data = json.loads(Path(path).read_text())
    data["vendored"][0]["commit"] = "b" * 40
    write_json(path, data)
    skill(Path(second_request["profile_home"]) / "vendor/local-copy", "vendored-name", "Changed text.")
    second = discover(second_request)
    one = {r["source_id"]: r for r in first["records"]}
    two = {r["source_id"]: r for r in second["records"]}
    assert one.keys() == two.keys()
    vendored_id = next(k for k, r in one.items() if r["origin"]["type"] == "vendored")
    assert one[vendored_id]["version"] != two[vendored_id]["version"]
    assert one[vendored_id]["source_hash"] != two[vendored_id]["source_hash"]


def test_snapshot_is_json_read_only_and_request_is_not_mutated(tmp_path):
    request = plugins(tmp_path)
    before_request = copy.deepcopy(request)
    before_files = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    snapshot = discover(request)
    assert json.loads(json.dumps(snapshot)) == snapshot
    assert request == before_request
    assert before_files == {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    for record in snapshot["records"]:
        assert {"source_id", "kind", "origin", "registry_key", "relative_path", "version",
                "source_hash", "entrypoints", "dependencies", "status"} <= record.keys()
        assert set(record["status"].values()) <= {"yes", "no", "unknown", "not_applicable"}
        assert all(e["observed_at"] for e in record["evidence"].values())


def test_authentication_is_per_binding_and_secrets_are_not_copied(tmp_path):
    request = plugins(tmp_path)
    request["private_bindings"] = write_json(tmp_path / "bindings.json", {"bindings": [
        {"id": "acme-mail", "kind": "app_connector", "connector": "mail",
         "authenticated": "yes", "token": "FAKE_CANARY_SECRET"},
        {"id": "acme-calendar", "kind": "mcp_binding", "server": "calendar",
         "authenticated": "unknown", "env": {"KEY": "FAKE_CANARY_SECRET"}},
    ]})
    snapshot = discover(request)
    records = {r["binding_id"]: r for r in snapshot["records"] if "binding_id" in r}
    assert records["acme-mail"]["status"]["authenticated"] == "yes"
    assert records["acme-calendar"]["status"]["authenticated"] == "unknown"
    assert "FAKE_CANARY_SECRET" not in json.dumps(snapshot)


def test_explicit_runtime_evidence_only_updates_the_exact_entrypoint(tmp_path):
    request = plugins(tmp_path)
    original = discover(request)
    record = next(r for r in original["records"] if r["registry_key"] == "demo@market-b")
    ep = record["entrypoints"][0]
    request["runtime_discovery"] = write_json(tmp_path / "runtime.json", {"entrypoints": [
        {"source_id": record["source_id"], "kind": ep["kind"], "name": ep["name"],
         "client": ep["client"], "scope": ep["scope"], "discovered": "yes",
         "compatible": "no", "observed_at": "2026-01-01T00:00:00Z"},
    ]})
    observed = discover(request)
    updated = next(r for r in observed["records"] if r["source_id"] == record["source_id"])
    assert updated["entrypoints"][0]["status"]["discovered"] == "yes"
    assert updated["entrypoints"][0]["status"]["compatible"] == "no"
    other = next(r for r in observed["records"] if r["registry_key"] == "demo@market-a")
    assert other["status"]["discovered"] == "unknown"


def test_malformed_or_missing_input_is_reported_as_partial(tmp_path):
    bad = tmp_path / "bad.json"
    text_file(bad, "{broken")
    invalid_shape = write_json(tmp_path / "shape.json", [])
    for path in (str(bad), str(tmp_path / "absent.json"), invalid_shape):
        snapshot = discover({"external_skill_repos": path, "profile_home": str(tmp_path)})
        assert snapshot["coverage"]["external_skill_repos"]["status"] == "partial"
        assert snapshot["problems"]


def test_cli_reads_request_from_stdin_without_writing_files(tmp_path):
    discover({})
    package_parent = Path(__file__).resolve().parents[1] / "skills/skill-smith/scripts"
    result = subprocess.run([sys.executable, "-m", "skill_smith"], input="{}", cwd=package_parent,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["coverage"]["skill_roots"]["status"] == "unchecked"


def test_bad_declaration_does_not_hide_later_valid_sources(tmp_path):
    request = external(tmp_path)
    path = request["external_skill_repos"]
    data = json.loads(Path(path).read_text())
    data["repos"].insert(0, {"dir": "broken"})
    write_json(path, data)
    skill(tmp_path / "repos/demo-kit/skills/invoice", "source-name")
    snapshot = discover(request)
    assert any(r.get("name") == "source-name" for r in snapshot["records"])
    assert snapshot["coverage"]["external_skill_repos"]["status"] == "partial"


def test_malformed_collection_shapes_are_partial_instead_of_raising(tmp_path):
    cases = [
        {"skill_roots": {}},
        {"repo_roots": [None]},
        {"plugin_registries": [{"path": write_json(tmp_path / "registry.json", {"plugins": {"demo@market": []}})}]},
        {"private_bindings": write_json(tmp_path / "bindings.json", {"bindings": "wrong"})},
        {"runtime_discovery": write_json(tmp_path / "runtime.json", {"entrypoints": [None]})},
    ]
    for request in cases:
        snapshot = discover(request)
        stage = next(iter(request))
        assert snapshot["coverage"][stage]["status"] == "partial", request
        assert snapshot["problems"]


def test_commands_agents_and_mcp_bindings_remain_typed_without_copying_config(tmp_path):
    request = plugins(tmp_path)
    selected = tmp_path / "cache/market-b/2"
    (selected / "commands").mkdir()
    text_file(selected / "commands/check.md", "---\ndescription: Check synthetic input.\n---\nBody.")
    (selected / "agents").mkdir()
    text_file(selected / "agents/reviewer.md", "---\nname: reviewer\ndescription: Review input.\n---\nBody.")
    write_json(selected / ".mcp.json", {"mcpServers": {
        "calendar": {"command": "fake-server", "env": {"TOKEN": "FAKE_CANARY_SECRET"}},
        "mail": {"url": "https://example.com/mcp", "headers": {"Authorization": "FAKE_CANARY_SECRET"}},
    }})
    snapshot = discover(request)
    plugin = next(r for r in snapshot["records"] if r["kind"] == "plugin" and r["registry_key"] == "demo@market-b")
    assert {e["kind"] for e in plugin["entrypoints"]} == {"skill", "command", "agent_template"}
    bindings = [r for r in snapshot["records"] if r["kind"] == "mcp_binding"]
    assert {r["server"] for r in bindings} == {"calendar", "mail"}
    assert all(r["status"]["authenticated"] == "unknown" for r in bindings)
    assert {d["source_id"] for d in plugin["dependencies"]} == {r["source_id"] for r in bindings}
    assert "FAKE_CANARY_SECRET" not in json.dumps(snapshot)


def test_invalid_enabled_plugins_does_not_claim_enabled_or_crash(tmp_path):
    request = plugins(tmp_path)
    write_json(request["plugin_registries"][0]["settings_path"], {"enabledPlugins": []})
    snapshot = discover(request)
    assert snapshot["coverage"]["plugin_registries"]["status"] == "partial"
    assert all(r["status"]["enabled"] == "unknown" for r in snapshot["records"])


def test_conflicting_vendored_pins_do_not_silently_select_one(tmp_path):
    request = external(tmp_path)
    path = request["external_skill_repos"]
    data = json.loads(Path(path).read_text())
    conflicting = dict(data["vendored"][0], commit="b" * 40)
    data["vendored"].append(conflicting)
    write_json(path, data)
    skill(tmp_path / "vendor/local-copy")
    record = next(r for r in discover(request)["records"] if r["origin"]["type"] == "vendored")
    assert record["resolution"] == "ambiguous"
    assert record["status"]["resolved"] == "unknown"
    assert not record["entrypoints"]


def test_unreadable_skill_file_keeps_mount_in_catalog(tmp_path, monkeypatch):
    discover({})
    from skill_smith import catalog
    source = skill(tmp_path / "skills/demo")
    real_open = open
    def denied(path, *args, **kwargs):
        if Path(path) == source / "SKILL.md":
            raise PermissionError("synthetic denied")
        return real_open(path, *args, **kwargs)
    monkeypatch.setattr(catalog, "open", denied, raising=False)
    snapshot = discover({"skill_roots": [{"path": str(source.parent)}]})
    assert snapshot["records"][0]["resolution"] == "unreadable"
    assert snapshot["records"][0]["status"]["resolved"] == "unknown"
    assert snapshot["coverage"]["skill_roots"]["status"] == "partial"


def test_source_traversal_cannot_resolve_sibling_skill(tmp_path):
    request = external(tmp_path)
    path = request["external_skill_repos"]
    data = json.loads(Path(path).read_text())
    data["repos"][0]["skills"][0]["subPath"] = "../../outside"
    write_json(path, data)
    skill(tmp_path / "outside", "escaped")
    snapshot = discover(request)
    assert snapshot["coverage"]["external_skill_repos"]["status"] == "partial"
    assert not any(r.get("name") == "escaped" for r in snapshot["records"])


def test_plugin_helper_directories_do_not_hide_valid_skills(tmp_path):
    request = plugins(tmp_path)
    (tmp_path / "cache/market-b/2/skills/helpers").mkdir()
    text_file(tmp_path / "cache/market-b/2/skills/README.md", "Synthetic helper notes.")
    snapshot = discover(request)
    record = next(r for r in snapshot["records"] if r["registry_key"] == "demo@market-b")
    assert record["status"]["resolved"] == "yes"
    assert [e["name"] for e in record["entrypoints"]] == ["demo"]
    assert snapshot["coverage"]["plugin_registries"]["status"] == "checked"


def test_unreadable_skill_stat_is_reported_not_dropped(tmp_path, monkeypatch):
    discover({})
    from skill_smith import paths
    source = skill(tmp_path / "skills/demo")
    original = paths.os.stat
    def denied(path, *args, **kwargs):
        if Path(path) == source / "SKILL.md":
            raise PermissionError("synthetic denied")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(paths.os, "stat", denied)
    snapshot = discover({"skill_roots": [{"path": str(source.parent)}]})
    assert snapshot["coverage"]["skill_roots"]["status"] == "partial"
    assert snapshot["records"][0]["status"]["resolved"] == "unknown"
