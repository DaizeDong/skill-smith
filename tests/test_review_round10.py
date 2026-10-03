"""Generated regressions for evidence, serialization and publication-route boundaries."""
import contextlib
import importlib.util
import io
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/skill-smith/scripts"
ASSETS = ROOT / "skills/skill-smith/assets/config"
sys.path[:0] = [str(ROOT / "tools"), str(SCRIPTS), str(ASSETS)]
from make_fixtures import (
    review10_budget_digest, review10_hook, review10_ignore, review10_library,
    review10_listing_identities, review10_namespaced_rows, review10_replacements,
    materialize_output_routes, review10_trim,
)
import budget_check as budget
import dedup_check as dedup


def module(name, folder=SCRIPTS):
    spec = importlib.util.spec_from_file_location(name + "_review10", folder / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def invoke(target, fixture, monkeypatch, *extra):
    argv = [target.__name__, "--skills-dir", str(fixture["user"]),
            "--installed-plugins", str(fixture["manifest"])]
    if target is budget:
        argv += ["--code-root", str(fixture["code"])]
    monkeypatch.setattr(sys, "argv", argv + list(extra))
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        rc = target.main()
    return rc, output.getvalue()


def digest(output, label):
    match = re.search(r"^\s*%s: (\w+) (.+)$" % label, output, re.M)
    assert match, output
    return match[1], dict(item.split("=", 1) for item in match[2].split())


@pytest.mark.parametrize("scenario,expected", [
    ("kept", (0, "OK")), ("lost", (1, "FAIL")), ("unseen", (2, "UNKNOWN")),
    ("missing", (2, "UNKNOWN")), ("unusable", (2, "UNKNOWN")), ("mismatched", (2, "UNKNOWN")),
])
def test_supplied_listing_controls_budget_verdict(tmp_path, monkeypatch, scenario, expected):
    fixture = review10_library(tmp_path, scenario)
    rc, output = invoke(budget, fixture, monkeypatch, "--listing", str(fixture["listing"]))
    state, fields = digest(output, "BUDGET")
    assert (rc, state) == expected, output
    assert fields["measurement"] == ("complete" if scenario in ("kept", "lost") else "incomplete")
    assert int(fields["unresolved"]) == 0 if scenario in ("kept", "lost") else int(fields["unresolved"]) > 0
    if scenario == "lost":
        assert fields["min_lost"] == "1"


def test_arithmetic_only_mode_cannot_claim_live_visibility(tmp_path, monkeypatch):
    fixture = review10_library(tmp_path)
    rc, output = invoke(budget, fixture, monkeypatch)
    state, fields = digest(output, "BUDGET")
    assert (rc, state) == (0, "OK")
    assert fields["measurement"] == "not_supplied"
    assert "nothing is dropped" not in output


def test_listing_findings_change_fingerprint(tmp_path, monkeypatch):
    fingerprints = []
    for scenario in ("kept", "lost", "unseen", "unusable"):
        fixture = review10_library(tmp_path / scenario, scenario)
        _, output = invoke(budget, fixture, monkeypatch, "--listing", str(fixture["listing"]))
        fingerprints.append(digest(output, "BUDGET")[1]["fp"])
    assert len(set(fingerprints)) == 4


@pytest.mark.parametrize("mode", ["canonical", "short_plugin", "ambiguous", "foreign"])
@pytest.mark.parametrize("reversed_order", [False, True])
def test_qualified_listing_never_borrows_another_plugin(mode, reversed_order):
    rows = [budget.Row(budget.PLUGIN, name, "synthetic", "unused", owner)
            for owner, name in review10_namespaced_rows()]
    lost, unseen = budget.measure_losses(rows, review10_listing_identities(mode, reversed_order))
    if mode in ("canonical", "short_plugin"):
        assert [row.owner for row in lost] == [rows[1].owner]
        assert not unseen
    else:
        assert not lost and unseen == rows


@pytest.mark.parametrize("scenario,expected", [("chinese", (1, "FAIL")),
                                               ("chinese-distinct", (0, "OK")),
                                               ("unmeasurable", (2, "UNKNOWN"))])
@pytest.mark.parametrize("candidate", [False, True])
def test_unicode_and_unmeasurable_descriptions(tmp_path, monkeypatch, scenario, expected, candidate):
    fixture = review10_library(tmp_path, scenario)
    extra = ["--desc", fixture["shared"]] if candidate else []
    rc, output = invoke(dedup, fixture, monkeypatch, *extra)
    if candidate and scenario == "chinese-distinct":
        expected = (1, "FAIL")  # The candidate still duplicates the first skill.
    assert (rc, digest(output, "DEDUP")[0]) == expected, output


@pytest.mark.parametrize("case", list(review10_replacements()))
def test_trim_preserves_string_type_and_contents(tmp_path, monkeypatch, case):
    replacement = review10_replacements()[case]
    fixture = review10_trim(tmp_path, replacement)
    trim = module("trim_descriptions")
    monkeypatch.setattr(trim, "_storage_path", lambda path, **kwargs: (str(path), None))
    monkeypatch.setattr(trim, "_storage_module", lambda: SimpleNamespace(
        reject_output_aliases=lambda path: path, recheck_status_path=lambda path, proof, **kwargs: path))
    assert trim.do_apply(str(fixture["worklist"]), False, str(fixture["backup"])) == 0
    result = fixture["path"].read_text(encoding="utf-8")
    assert budget.parse_frontmatter(result) == ("acme-report", replacement)
    assert trim.parse_desc(result.split("\n")[1:-2])[3] == replacement
    assert [path.read_text(encoding="utf-8") for path in fixture["backup"].rglob("*") if path.is_file()] == [fixture["before"]]


def test_trim_validates_complete_frontmatter_before_mutation(tmp_path, monkeypatch):
    fixture = review10_trim(tmp_path, review10_replacements()["plain"], malformed=True)
    trim = module("trim_descriptions")
    monkeypatch.setattr(trim, "_storage_path", lambda path, **kwargs: (str(path), None))
    monkeypatch.setattr(trim, "_storage_module", lambda: SimpleNamespace(
        reject_output_aliases=lambda path: path, recheck_status_path=lambda path, proof, **kwargs: path))
    with pytest.raises(ValueError, match="frontmatter|metadata"):
        trim.do_apply(str(fixture["worklist"]), False, str(fixture["backup"]))
    assert fixture["path"].read_text(encoding="utf-8") == fixture["before"]
    assert not fixture["backup"].exists()


@pytest.mark.parametrize("kind,expected", [("complete", "PASS"), ("lost", "FAIL"),
                                          ("unmeasured", "UNKNOWN"), ("incomplete", "UNKNOWN"),
                                          ("missing", "UNKNOWN")])
def test_fleet_requires_complete_live_measurement(monkeypatch, kind, expected):
    fleet = module("fleet_check")
    monkeypatch.setattr(fleet, "run", lambda *args, **kwargs: (0, review10_budget_digest(kind), ""))
    result = fleet.check_budget("unused", "unused", 5)
    assert result.count(expected) == 1
    if expected != "PASS":
        assert result.count("PASS") == 0


@pytest.mark.parametrize("scenario,allowed", [("private", True), ("private_override", False),
    ("public_push", False), ("unknown_push", False), ("multiple_push", False),
    ("push_default", False), ("branch_push", False), ("branch_remote", False),
    ("missing_route", False), ("local_route", False), ("config_failure", False)])
def test_private_data_requires_effective_private_push_routes(private_output, scenario, allowed):
    fixture = materialize_output_routes(private_output, scenario)
    fleet = private_output["fleet"]
    path = private_output["data"] / "status.json"
    if allowed:
        result, proof = fleet.resolve_status_path(str(path), str(private_output["visibility"]))
        assert result == str(path)
        assert proof.repositories
        assert all(fixture["visibility"][slug] == "PRIVATE" for slug in proof.repositories)
    else:
        with pytest.raises(ValueError, match="PRIVATE|publication|push|routing"):
            fleet.resolve_status_path(str(path), str(private_output["visibility"]))
    assert not path.exists()


@pytest.mark.parametrize("scenario,allowed", [("active", True), ("restored", True),
    ("parent_excluded", True), ("absent", False), ("comments", False), ("negated", False),
    ("reopened", False), ("root_only_env", False), ("nested_reopened", False)])
@pytest.mark.parametrize("layer", ["doctor", "gate"])
def test_ignore_checks_follow_order_negation_and_path_scope(tmp_path, monkeypatch, scenario, allowed, layer):
    root = review10_ignore(tmp_path, scenario)
    output = io.StringIO()
    if layer == "doctor":
        doctor = module("verify_config", ASSETS)
        runtime = SimpleNamespace(skill="acme-tool", discover=lambda override: (str(root), "synthetic"))
        monkeypatch.setattr(doctor, "ConfigRuntime", lambda skill: runtime)
        monkeypatch.setattr(sys, "argv", ["verify_config"])
        with contextlib.redirect_stdout(output):
            rc = doctor.main()
        assert (rc == 0) is allowed, output.getvalue()
    else:
        gate = module("check_config_conformance")
        with contextlib.redirect_stdout(output):
            gate.main(str(root), no_run=True)
        line = next(line for line in output.getvalue().splitlines() if "E6 " in line)
        assert ("[PASS]" in line) is allowed, output.getvalue()
        assert "none committed" not in line


@pytest.mark.native
@pytest.mark.parametrize("hook", ["pre-commit", "pre-push"])
@pytest.mark.parametrize("kind", ["missing", "empty", "directory", "valid", "failure"])
def test_consumer_hook_rejects_incomplete_delegate(tmp_path, hook, kind):
    fixture = review10_hook(tmp_path, hook, (ROOT / ".githooks" / hook).read_bytes(), kind)
    result = subprocess.run(["sh", str(fixture["path"]), *fixture["args"]], cwd=tmp_path,
                            input=fixture["stdin"], capture_output=True, text=True, timeout=10)
    assert result.returncode == fixture["expected_exit"], result.stdout + result.stderr
    if kind in ("valid", "failure"):
        assert result.stdout == fixture["expected_stdout"]
    else:
        assert "synthetic-guard-ran" not in result.stdout
