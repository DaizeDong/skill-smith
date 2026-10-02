"""Generated regressions for complete active-library budget and overlap coverage."""
import contextlib
import io
from pathlib import Path
import re
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "skills/skill-smith/scripts"))
from make_fixtures import library_inventory_fixture
import budget_check as budget
import dedup_check as dedup


def invoke(module, fixture, monkeypatch, *extra):
    args = [module.__name__, "--skills-dir", str(fixture["user"]),
            "--installed-plugins", str(fixture["manifest"])]
    if module is budget:
        args += ["--code-root", str(fixture["code"])]
    monkeypatch.setattr(sys, "argv", args + list(extra))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = module.main()
    return rc, out.getvalue()


def digest(output, kind):
    match = re.search(r"^\s*%s: (\w+) (.+)$" % kind, output, re.M)
    assert match, output
    return match.group(1), dict(field.split("=", 1) for field in match.group(2).split())


def test_generated_complete_control_measures_both_tiers(tmp_path):
    fixture = library_inventory_fixture(tmp_path)
    users = budget.user_tier_rows(str(fixture["user"]), str(fixture["code"]))
    plugins, problems = budget.plugin_tier_rows(str(fixture["manifest"]))
    assert len(users) == len(plugins) == 1 and not problems
    assert users[0].cost == len("- invoice-reader: " + fixture["shared"] + "\n")


def test_generated_similarity_control(tmp_path):
    fixture = library_inventory_fixture(tmp_path)
    assert dedup.jaccard(dedup.words(fixture["shared"]), dedup.words(fixture["shared"].upper())) == 1
    assert dedup.jaccard(dedup.words(fixture["shared"]), dedup.words(fixture["distinct"])) == 0


def test_dedup_default_library_includes_active_plugins(tmp_path, monkeypatch):
    fixture = library_inventory_fixture(tmp_path, "cross_duplicate")
    expanduser = dedup.os.path.expanduser
    monkeypatch.setattr(dedup.os.path, "expanduser", lambda path: str(fixture["manifest"])
                        if path == "~/.claude/plugins/installed_plugins.json" else expanduser(path))
    monkeypatch.setattr(sys, "argv", ["dedup_check", "--skills-dir", str(fixture["user"])])
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = dedup.main()
    assert rc == 1, out.getvalue()
    assert "polygon-renderer" in out.getvalue()


@pytest.mark.parametrize("scenario", [
    "missing_user_root", "missing_manifest", "missing_install", "mixed_scopes",
    "missing_user_skill", "missing_plugin_skill", "invalid_json", "json_list", "json_null",
    "json_missing_plugins", "plugins_list", "plugins_null", "records_empty", "record_scalar",
    "path_number", "path_relative", "path_nul", "invalid_manifest_utf8", "invalid_skill_utf8",
    "missing_description", "empty_description", "unterminated_frontmatter", "list_description",
    "broken_quote", "null_description", "duplicate_description",
    "duplicate_json_key", "malformed_frontmatter_line", "numeric_description", "conflicting_scopes",
])
def test_budget_incomplete_inventory_is_unknown(tmp_path, monkeypatch, scenario):
    fixture = library_inventory_fixture(tmp_path, scenario)
    rc, output = invoke(budget, fixture, monkeypatch)
    state, fields = digest(output, "BUDGET")
    assert (rc, state) == (2, "UNKNOWN"), output
    assert int(fields["unresolved"]) >= 1, output
    assert "so nothing is dropped" not in output and "STATUS: OK" not in output


@pytest.mark.parametrize("tier", ["user", "plugin"])
@pytest.mark.parametrize("failure", ["file", "directory"])
def test_budget_permission_failures_remain_unknown(tmp_path, monkeypatch, tier, failure):
    fixture = library_inventory_fixture(tmp_path)
    target = (fixture["paths"]["invoice-reader"] if tier == "user"
              else fixture["paths"]["polygon-renderer"])
    if failure == "file":
        import builtins
        original = builtins.open

        def denied(path, *args, **kwargs):
            if Path(path) == target:
                raise PermissionError("synthetic unreadable skill")
            return original(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", denied)
    else:
        original = budget.os.listdir
        directory = fixture["user"] if tier == "user" else fixture["active"] / "skills"

        def denied(path):
            if Path(path) == directory:
                raise PermissionError("synthetic unreadable directory")
            return original(path)

        monkeypatch.setattr(budget.os, "listdir", denied)
    rc, output = invoke(budget, fixture, monkeypatch)
    state, fields = digest(output, "BUDGET")
    assert (rc, state) == (2, "UNKNOWN"), output
    assert int(fields["unresolved"]) >= 1


@pytest.mark.parametrize("scenario,count", [("empty", 0), ("distinct", 2),
                                           ("repeated_scope", 2), ("command_only_plugin", 1),
                                           ("folded_description", 2)])
def test_complete_inventory_retains_success(tmp_path, monkeypatch, scenario, count):
    fixture = library_inventory_fixture(tmp_path, scenario)
    rc, output = invoke(budget, fixture, monkeypatch)
    state, fields = digest(output, "BUDGET")
    assert (rc, state, fields["unresolved"]) == (0, "OK", "0"), output
    rows, problems = budget.library_inventory(str(fixture["user"]), str(fixture["code"]),
                                             str(fixture["manifest"]))
    assert len(rows) == count and not problems
    assert isinstance(budget.user_tier_rows(str(fixture["user"]), str(fixture["code"])), list)


@pytest.mark.parametrize("capacity,expected", [(300, (1, "FAIL")), (10, (3, "BLOCKED"))])
def test_known_overflow_keeps_priority_over_unknown(tmp_path, monkeypatch, capacity, expected):
    fixture = library_inventory_fixture(tmp_path, "overflow")
    rc, output = invoke(budget, fixture, monkeypatch, "--capacity", str(capacity))
    state, fields = digest(output, "BUDGET")
    assert (rc, state) == expected, output
    assert int(fields["unresolved"]) >= 1 and int(fields["overflow"]) > 0
    assert "would put the library back inside" not in output


@pytest.mark.parametrize("scenario,pairs", [("cross_duplicate", 1), ("plugin_duplicate", 1),
                                          ("user_duplicate", 1), ("distinct", 0),
                                          ("stale_cache", 0), ("repeated_scope", 0), ("empty", 0)])
def test_dedup_uses_active_budget_inventory(tmp_path, monkeypatch, scenario, pairs):
    fixture = library_inventory_fixture(tmp_path, scenario)
    rc, output = invoke(dedup, fixture, monkeypatch)
    state, fields = digest(output, "DEDUP")
    assert (rc, state) == ((1, "FAIL") if pairs else (0, "OK")), output
    rows, problems = budget.library_inventory(str(fixture["user"]), str(fixture["code"]),
                                             str(fixture["manifest"]))
    assert int(fields["skills"]) == len(rows) and not problems
    assert int(fields["overlaps"]) == pairs and fields["unresolved"] == "0"
    if scenario == "cross_duplicate":
        assert "shapes@example-market:polygon-renderer" in output
    assert "stale-copy" not in output


@pytest.mark.parametrize("scenario", ["missing_user_root", "missing_manifest", "mixed_scopes",
                                      "list_description", "missing_plugin_skill"])
def test_dedup_incomplete_inventory_cannot_pass(tmp_path, monkeypatch, scenario):
    fixture = library_inventory_fixture(tmp_path, scenario)
    rc, output = invoke(dedup, fixture, monkeypatch)
    state, fields = digest(output, "DEDUP")
    assert (rc, state) == (2, "UNKNOWN"), output
    assert int(fields["unresolved"]) >= 1 and "RESULT: no overlaps" not in output


def test_candidate_duplicate_in_plugin_is_visible(tmp_path, monkeypatch):
    fixture = library_inventory_fixture(tmp_path)
    rc, output = invoke(dedup, fixture, monkeypatch, "--desc", fixture["distinct"])
    state, fields = digest(output, "DEDUP")
    assert (rc, state, fields["overlaps"]) == (1, "FAIL", "1"), output


def test_candidate_cannot_be_cleared_by_partial_inventory(tmp_path, monkeypatch):
    fixture = library_inventory_fixture(tmp_path, "missing_manifest")
    rc, output = invoke(dedup, fixture, monkeypatch, "--desc", fixture["distinct"])
    state, fields = digest(output, "DEDUP")
    assert (rc, state) == (2, "UNKNOWN"), output
    assert "OK to create" not in output and int(fields["unresolved"]) >= 1


def test_dedup_known_duplicate_keeps_unknown_coverage(tmp_path, monkeypatch):
    fixture = library_inventory_fixture(tmp_path, "mixed_scopes")
    rc, output = invoke(dedup, fixture, monkeypatch, "--desc", fixture["shared"])
    state, fields = digest(output, "DEDUP")
    assert (rc, state, fields["overlaps"]) == (1, "FAIL", "1"), output
    assert int(fields["unresolved"]) >= 1
