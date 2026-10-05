"""Native spelling aliases must not grant access through escaping directory links."""
import os

import pytest

from skill_smith import catalog, paths
from tools.make_fixtures import (
    catalog_path_alias_fixture, catalog_json, directory_link, native_alias_capture,
    plugin_reference_fixture, windows_short_path,
)


def short_path(path):
    short = windows_short_path(path)
    if str(short).casefold() == str(path).casefold():
        if os.environ.get("SKILL_SMITH_REQUIRE_SHORT_PATH") == "1":
            pytest.fail("Windows package CI requires a volume with 8.3 path aliases")
        pytest.skip("8.3 aliases are disabled for the generated directory")
    return short


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows 8.3 path spelling")
def test_windows_short_root_resolves_the_same_catalog(tmp_path):
    case = catalog_path_alias_fixture(tmp_path)
    short = short_path(case["approved"])
    result = paths.probe(short / "skills/demo", [tmp_path / "missing-approved-root", short])
    assert result["resolution"] == "resolved", result
    assert result["resolved_path"] == os.path.realpath(case["approved"] / "skills/demo")
    snapshot = catalog.discover({"skill_roots": [{"path": str(short / "skills")}]})
    assert snapshot["coverage"]["skill_roots"]["status"] == "checked", snapshot["problems"]
    assert len(snapshot["records"]) == 1
    assert snapshot["records"][0]["entrypoints"][0]["name"] == "demo"


def test_approved_root_link_does_not_authorize_its_outside_target(tmp_path):
    case = catalog_path_alias_fixture(tmp_path)
    alias = tmp_path / "unapproved-root-link"
    directory_link(alias, case["outside"])
    result = paths.probe(alias / "skills/other", [alias])
    assert result["resolution"] == "outside_approved_roots", result


def test_child_link_escape_requires_its_target_to_be_explicitly_approved(tmp_path):
    case = catalog_path_alias_fixture(tmp_path)
    alias = case["approved"] / "child-link"
    directory_link(alias, case["outside"])
    result = paths.probe(alias / "skills/other", [case["approved"]])
    assert result["resolution"] == "outside_approved_roots", result
    allowed = paths.probe(alias / "skills/other", [case["approved"], case["outside"]])
    assert allowed["resolution"] == "resolved", allowed


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows 8.3 path spelling")
@pytest.mark.parametrize("kind", ["skills", "commands", "agents"])
def test_windows_custom_plugin_entry_resolves_short_root(tmp_path, kind):
    case = plugin_reference_fixture(tmp_path, kind)
    short = short_path(case["plugin"])
    snapshot = catalog.discover({"plugin_descriptors": [{"name": "demo@example", "path": str(short)}]})
    assert snapshot["coverage"]["plugin_descriptors"]["status"] == "checked", snapshot["problems"]
    record, = snapshot["records"]
    entry, = record["entrypoints"]
    assert entry["name"] == "synthetic-entry"
    assert entry["relative_path"] == case["relative_path"]
    assert entry["kind"] == {"skills": "skill", "commands": "command", "agents": "agent_template"}[kind]


@pytest.mark.parametrize("escape", ["absolute", "traversal", "junction"])
def test_custom_plugin_entry_cannot_escape_to_an_approved_outside_root(tmp_path, escape):
    case = plugin_reference_fixture(tmp_path)
    root = short_path(case["plugin"]) if os.name == "nt" else case["plugin"]
    reference = str(case["outside_entry"])
    if escape == "traversal":
        reference = "../" + case["outside"].name + "/" + case["relative_path"]
    elif escape == "junction":
        directory_link(case["plugin"] / "linked", case["outside"])
        reference = "linked/" + case["relative_path"]
    catalog_json(case["manifest"], {"name": "demo", "agents": [reference]})
    snapshot = catalog.discover({"approved_roots": [str(case["outside"])],
                                "plugin_descriptors": [{"name": "demo@example", "path": str(root)}]})
    assert snapshot["coverage"]["plugin_descriptors"]["status"] == "partial"
    assert any(p["reason"] == "agent_reference_outside_plugin" for p in snapshot["problems"])
    assert snapshot["records"][0]["entrypoints"] == []


def test_missing_custom_plugin_entry_is_reported_as_unavailable(tmp_path):
    case = plugin_reference_fixture(tmp_path)
    root = short_path(case["plugin"]) if os.name == "nt" else case["plugin"]
    catalog_json(case["manifest"], {"name": "demo", "agents": ["custom/missing.md"]})
    snapshot = catalog.discover({"plugin_descriptors": [{"name": "demo@example", "path": str(root)}]})
    assert [p["reason"] for p in snapshot["problems"]] == ["declared_plugin_path_unavailable"]
    assert snapshot["records"][0]["entrypoints"] == []


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows 8.3 path spelling")
@pytest.mark.parametrize("scope", ["short", "outside", "junction", "embedded_nul"])
def test_native_cwd_short_spelling_does_not_accept_other_scope_aliases(tmp_path, monkeypatch, scope):
    from skill_smith import native_discovery

    case = catalog_path_alias_fixture(tmp_path)
    short = short_path(case["approved"])
    cwd = short
    if scope == "outside":
        cwd = case["outside"]
    elif scope == "junction":
        cwd = tmp_path / "native-cwd-link"
        directory_link(cwd, case["approved"])
    elif scope == "embedded_nul":
        cwd = str(short) + "\x00unexpected"
    monkeypatch.setattr(native_discovery, "acquire", lambda _: native_alias_capture(short, cwd))
    snapshot = catalog.discover({"skill_roots": [{"path": str(short / "skills"), "client": "codex"}],
                                "native_discovery": {"enabled": True, "cwd": str(short)}})
    expected = "checked" if scope == "short" else "partial"
    assert snapshot["coverage"]["native_discovery"]["status"] == expected, snapshot["problems"]
    entry = snapshot["records"][0]["entrypoints"][0]
    assert entry["status"]["discovered"] == ("yes" if scope == "short" else "unknown")
