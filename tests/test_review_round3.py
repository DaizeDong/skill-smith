"""Review regressions for CI step evidence and returned branch provenance."""
import pytest

from test_review_round2 import inspect_ci, fc
from make_fixtures import ci_step_evidence_cases, ci_branch_evidence_cases, ci_execution_fixture


@pytest.mark.parametrize("case,runs,jobs,execution", ci_step_evidence_cases())
def test_step_evidence_requires_a_valid_state_and_conclusion(monkeypatch, case, runs, jobs, execution):
    result = inspect_ci(monkeypatch, runs, jobs)
    assert [row[0] for row in result.rows] == [fc.PASS if execution == "executed" else fc.UNKNOWN], case
    evidence = next(iter(result.execution.values()))
    assert evidence["state"] == execution, case
    assert evidence["run_id"] == runs[0]["databaseId"]
    assert evidence["head_sha"] == runs[0]["headSha"]


@pytest.mark.parametrize("case,runs,jobs,execution", ci_step_evidence_cases("failure"))
def test_red_workflow_policy_preserves_execution_classification(monkeypatch, case, runs, jobs, execution):
    result = inspect_ci(monkeypatch, runs, jobs)
    assert [row[0] for row in result.rows] == [fc.FAIL], case
    assert next(iter(result.execution.values()))["state"] == execution, case


@pytest.mark.parametrize("case,runs,jobs", ci_branch_evidence_cases())
def test_success_on_an_unverified_branch_cannot_cover_default(monkeypatch, case, runs, jobs):
    result = inspect_ci(monkeypatch, runs, jobs)
    assert [row[0] for row in result.rows] == [fc.UNKNOWN], case
    assert "branch" in result.rows[0][2].lower(), case
    assert next(iter(result.execution.values()))["state"] == "executed", case


@pytest.mark.parametrize("case,runs,jobs", ci_branch_evidence_cases("failure"))
def test_failure_on_an_unverified_branch_is_not_a_default_branch_verdict(monkeypatch, case, runs, jobs):
    result = inspect_ci(monkeypatch, runs, jobs)
    assert [row[0] for row in result.rows] == [fc.UNKNOWN], case
    assert next(iter(result.execution.values()))["state"] == "executed", case


def test_success_on_observed_default_branch_still_passes(monkeypatch):
    result = inspect_ci(monkeypatch, *ci_execution_fixture())
    assert [row[0] for row in result.rows] == [fc.PASS]
    assert next(iter(result.execution.values()))["state"] == "executed"
