"""Generated instruction targets must distinguish clean reads from failed scans."""
import builtins
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/skill-smith/scripts"
sys.path[:0] = [str(ROOT / "tools"), str(SCRIPTS)]
from make_fixtures import instruction_scan_case


def checker():
    spec = importlib.util.spec_from_file_location("conformance_instruction_scan", SCRIPTS / "check_conformance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("root_layout", [False, True])
def test_readable_instruction_targets_keep_clean_pass(tmp_path, root_layout):
    instruction_scan_case(tmp_path, root_layout)
    target = checker()
    contents = target.check_skill_md_content(str(tmp_path))
    target.results.clear()
    target.check_retrofit_markers(str(tmp_path), contents)
    assert target.results == [
        ("instruction text states rules, not version deltas (2 files scanned)", True, "")]


@pytest.mark.parametrize("root_layout", [False, True])
@pytest.mark.parametrize("unreadable", ["skill", "reference"])
def test_unreadable_instruction_is_a_failed_scan_after_content_admission(
        tmp_path, monkeypatch, root_layout, unreadable):
    paths = instruction_scan_case(tmp_path, root_layout)
    target = checker()
    contents = target.check_skill_md_content(str(tmp_path))
    assert str(paths["skill"]) in contents
    assert all(ok is True for _, ok, _ in target.results)
    target.results.clear()
    original_open = builtins.open

    def deny(path, *args, **kwargs):
        if Path(path) == paths[unreadable]:
            raise PermissionError("Generated instruction read denied")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", deny)
    target.check_retrofit_markers(str(tmp_path), contents)
    failures = [(name, detail) for name, ok, detail in target.results if ok is False]
    assert len(failures) == 1, target.results
    assert "1 of 2 files scanned" in failures[0][1]
    assert "unreadable" in failures[0][1]
    assert paths[unreadable].relative_to(tmp_path).as_posix() in failures[0][1]
    assert not any(ok is True for _, ok, _ in target.results)


def test_readable_marker_stays_visible_when_another_target_is_unreadable(tmp_path, monkeypatch):
    paths = instruction_scan_case(tmp_path, with_marker=True)
    target = checker()
    contents = target.check_skill_md_content(str(tmp_path))
    target.results.clear()
    original_open = builtins.open

    def deny(path, *args, **kwargs):
        if Path(path) == paths["skill"]:
            raise PermissionError("Generated instruction read denied")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", deny)
    target.check_retrofit_markers(str(tmp_path), contents)
    assert any(ok is False for _, ok, _ in target.results), target.results
    warnings = [detail for _, ok, detail in target.results if ok == target.WARN]
    assert len(warnings) == 1 and "1 retrofit marker(s) in 1 of 1 file(s) scanned" in warnings[0]
    assert "Phase 2 adds" in warnings[0]


@pytest.mark.parametrize("unreadable", ["skill", "reference"])
def test_scan_read_failure_makes_full_conformance_exit_nonzero(tmp_path, monkeypatch, capsys, unreadable):
    paths = instruction_scan_case(tmp_path)
    target = checker()
    original_open = builtins.open
    skill_reads = 0

    def deny(path, *args, **kwargs):
        nonlocal skill_reads
        if Path(path) == paths["skill"]:
            skill_reads += 1
        if Path(path) == paths[unreadable] and (unreadable == "reference" or skill_reads > 1):
            raise PermissionError("Generated instruction read denied")
        return original_open(path, *args, **kwargs)

    def external_scanner(args, **kwargs):
        assert Path(args[1]).name in {"pii_guard.py", "data_boundary.py", "dash_guard.py"}
        return SimpleNamespace(returncode=0, stdout="synthetic scanner clean", stderr="")

    monkeypatch.setattr(builtins, "open", deny)
    monkeypatch.setattr(target.subprocess, "run", external_scanner)
    assert target.main(str(tmp_path)) == 1
    output = capsys.readouterr().out
    assert "[PASS] SKILL.md content" in output
    assert "[FAIL] instruction text" in output and "unreadable" in output


def test_readable_marker_keeps_nonblocking_warning(tmp_path):
    instruction_scan_case(tmp_path, with_marker=True)
    target = checker()
    contents = target.check_skill_md_content(str(tmp_path))
    target.results.clear()
    target.check_retrofit_markers(str(tmp_path), contents)
    assert len(target.results) == 1
    assert target.results[0][1] == target.WARN
    assert "1 retrofit marker(s) in 1 of 2 file(s) scanned" in target.results[0][2]
