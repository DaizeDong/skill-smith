"""Additional fleet output and CI evidence cases, without external queries."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from make_fixtures import ci_execution_fixture, ci_step_evidence_cases

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/skill-smith/scripts"
spec = importlib.util.spec_from_file_location("fleet_acceptance_test", SCRIPTS / "fleet_check.py")
fc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fc)


def test_default_output_uses_shared_resolver(private_output, monkeypatch):
    fc = private_output["fleet"]
    monkeypatch.setattr(fc, "load_datadir", lambda *a: SimpleNamespace(
        resolve_data_dir=lambda _: private_output["data"]))
    path = fc.resolve_status_path(None)
    assert Path(path) == private_output["data"] / "fleet-check-status.json"


def test_plain_directory_does_not_become_versioned_data(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="versioned"):
        fc.resolve_status_path(str(tmp_path / "output.json"))


def test_zero_step_ci_is_distinct_from_executed_failure(monkeypatch):
    assert hasattr(fc, "ci_execution_detail")
    no_runner = ci_execution_fixture("not_started")[1]
    executed_failure = next(jobs for name, _runs, jobs, _expected in ci_step_evidence_cases("failure")
                            if name == "completed-failure")
    monkeypatch.setattr(fc, "run", lambda *a, **k: (0, json.dumps(no_runner), ""))
    assert fc.ci_execution_detail("gh", "owner/repo", 1, 10)[0] == "not_started"
    monkeypatch.setattr(fc, "run", lambda *a, **k: (0, json.dumps(executed_failure), ""))
    assert fc.ci_execution_detail("gh", "owner/repo", 1, 10)[0] == "executed"


def test_empty_job_listing_is_not_proof_that_ci_never_started(monkeypatch):
    assert hasattr(fc, "ci_execution_detail")
    monkeypatch.setattr(fc, "run", lambda *a, **k: (0, json.dumps({"jobs": []}), ""))
    assert fc.ci_execution_detail("gh", "owner/repo", 1, 10)[0] == "unknown"


def test_guard_coverage_comes_from_job_actions_not_workflow_names():
    assert hasattr(fc, "workflow_guards")
    assert fc.workflow_guards("name: pii-guard\njobs: {}\n") == []
    body = "jobs:\n  check:\n    steps:\n      - uses: ./ci/pii-guard\n      - uses: ./style/ci/dash-guard\n"
    assert fc.workflow_guards(body) == ["pii-guard", "dash-guard"]
    commented = "jobs:\n  check:\n    steps:\n      - run: echo ok\n# - uses: ./ci/pii-guard\n"
    assert fc.workflow_guards(commented) == []


def test_role_policy_never_drops_public_security_requirement():
    assert hasattr(fc, "required_guards")
    assert fc.required_guards("security-kit") == ["pii-guard"]
    assert "pii-guard" in fc.required_guards("style-kit")
    with pytest.raises(ValueError):
        fc.required_guards("unknown-role")


def test_malformed_job_rows_are_unobserved_not_a_crash(monkeypatch):
    monkeypatch.setattr(fc, "run", lambda *a, **k: (0, json.dumps({"jobs": [None]}), ""))
    assert fc.ci_execution_detail("gh", "owner/repo", 1, 10)[0] == "unknown"


def test_null_workflow_steps_are_rejected_as_unparseable():
    with pytest.raises(ValueError, match="steps"):
        fc.workflow_guards("jobs:\n  check:\n    steps: null\n")
