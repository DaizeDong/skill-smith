"""Authored regressions for scaffold mutation isolation and budget explanations."""
import contextlib
import io
import re
import sys
from types import SimpleNamespace

import pytest

from test_review_round16 import fixtures, module


@pytest.mark.parametrize("existing_repository", [False, True])
def test_emit_guards_isolates_every_git_mutation(monkeypatch, existing_repository):
    scaffold = module("scaffold_skill")
    inputs = fixtures.review17_git_mutation_inputs(scaffold.KITS)
    inherited = inputs["environment"].copy()
    monkeypatch.setattr(scaffold.os, "environ", inputs["environment"])
    git_marker = scaffold.os.path.join(inputs["root"], ".git")
    monkeypatch.setattr(scaffold.os.path, "exists",
                        lambda path: existing_repository and path == git_marker)
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=inputs["stdout"], stderr="")

    def verify(root, _url, _path):
        scaffold.checked_git(root, *inputs["args"])

    class KitsComplete(Exception):
        pass

    def stop_before_output_files(*_args):
        raise KitsComplete

    monkeypatch.setattr(scaffold.subprocess, "run", run)
    monkeypatch.setattr(scaffold, "verify_kit", verify)
    monkeypatch.setattr(scaffold, "emit_hook_forwarders", stop_before_output_files)
    with pytest.raises(KitsComplete):
        scaffold.emit_guards(inputs["root"], False, inputs["name"])

    expected_commands = [] if existing_repository else [["git", "init", "-q"]]
    for url, path in scaffold.KITS:
        expected_commands.extend([["git", "submodule", "add", "-b", "main", url, path],
                                  ["git", *inputs["args"]]])
    assert [args for args, _kwargs in calls] == expected_commands
    for args, kwargs in calls:
        assert kwargs["cwd"] == inputs["root"]
        assert kwargs["timeout"] == 120
        if args[1] in ("init", "submodule"):
            assert kwargs["env"] == inputs["expected_mutation_environment"]
        else:
            assert kwargs["env"] == {
                "PATH": inherited["PATH"], "SYNTHETIC_KEEP": inherited["SYNTHETIC_KEEP"],
                "GIT_NO_REPLACE_OBJECTS": "1",
            }
    assert inputs["environment"] == inherited


@pytest.mark.parametrize("case", fixtures.review17_invalid_transport_cases(),
                         ids=lambda case: case["id"])
def test_invalid_local_transport_fails_before_git_mutation(monkeypatch, case):
    scaffold = module("scaffold_skill")
    inputs = fixtures.review17_git_mutation_inputs(scaffold.KITS)
    inputs["environment"].update(case["updates"])
    for key in case["remove"]:
        inputs["environment"].pop(key)
    monkeypatch.setattr(scaffold.os, "environ", inputs["environment"])

    def unexpected_run(*_args, **_kwargs):
        pytest.fail("Git was invoked before invalid transport configuration was rejected")

    monkeypatch.setattr(scaffold.subprocess, "run", unexpected_run)
    with pytest.raises(SystemExit, match="local Git transport configuration"):
        scaffold.emit_guards(inputs["root"], False, inputs["name"])


@pytest.mark.parametrize("case", fixtures.review17_budget_cases(), ids=lambda case: case["id"])
def test_nontrimmable_budget_explanation_names_actual_red_reasons(monkeypatch, case):
    budget = module("budget_check")
    rows = [budget.Row(**row) for row in case["records"]]
    monkeypatch.setattr(budget, "library_inventory", lambda *_args: (rows, []))
    monkeypatch.setattr(budget, "parse_listing", lambda _path: (case["listing_rows"], None))
    monkeypatch.setattr(sys, "argv", [*case["argv"], "--listing", case["listing"],
                                    "--capacity", str(case["capacity"])])
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        rc = budget.main()
    text = output.getvalue()
    match = re.search(r"^\s*BUDGET: (\w+) (.+)$", text, re.M)
    assert match, text
    fields = dict(part.split("=", 1) for part in match.group(2).split())
    assert fields["measurement"] == "complete"
    assert int(fields["cap_over_ours"]) == case["expected_cap_over_ours"]
    assert int(fields["min_lost"]) == case["expected_min_lost"]
    assert int(fields["projected_min_removals"]) > 0
    assert rc != 0
    has_cap = bool(case["expected_cap_over_ours"])
    has_loss = bool(case["expected_min_lost"])
    assert (match.group(1) == "FAIL") == (has_cap or has_loss)
    assert ("authored description cap violation(s)" in text) == has_cap
    assert ("observed description omission(s)" in text) == has_loss
    if has_loss:
        assert "Restore visibility and measure a new complete listing" in text
    if has_cap or has_loss:
        assert "Capacity-policy overflow is separate and remains after description trimming." in text
    assert "This run is red for the cap violation(s) listed above" not in text
    assert "it will still be here, amber, once the red is gone" not in text
