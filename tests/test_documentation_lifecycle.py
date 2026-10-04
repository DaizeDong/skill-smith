"""Release refusal and pinned documentation-checker interface regressions; no live evidence."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "skills/skill-smith/scripts"))
from make_fixtures import documentation_checker_fixture, documentation_contract_report, release_documentation_fixture
import bump_version as bump
import check_conformance as conformance
import version_sites


@pytest.mark.parametrize("notes", [None, "", "TODO: describe this release.", "<!-- pending -->",
                                  "Adds {{SYNTHETIC_NOTES}} report validation.",
                                  "Adds YOUR_NOTES report validation.",
                                  "Adds synthetic report validation.\n### TODO: additional synthetic notes"])
def test_unfinished_release_refuses_before_any_write(tmp_path, notes):
    repo = release_documentation_fixture(tmp_path, notes=notes)
    before = {name: (repo / name).read_bytes() for name in version_sites.SITE_FILES.values()}
    assert bump.main([str(repo), "--level", "patch", "--date", "2020-01-02"]) == 1
    assert all((repo / name).read_bytes() == original for name, original in before.items())


@pytest.mark.parametrize("value", ["2020-02-30", "2020-1-2", "2019-12-31", "2099-01-02"])
def test_bad_or_regressing_release_date_refuses(tmp_path, value):
    repo = release_documentation_fixture(tmp_path)
    assert bump.main([str(repo), "--level", "patch", "--date", value]) == 1
    assert version_sites.collect(repo)["plugin"] == "0.1.0"


@pytest.mark.parametrize("version", ["0.0.9", "01.2.3", "0.01.2"])
def test_nonadvancing_or_noncanonical_release_refuses(tmp_path, version):
    repo = release_documentation_fixture(tmp_path)
    assert bump.main([str(repo), "--set", version, "--date", "2020-01-02"]) == 1
    assert version_sites.collect(repo)["plugin"] == "0.1.0"


@pytest.mark.parametrize("notes", [None, "TODO: unfinished release.", ""])
def test_supplied_notes_finish_missing_or_placeholder_staging(tmp_path, notes):
    repo = release_documentation_fixture(tmp_path, notes=notes)
    old = (repo / "CHANGELOG.md").read_text(encoding="utf-8").split("## [0.1.0]", 1)[1]
    assert bump.main([str(repo), "--level", "patch", "--date", "2020-01-02",
                      "--notes", "Rejects invalid synthetic report inputs."]) == 0
    text = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    assert text.split("## [0.1.0]", 1)[1] == old
    assert "TODO" not in text and "Rejects invalid synthetic report inputs." in text
    assert "TODO: future synthetic feature." in (repo / "ROADMAP.md").read_text(encoding="utf-8")


def test_substantive_unreleased_does_not_need_duplicate_notes(tmp_path):
    repo = release_documentation_fixture(tmp_path)
    assert bump.main([str(repo), "--level", "patch", "--date", "2020-01-02"]) == 0
    assert "Adds synthetic report validation." in (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    assert version_sites.is_synced(version_sites.collect(repo))


def test_release_notes_can_describe_placeholder_rejection(tmp_path):
    repo = release_documentation_fixture(tmp_path, notes="Rejects TODO and placeholder release bodies before writing.")
    assert bump.main([str(repo), "--level", "patch", "--date", "2020-01-02"]) == 0


@pytest.mark.parametrize("completed", ["Adds synthetic report validation.", "Fix UTF-8."])
def test_supplied_notes_cannot_discard_partially_finished_unreleased(tmp_path, completed):
    repo = release_documentation_fixture(tmp_path, notes=completed + "\n- TODO: add another change.")
    before = {name: (repo / name).read_bytes() for name in version_sites.SITE_FILES.values()}
    assert bump.main([str(repo), "--level", "patch", "--date", "2020-01-02",
                      "--notes", "Rejects invalid synthetic report inputs."]) == 1
    assert all((repo / name).read_bytes() == original for name, original in before.items())


checker_report = documentation_contract_report


def test_delegate_pass_and_named_failure(tmp_path):
    for ok in (True, False):
        documentation_checker_fixture(tmp_path, checker_report(ok), 0 if ok else 1)
        conformance.results.clear()
        conformance.check_documentation(str(tmp_path))
        assert len(conformance.results) == 10
        assert conformance.results[0] == ("documentation: docs.required", ok, "synthetic kit report")
        assert conformance.results[-1][0:2] == ("documentation: unverified boundaries", conformance.WARN)


@pytest.mark.parametrize("fault", ["missing", "malformed", "empty", "wrong_stage", "wrong_exit", "wrong_ok",
                                  "omitted", "duplicate", "unknown", "missing_boundaries", "wrong_failures",
                                  "not_applicable", "all_not_applicable"])
def test_unobserved_or_invalid_checker_is_a_visible_failure(tmp_path, fault):
    report = checker_report()
    if fault == "empty":
        report["checks"] = []
    if fault == "wrong_stage":
        report["stage"] = "draft"
    if fault == "wrong_ok":
        report["ok"] = False
    if fault == "omitted":
        report["checks"].pop()
    if fault == "duplicate":
        report["checks"][-1] = report["checks"][0].copy()
    if fault == "unknown":
        report["checks"][-1]["name"] = "unknown.rule"
    if fault == "missing_boundaries":
        report.pop("unverified")
    if fault == "wrong_failures":
        report["failures"] = [{"name": "docs.required", "detail": "synthetic false failure"}]
    if fault == "not_applicable":
        report["checks"][0]["status"] = "NOT_APPLICABLE"
    if fault == "all_not_applicable":
        for row in report["checks"]:
            row["status"] = "NOT_APPLICABLE"
    if fault != "missing":
        documentation_checker_fixture(tmp_path, report, 1 if fault == "wrong_exit" else 0,
                                      "not json" if fault == "malformed" else None)
    conformance.results.clear()
    conformance.check_documentation(str(tmp_path))
    assert len(conformance.results) == 1 and conformance.results[0][1] is False


def test_delegate_uses_current_kit_root_profile_and_trusted_stage(tmp_path, monkeypatch):
    documentation_checker_fixture(tmp_path, checker_report())
    calls = []
    def execute(args, **kwargs):
        calls.append((args, kwargs))
        report = checker_report()
        report["stage"] = "draft"
        return subprocess.CompletedProcess(args, 0, json.dumps(report), "")
    monkeypatch.setattr(conformance.subprocess, "run", execute)
    conformance.results.clear()
    conformance.check_documentation(str(tmp_path), "draft")
    assert calls[0][0][1:] == [str(tmp_path / "style/tools/doc_contract.py"), "--root",
                              str(tmp_path), "--profile", "skill", "--stage", "draft", "--json"]


def test_main_leaves_version_current_and_badges_to_shared_checker(tmp_path, monkeypatch, capsys):
    from make_fixtures import review11_skill
    review11_skill(tmp_path, "valid")
    documentation_checker_fixture(tmp_path, checker_report())
    for name in ("README.md", "README_CN.md"):
        path = tmp_path / name
        path.write_text(path.read_text(encoding="utf-8").replace("Roadmap-v0.0.1-purple", "Roadmap-current-purple"), encoding="utf-8")
    (tmp_path / "ROADMAP.md").write_text("# Roadmap\nCurrent: see `.claude-plugin/plugin.json`.\n", encoding="utf-8")
    def execute(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, json.dumps(checker_report()) if Path(args[1]).name == "doc_contract.py" else "synthetic scanner clean", "")
    monkeypatch.setattr(conformance.subprocess, "run", execute)
    conformance.results.clear()
    assert conformance.main(str(tmp_path)) == 0
    output = capsys.readouterr().out
    assert "documentation: version.current" in output
    assert "version four-source" not in output and "README badge: Roadmap" not in output
    assert "semantic completeness and bilingual accuracy" in output


def test_scaffold_freeze_instruction_precedes_document_drafting(tmp_path, monkeypatch, capsys):
    import scaffold_skill as scaffold
    monkeypatch.setattr(scaffold, "emit_guards", lambda *args: None)
    monkeypatch.setattr(sys, "argv", ["scaffold_skill.py", "synthetic-tool", "--out-dir", str(tmp_path)])
    assert scaffold.main() == 0
    output = capsys.readouterr().out
    assert output.index("Freeze evaluator policy + holdout BEFORE") < output.index("generation owner completes README")
    assert "--stage draft" in output
