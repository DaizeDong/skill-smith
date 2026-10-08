"""Independent-review regressions using generated fixtures and local kit transports."""
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest
import yaml

from test_review_round1 import config, fc, SCRIPTS
from make_fixtures import config_probe, ci_execution_fixture, scaffold_name_cases, malformed_ci_run_listings


@pytest.mark.parametrize("kind", ["missing", "file"])
def test_g8_rejects_a_target_that_cannot_be_examined(tmp_path, capsys, kind):
    target = config_probe(tmp_path / "synthetic-target", kind)
    assert config.main(str(target), True) != 0
    assert "NOT_APPLICABLE" not in capsys.readouterr().out


def test_g8_existing_config_free_directory_remains_not_applicable(tmp_path, capsys):
    target = config_probe(tmp_path / "synthetic-tool")
    assert config.main(str(target), True) == 0
    assert "NOT_APPLICABLE" in capsys.readouterr().out


def test_g8_read_failure_cannot_erase_configuration_signals(tmp_path, monkeypatch, capsys):
    target = config_probe(tmp_path / "synthetic-tool")
    original = Path.open

    def read_denied(path, *args, **kwargs):
        if Path(path) == target / "README.md":
            raise PermissionError("synthetic unreadable document")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", read_denied)
    assert config.main(str(target), True) != 0
    assert "NOT_APPLICABLE" not in capsys.readouterr().out


def inspect_ci(monkeypatch, runs, jobs):
    monkeypatch.setattr(fc.shutil, "which", lambda _name: "synthetic-gh")

    def transport(argv, **kwargs):
        if argv[-1] == ".default_branch":
            return 0, "main\n", ""
        if argv[1:3] == ["run", "list"]:
            return 0, json.dumps(runs), ""
        if argv[1] == "api" and "/actions/runs/" in argv[2]:
            return 0, json.dumps(jobs), ""
        raise AssertionError("Unexpected synthetic transport request: " + repr(argv))

    monkeypatch.setattr(fc, "run", transport)
    return fc.check_ci([("example/acme-tool", ["tests.yml"], "", "PUBLIC")], 5)


@pytest.mark.parametrize("scenario,execution", [
    ("not_started", "not_started"), ("empty", "unknown"), ("skipped", "unknown"),
    ("malformed_jobs", "unknown"), ("missing_run_id", "unknown"),
])
def test_successful_ci_requires_observed_execution(monkeypatch, scenario, execution):
    check = inspect_ci(monkeypatch, *ci_execution_fixture(scenario))
    assert [row[0] for row in check.rows] == [fc.UNKNOWN]
    assert next(iter(check.execution.values()))["state"] == execution


def test_successful_executed_ci_is_a_pass(monkeypatch):
    check = inspect_ci(monkeypatch, *ci_execution_fixture())
    assert [row[0] for row in check.rows] == [fc.PASS]
    assert next(iter(check.execution.values()))["state"] == "executed"


@pytest.mark.parametrize("scenario,execution", [("not_started", "not_started"), ("executed", "executed")])
def test_ci_failure_keeps_execution_state_separate(monkeypatch, scenario, execution):
    check = inspect_ci(monkeypatch, *ci_execution_fixture(scenario, "failure"))
    assert [row[0] for row in check.rows] == [fc.FAIL]
    assert next(iter(check.execution.values()))["state"] == execution


@pytest.mark.parametrize("runs", malformed_ci_run_listings())
def test_malformed_ci_run_listing_is_unobserved(monkeypatch, runs):
    check = inspect_ci(monkeypatch, runs, {})
    assert [row[0] for row in check.rows] == [fc.UNKNOWN]


@pytest.mark.parametrize("display,canonical", scaffold_name_cases())
def test_scaffold_uses_one_canonical_identity_in_structured_metadata(tmp_path, display, canonical):
    result = subprocess.run([sys.executable, str(SCRIPTS / "scaffold_skill.py"), display,
                             "--out-dir", str(tmp_path)], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    root = tmp_path / canonical
    plugin = json.loads((root / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    declaration = json.loads((root / ".dataclass.json").read_text(encoding="utf-8"))
    assert plugin["name"] == canonical
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", plugin["name"])
    document = (root / "skills" / canonical / "SKILL.md").read_text(encoding="utf-8")
    assert yaml.safe_load(document[4:].split("\n---\n", 1)[0])["name"] == canonical
    assert "Scaffolding " + canonical in result.stdout
    serialized = json.dumps(declaration)
    assert "ACME_TOOL_DATA_DIR" in serialized and "acme-tool-config" in serialized
    assert display not in serialized
