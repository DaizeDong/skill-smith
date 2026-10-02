"""Author regressions for budget evidence labels and local Git environment isolation."""
import contextlib
import importlib.util
import io
from pathlib import Path
import re
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import make_fixtures as fixtures


def module(name):
    path = ROOT / "skills/skill-smith/scripts" / (name + ".py")
    spec = importlib.util.spec_from_file_location("review16_" + name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def budget_result(monkeypatch, *, listing=False, missing=False, policy=False, plugins=False):
    budget = module("budget_check")
    inputs = fixtures.review16_budget_inputs()
    rows = [budget.Row(**row) for row in inputs["records"]]
    monkeypatch.setattr(budget, "library_inventory", lambda *args: (rows, []))
    monkeypatch.setattr(budget, "parse_listing",
                        lambda path: (fixtures.review15_listing(inputs["records"], missing), None))
    arguments = inputs["argv"]
    if listing:
        arguments += ["--listing", inputs["listing"]]
    if policy:
        arguments += ["--capacity", str(inputs["capacity"])]
    if plugins:
        arguments += ["--plugins"]
    monkeypatch.setattr(sys, "argv", arguments)
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        rc = budget.main()
    match = re.search(r"^\s*BUDGET: (\w+) (.+)$", output.getvalue(), re.M)
    assert match, output.getvalue()
    fields = dict(part.split("=", 1) for part in match.group(2).split())
    return rc, fields, output.getvalue()


def fleet_result(monkeypatch, rc, output):
    fleet = module("fleet_check")
    monkeypatch.setattr(fleet.os.path, "isfile", lambda path: True)
    monkeypatch.setattr(fleet, "run", lambda *args, **kwargs: (rc, output, ""))
    inputs = fixtures.review16_budget_inputs()
    return fleet, fleet.check_budget(*inputs["fleet_arguments"])


def test_unmeasured_policy_projection_survives_fleet_transport(monkeypatch):
    rc, fields, output = budget_result(monkeypatch, policy=True)
    assert rc == 3 and fields["measurement"] == "not_supplied"
    assert fields["min_lost"] == "0"
    assert int(fields["projected_min_removals"]) > 0
    fleet, result = fleet_result(monkeypatch, rc, output)
    assert result.count(fleet.WARN) == 1
    detail = result.rows[0][2]
    assert "projected minimum removal: " + fields["projected_min_removals"] in detail
    assert "current omissions unmeasured" in detail
    assert "have no description" not in detail
    assert "--plugins" in detail and "fp=" + fields["fp"] in detail


def test_observed_loss_and_policy_projection_remain_distinct(monkeypatch):
    rc, fields, output = budget_result(monkeypatch, listing=True, missing=True, policy=True)
    assert fields["measurement"] == "complete" and fields["min_lost"] == "1"
    assert int(fields["projected_min_removals"]) > 1
    fleet, result = fleet_result(monkeypatch, rc, output)
    assert result.count(fleet.FAIL) == 1
    detail = result.rows[0][2]
    assert ">=1 skill(s) have no description in the supplied listing" in detail
    assert "projected minimum removal: " + fields["projected_min_removals"] in detail


@pytest.mark.parametrize("listing", [False, True])
def test_plugin_advisory_does_not_claim_capacity_fit(monkeypatch, listing):
    _rc, fields, output = budget_result(monkeypatch, listing=listing, missing=listing, plugins=True)
    assert int(fields["estimated_overflow"]) > 0
    assert fields["projected_min_removals"] == "0"
    assert "No removal policy is enforced without --capacity." in output
    assert "the library is inside the selected capacity reference" not in output


def test_checked_git_discards_inherited_git_variables(monkeypatch):
    scaffold = module("scaffold_skill")
    inputs = fixtures.review16_git_verification_inputs()
    inherited = inputs["environment"].copy()
    monkeypatch.setattr(scaffold.os, "environ", inputs["environment"])
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=inputs["stdout"], stderr="")

    monkeypatch.setattr(scaffold.subprocess, "run", run)
    assert scaffold.checked_git(inputs["root"], *inputs["args"]) == inputs["stdout"].strip()
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ["git", *inputs["args"]] and kwargs["cwd"] == inputs["root"]
    assert kwargs["env"] == {
        "PATH": inherited["PATH"],
        "SYNTHETIC_KEEP": inherited["SYNTHETIC_KEEP"],
        "GIT_NO_REPLACE_OBJECTS": "1",
    }
    assert inputs["environment"] == inherited
