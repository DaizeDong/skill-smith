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


@pytest.mark.parametrize("visibility", ["PUBLIC", "UNKNOWN"])
def test_status_output_rejects_public_or_unknown(tmp_path, monkeypatch, visibility):
    assert hasattr(fc, "resolve_status_path"), "Real output needs a private-companion boundary"
    monkeypatch.setattr(fc, "in_git_worktree", lambda _: (True, str(tmp_path)))
    monkeypatch.setattr(fc, "origin_slug", lambda _: "owner/synthetic-config")
    monkeypatch.setattr(fc, "publication_routes", lambda _: ("origin", {"origin": ["owner/synthetic-config"]}))
    monkeypatch.setattr(fc, "VisibilityOracle", lambda *a, **k: SimpleNamespace(visibility=lambda _: (visibility, "synthetic")))
    with pytest.raises(ValueError, match="PRIVATE"):
        fc.resolve_status_path(str(tmp_path / "result.json"), "fixture-visibility", True)


def test_default_output_uses_shared_resolver_and_names_private_repo(tmp_path, monkeypatch):
    assert hasattr(fc, "resolve_status_path")
    monkeypatch.setattr(fc, "load_datadir", lambda *a: SimpleNamespace(resolve_data_dir=lambda _: tmp_path))
    monkeypatch.setattr(fc, "in_git_worktree", lambda _: (True, str(tmp_path)))
    monkeypatch.setattr(fc, "origin_slug", lambda _: "owner/synthetic-config")
    monkeypatch.setattr(fc, "publication_routes", lambda _: ("origin", {"origin": ["owner/synthetic-config"]}))
    monkeypatch.setattr(fc, "VisibilityOracle", lambda *a, **k: SimpleNamespace(visibility=lambda _: ("PRIVATE", "synthetic")))
    path, proof = fc.resolve_status_path(None, "fixture-visibility", True)
    assert Path(path) == tmp_path / "fleet-check-status.json"
    assert "PRIVATE" in proof and "owner/synthetic-config" in proof


def test_plain_directory_does_not_become_versioned_data(tmp_path, monkeypatch):
    assert hasattr(fc, "resolve_status_path")
    monkeypatch.setattr(fc, "in_git_worktree", lambda _: (False, ""))
    with pytest.raises(ValueError, match="versioned"):
        fc.resolve_status_path(str(tmp_path / "output.json"), "fixture", True)


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
