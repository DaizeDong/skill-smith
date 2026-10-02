"""Synthetic regressions for exact snapshot, config, budget, kit and DATA identities."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import make_fixtures as fixtures


def module(name):
    path = ROOT / "skills/skill-smith/scripts" / (name + ".py")
    spec = importlib.util.spec_from_file_location("review15_" + name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def git(root, *args):
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith("GIT_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "safe.directory", "GIT_CONFIG_VALUE_0": str(root)})
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          text=True, check=True, timeout=30, env=env)


@pytest.mark.native
@pytest.mark.parametrize("selector", ["repository", "index", "objects", "config"])
def test_snapshot_ignores_foreign_git_selectors(tmp_path, monkeypatch, selector):
    gate = module("acceptance_gate")
    layout = fixtures.review15_snapshot_files(tmp_path)
    for name in ("requested", "foreign"):
        git(layout[name], "init", "-q")
        git(layout[name], "add", "code.py")
    before = gate.candidate_snapshot(layout["requested"])
    environment = dict(fixtures.review15_git_selectors(layout["foreign"]))[selector]
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    assert gate.candidate_snapshot(layout["requested"]) == before
    (layout["requested"] / "code.py").write_bytes(layout["changed_payload"])
    changed = gate.candidate_snapshot(layout["requested"])
    assert changed != before
    (layout["foreign"] / "code.py").write_bytes(layout["changed_payload"])
    assert gate.candidate_snapshot(layout["requested"]) == changed


@pytest.mark.native
def test_snapshot_changes_in_the_requested_repository(tmp_path):
    gate = module("acceptance_gate")
    layout = fixtures.review15_snapshot_files(tmp_path)
    git(layout["requested"], "init", "-q")
    git(layout["requested"], "add", "code.py")
    before = gate.candidate_snapshot(layout["requested"])
    (layout["requested"] / "code.py").write_bytes(layout["changed_payload"])
    assert gate.candidate_snapshot(layout["requested"]) != before


@pytest.mark.parametrize("case", ["current-exact", "legacy-exact", "current-prefix",
                                  "legacy-prefix", "prose-only", "ambiguous"])
def test_doctor_root_comparison_is_exact(tmp_path, case):
    config = module("check_config_conformance")
    row = next(row for row in fixtures.review15_doctor_reports(tmp_path) if row[0] == case)
    assert config.doctor_selected_root(row[1], str(tmp_path)) is row[2]


@pytest.mark.parametrize("case,expected", [("current-exact", 0), ("current-prefix", 1)])
def test_config_gate_checks_exact_roots_after_prerequisites(tmp_path, monkeypatch, case, expected):
    config = module("check_config_conformance")
    layout = fixtures.review15_doctor_layout(tmp_path)
    scratch = tmp_path / "generation"
    scratch.mkdir()
    monkeypatch.setattr(config.tempfile, "mkdtemp", lambda **kwargs: str(scratch))

    def run(args, env=None, cwd=None):
        if "--out" in args:
            destination = Path(args[args.index("--out") + 1])
            destination.mkdir()
            (destination / "registry.json").write_bytes(layout["template"])
            return subprocess.CompletedProcess(args, 0, "", "")
        requested = next(iter(env.values()))
        output = next(row[1] for row in fixtures.review15_doctor_reports(requested)
                      if row[0] == case)
        return subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr(config, "run", run)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        result = config.check_config(str(layout["tool"]), False,
                                     *map(str, layout["configs"]))
    assert result == expected, out.getvalue()
    for element in ("E1", "E2", "E3", "E4", "E6", "E7"):
        assert "[PASS] " + element in out.getvalue(), out.getvalue()
    assert ("[PASS] E5" if expected == 0 else "[FAIL] E5") in out.getvalue()


def budget_result(monkeypatch, *, listing=True, missing=False, capacity=None):
    budget = module("budget_check")
    records = fixtures.review15_budget_records()
    rows = [budget.Row(**row) for row in records]
    monkeypatch.setattr(budget, "library_inventory", lambda *args: (rows, []))
    monkeypatch.setattr(budget, "parse_listing",
                        lambda path: (fixtures.review15_listing(records, missing), None))
    arguments = ["budget_check", "--skills-dir", "synthetic", "--code-root", "synthetic",
                 "--installed-plugins", "synthetic"]
    if listing:
        arguments += ["--listing", "synthetic-listing"]
    if capacity is not None:
        arguments += ["--capacity", str(capacity)]
    monkeypatch.setattr(sys, "argv", arguments)
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        rc = budget.main()
    match = re.search(r"^\s*BUDGET: (\w+) (.+)$", output.getvalue(), re.M)
    assert match, output.getvalue()
    fields = dict(part.split("=", 1) for part in match.group(2).split())
    return budget, rc, match.group(1), fields, output.getvalue()


def test_complete_listing_overrides_historical_estimate(monkeypatch):
    budget, rc, state, fields, output = budget_result(monkeypatch)
    assert int(fields["total"]) > budget.OBSERVED_CAPACITY_CHARS
    assert (rc, state, fields["measurement"], fields["min_lost"], fields["overflow"]) == (
        0, "OK", "complete", "0", "0"), output
    assert fields["capacity_source"] == "current_listing_lower_bound"
    assert "prompt at all" not in output


def test_explicit_capacity_remains_a_policy_without_inventing_omissions(monkeypatch):
    _budget, rc, state, fields, output = budget_result(monkeypatch, capacity=1)
    assert (rc, state) == (3, "BLOCKED"), output
    assert fields["measurement"] == "complete" and fields["min_lost"] == "0"
    assert int(fields["overflow"]) > 0 and fields["capacity_source"] == "configured"
    assert "prompt at all" not in output


def test_observed_listing_omission_still_fails(monkeypatch):
    _budget, rc, state, fields, output = budget_result(monkeypatch, missing=True)
    assert (rc, state, fields["min_lost"]) == (1, "FAIL", "1"), output
    assert fields["measurement"] == "complete"
    assert "has no description in the supplied listing" in output


def test_historical_estimate_without_listing_is_advisory(monkeypatch):
    _budget, rc, state, fields, output = budget_result(monkeypatch, listing=False)
    assert (rc, state, fields["overflow"]) == (0, "OK", "0"), output
    assert fields["measurement"] == "not_supplied"
    assert fields["capacity_source"] == "historical_estimate"
    assert int(fields["estimated_overflow"]) > 0
    assert "visibility is unmeasured" in output


def test_fleet_forwards_current_capacity_and_listing(monkeypatch):
    _budget, rc, _state, fields, output = budget_result(monkeypatch)
    fleet = module("fleet_check")
    calls = []
    monkeypatch.setattr(fleet.os.path, "isfile", lambda path: True)
    monkeypatch.setattr(fleet, "run", lambda args, **kwargs: calls.append(args) or (rc, output, ""))
    capacity = int(fields["total"])
    result = fleet.check_budget("synthetic", "synthetic", 5, "synthetic-listing", capacity)
    assert result.count(fleet.PASS) == 1
    assert calls[0][-4:] == ["--listing", "synthetic-listing", "--capacity", str(capacity)]


@pytest.mark.parametrize("checkout", ["acme-synthetic-tool", "renamed-checkout"])
@pytest.mark.parametrize("visibility", ["PUBLIC", "UNKNOWN", "PRIVATE"])
def test_data_companion_identity_survives_checkout_rename(tmp_path, monkeypatch, checkout, visibility):
    fleet = module("fleet_check")
    layout = fixtures.review15_inverse_layout(tmp_path, checkout)
    selected = []

    def resolve(name, create=False):
        selected.append(name)
        return layout["data"] if name == layout["skill"] else None

    monkeypatch.setattr(fleet, "load_datadir", lambda *args: SimpleNamespace(resolve_data_dir=resolve))
    monkeypatch.setattr(fleet, "in_git_worktree", lambda path: (True, str(layout["data"].parent)))
    slug = "acmecorp/synthetic-config"
    monkeypatch.setattr(fleet, "publication_identity",
                        lambda *args, **kwargs: (slug, "origin", {"origin": [slug]}))
    oracle = SimpleNamespace(error="", map_age=lambda: (0, None),
                             prefetch=lambda slugs: None,
                             visibility=lambda slug: (visibility, "synthetic"))
    result = fleet.check_data_boundary("synthetic", {checkout: str(layout["consumer"])}, oracle=oracle)
    assert selected == [layout["skill"]]
    assert result.count(fleet.SKIP) == 0
    assert [row[0] for row in result.rows] == [fleet.PASS if visibility == "PRIVATE" else fleet.FAIL]


@pytest.mark.parametrize("case", ["missing", "malformed", "no-name", "wrong-type", "invalid-name"])
def test_unavailable_plugin_identity_is_unknown_without_basename_fallback(tmp_path, monkeypatch, case):
    fleet = module("fleet_check")
    layout = fixtures.review15_inverse_layout(tmp_path)
    payload = dict(fixtures.review15_metadata_failures())[case]
    metadata = layout["consumer"] / ".claude-plugin/plugin.json"
    if payload is None:
        metadata.unlink()
    else:
        metadata.write_text(payload, encoding="utf-8")
    loads = []
    monkeypatch.setattr(fleet, "load_datadir", lambda *args: loads.append(args))
    oracle = SimpleNamespace(error="", map_age=lambda: (0, None), prefetch=lambda slugs: None)
    result = fleet.check_data_boundary("synthetic", {"renamed": str(layout["consumer"])}, oracle=oracle)
    assert not loads
    assert result.count(fleet.UNKNOWN) == 1 and result.count(fleet.SKIP) == 0
    assert "plugin identity" in result.rows[0][2]


def initialized_kit(tmp_path):
    layout = fixtures.review15_kit_layout(tmp_path)
    git(layout["dest"], "read-tree", "HEAD")
    git(layout["root"], "update-index", "--add", "--cacheinfo",
        "160000," + layout["revision"] + ",guards")
    return layout


@pytest.mark.native
def test_clean_pinned_kit_remains_usable(tmp_path):
    scaffold = module("scaffold_skill")
    layout = initialized_kit(tmp_path)
    assert scaffold.verify_kit(str(layout["root"]), scaffold.GUARDS_URL, "guards") is None


@pytest.mark.native
@pytest.mark.parametrize("flag", [None, "--assume-unchanged", "--skip-worktree"])
@pytest.mark.parametrize("relative", ["tools/pii_guard.py", "tools/nested_helper.py"])
def test_pinned_kit_rejects_hidden_working_payload_changes(tmp_path, flag, relative):
    scaffold = module("scaffold_skill")
    layout = initialized_kit(tmp_path)
    if flag:
        git(layout["dest"], "update-index", flag, "--", relative)
    (layout["dest"] / relative).write_bytes(layout["changed_payload"])
    with pytest.raises(SystemExit, match="modified"):
        scaffold.verify_kit(str(layout["root"]), scaffold.GUARDS_URL, "guards")
