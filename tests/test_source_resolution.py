"""Exact provenance resolution and the legacy readers' catalog boundary."""
import json
from pathlib import Path

import budget_check
import fleet_check
from tools.make_fixtures import directory_link, external, plugins, skill, text_file, write_json
from test_catalog_contract import discover


def test_vendored_local_path_does_not_append_upstream_subpath(tmp_path):
    request = external(tmp_path)
    skill(tmp_path / "vendor/local-copy", "vendored-name")
    skill(tmp_path / "repos/demo-kit/skills/invoice", "source-name")
    snapshot = discover(request)
    vendored = next(r for r in snapshot["records"] if r["origin"]["type"] == "vendored")
    assert Path(vendored["path"]) == tmp_path / "vendor/local-copy"
    assert vendored["relative_path"] == "upstream/skill"
    assert vendored["origin"]["vendored"] == "2026-01-01"
    assert vendored["version"] == "a" * 40
    assert vendored["status"]["resolved"] == "yes"
    checkout = next(r for r in snapshot["records"] if r["origin"]["type"] == "checkout")
    assert Path(checkout["path"]) == tmp_path / "repos/demo-kit/skills/invoice"
    assert checkout["origin"]["branch"] == "main"
    assert checkout["name"] == "source-name"
    assert checkout["aliases"] == ["invoice-alias"]


def test_missing_sources_keep_declarations_and_never_claim_availability(tmp_path):
    snapshot = discover(external(tmp_path))
    assert len(snapshot["records"]) == 2
    assert all(r["status"]["declared"] == "yes" for r in snapshot["records"])
    assert all(r["status"]["resolved"] == "no" for r in snapshot["records"])
    assert all(r["resolution"] == "missing" for r in snapshot["records"])
    assert all(r["ownership"] != "deletable" for r in snapshot["records"])


def test_same_name_scan_is_candidate_only(tmp_path):
    request = external(tmp_path)
    path = request["external_skill_repos"]
    data = json.loads(Path(path).read_text())
    data["repos"].append({"dir": "other", "url": "https://example.com/acme/other.git",
                           "skills": [{"name": "invoice-alias", "subPath": "."}]})
    write_json(path, data)
    skill(tmp_path / "local/invoice-alias", "invoice-alias")
    request["skill_roots"] = [{"path": str(tmp_path / "local"), "namespace": "local"}]
    snapshot = discover(request)
    local = next(r for r in snapshot["records"] if r["origin"]["type"] == "local")
    assert local["status"]["declared"] == "unknown"
    assert len(local["candidates"]) == 2
    assert all(r["status"]["resolved"] == "no" for r in snapshot["records"]
               if r["origin"]["type"] == "checkout")


def test_cross_client_roots_link_to_one_explicit_source(tmp_path):
    request = external(tmp_path)
    source = skill(tmp_path / "repos/demo-kit/skills/invoice", "source-name")
    request["skill_roots"] = [
        {"path": str(source.parent), "client": "claude", "namespace": "claude-skills"},
        {"path": str(source.parent), "client": "codex", "namespace": "codex-skills"},
    ]
    snapshot = discover(request)
    record = next(r for r in snapshot["records"] if r["origin"]["type"] == "checkout")
    assert {e["client"] for e in record["entrypoints"] if e["status"]["installed"] == "yes"} == {"claude", "codex"}
    assert all(e["source_id"] == record["source_id"] for e in record["entrypoints"])
    assert not any(r["origin"]["type"] == "local" for r in snapshot["records"])


def test_cc_setup_keeps_external_installer_ownership(tmp_path):
    skill(tmp_path / "local/cc-setup", "cc-setup")
    snapshot = discover({"skill_roots": [{"path": str(tmp_path / "local"), "namespace": "local"}]})
    record = snapshot["records"][0]
    assert record["ownership"] == "external-installer"
    assert record["install_strategy"] == "external-installer"


def test_reparse_escape_retains_direct_and_final_target_without_reading_skill(tmp_path, monkeypatch):
    discover({})
    from skill_smith import paths
    source = skill(tmp_path / "local/mounted")
    escaped = skill(tmp_path / "outside/demo")
    original = paths.os.path.realpath
    monkeypatch.setattr(paths.os.path, "realpath", lambda p, **kw:
                        str(escaped / Path(p).relative_to(source))
                        if Path(p).is_relative_to(source) else original(p, **kw))
    snapshot = discover({"skill_roots": [{"path": str(source.parent), "namespace": "local"}]})
    record = snapshot["records"][0]
    assert record["resolution"] == "outside_approved_roots"
    assert Path(record["path"]) == source
    assert Path(record["resolved_path"]) == escaped
    assert record["status"]["resolved"] == "no"
    assert not record["entrypoints"]


def test_unreadable_mount_is_unknown_not_missing(tmp_path, monkeypatch):
    discover({})
    from skill_smith import paths
    source = skill(tmp_path / "local/mounted")
    original = paths.os.stat
    def denied(path, *args, **kwargs):
        if Path(path) == source:
            raise PermissionError("synthetic access denied")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(paths.os, "stat", denied)
    snapshot = discover({"skill_roots": [{"path": str(source.parent), "namespace": "local"}]})
    record = snapshot["records"][0]
    assert record["resolution"] == "unreadable"
    assert record["status"]["resolved"] == "unknown"
    assert record["ownership"] == "unmanaged"


def test_unc_prefix_and_component_boundaries():
    discover({})
    from skill_smith.paths import within
    assert within(r"\\?\UNC\server\share\skills\demo", r"\\server\share\skills")
    assert not within(r"\\server\share\skills-elsewhere\demo", r"\\server\share\skills")
    assert not within(r"\\server\other\skills\demo", r"\\server\share\skills")


def test_linked_worktrees_are_included_by_fleet_reader(tmp_path):
    checkout = tmp_path / "linked"
    checkout.mkdir()
    text_file(checkout / ".git", "gitdir: ../metadata/worktrees/linked\n")
    assert fleet_check.local_repos(str(tmp_path)) == {"linked": str(checkout)}


def test_budget_and_dedup_consume_same_frozen_snapshot_after_files_disappear(tmp_path):
    import dedup_check
    request = plugins(tmp_path)
    snapshot = discover(request)
    for path in tmp_path.rglob("SKILL.md"):
        path.unlink()
    assert hasattr(budget_check, "rows_from_catalog"), "budget reader must accept catalog snapshots"
    rows, problems = budget_check.rows_from_catalog(snapshot, str(tmp_path / "fleet"))
    assert [r.owner for r in rows] == ["demo@market-b"]
    assert not problems
    assert hasattr(dedup_check, "items_from_catalog"), "dedup reader must accept catalog snapshots"
    items = dedup_check.items_from_catalog(snapshot)
    assert [name for name, _words in items] == ["demo"]


def test_budget_keeps_missing_scope_visible_when_another_scope_resolves(tmp_path):
    request = plugins(tmp_path)
    descriptor = request["plugin_registries"][0]
    data = json.loads(Path(descriptor["path"]).read_text())
    data["plugins"]["demo@market-b"].append({"scope": "project", "projectPath": "synthetic-project",
        "version": "2", "installPath": str(tmp_path / "cache/missing")})
    write_json(descriptor["path"], data)
    snapshot = discover(request)
    rows, problems = budget_check.rows_from_catalog(snapshot, str(tmp_path / "fleet"))
    assert len(rows) == 1
    assert any("demo@market-b" in p and "project" in p for p in problems)


def test_real_dangling_junction_retains_target_and_unknown_install_state(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = directory_link(tmp_path / "skills/broken", target)
    target.rmdir()
    snapshot = discover({"skill_roots": [{"path": str(link.parent)}], "approved_roots": [str(tmp_path)]})
    record = snapshot["records"][0]
    assert record["is_link"]
    assert record["direct_target"]
    assert Path(record["resolved_path"]) == target
    assert record["status"]["installed"] == "unknown"
    assert record["status"]["resolved"] == "no"
    assert record["resolution"] == "missing"


def test_real_alias_junction_resolves_to_explicit_source(tmp_path):
    request = external(tmp_path)
    source = skill(tmp_path / "repos/demo-kit/skills/invoice", "source-name")
    link = directory_link(tmp_path / "skills/invoice-alias", source)
    request["skill_roots"] = [{"path": str(link.parent), "client": "claude"}]
    snapshot = discover(request)
    record = next(r for r in snapshot["records"] if r["origin"]["type"] == "checkout")
    assert record["name"] == "source-name"
    assert record["aliases"] == ["invoice-alias"]
    assert any(e["install_name"] == "invoice-alias" and e["status"]["installed"] == "yes"
               for e in record["entrypoints"])


def test_fleet_budget_uses_snapshot_even_after_sources_disappear(tmp_path):
    snapshot = discover(plugins(tmp_path))
    for path in tmp_path.rglob("SKILL.md"):
        path.unlink()
    check = fleet_check.check_budget(str(tmp_path / "absent"), str(tmp_path / "fleet"), 5, snapshot=snapshot)
    assert [row[0] for row in check.rows] == [fleet_check.PASS]


def test_fleet_unreadable_mount_is_unknown_not_dangling(tmp_path, monkeypatch):
    discover({})
    from skill_smith import paths
    target = skill(tmp_path / "target")
    link = directory_link(tmp_path / "skills/mount", target)
    original = paths.os.stat
    def denied(path, *args, **kwargs):
        if Path(path) == link:
            raise PermissionError("synthetic access denied")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(paths.os, "stat", denied)
    snapshot = discover({"skill_roots": [{"path": str(link.parent)}], "approved_roots": [str(tmp_path)]})
    check = fleet_check.check_junctions(str(link.parent), snapshot=snapshot)
    assert [row[0] for row in check.rows] == [fleet_check.UNKNOWN]


def test_dedup_legacy_cli_accepts_junction_into_explicit_code_root(tmp_path):
    import dedup_check
    target = skill(tmp_path / "code/demo")
    link = directory_link(tmp_path / "skills/demo", target)
    assert dedup_check.main(["--skills-dir", str(link.parent), "--code-root", str(tmp_path / "code")]) == 0
