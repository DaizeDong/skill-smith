"""Safety regressions; real local git operations, no commits or network."""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/skill-smith/scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("scaffold_guard_test", SCRIPTS / "scaffold_skill.py")
scaffold = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scaffold)


def test_empty_existing_kit_is_not_an_installed_guard(tmp_path):
    (tmp_path / "guards").mkdir()
    with pytest.raises(SystemExit, match="(?i)(empty|invalid|submodule|missing)"):
        scaffold.emit_guards(str(tmp_path), False, "synthetic-tool")


def test_fresh_scaffold_tracks_fail_closed_forwarders(tmp_path):
    scaffold.emit_guards(str(tmp_path), False, "synthetic-tool")
    result = subprocess.run(["git", "config", "core.hooksPath"], cwd=tmp_path, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == ".githooks"
    tracked = subprocess.run(["git", "ls-files", ".githooks"], cwd=tmp_path, capture_output=True, text=True, check=True).stdout
    assert ".githooks/pre-commit" in tracked and ".githooks/pre-push" in tracked
    for hook in ("pre-commit", "pre-push"):
        text = (tmp_path / ".githooks" / hook).read_text(encoding="utf-8")
        assert 'exit 1' in text and f'guards/hooks/{hook}' in text
    assert './style/ci/dash-guard' in (tmp_path / '.github/workflows/dash-guard.yml').read_text()
    assert './style/ci/load-budget' in (tmp_path / '.github/workflows/load-budget.yml').read_text()


def test_failed_hooks_config_is_not_success(tmp_path, monkeypatch):
    original = scaffold.subprocess.run
    def fail_config(args, **kwargs):
        if args[:3] == ["git", "config", "core.hooksPath"]:
            return subprocess.CompletedProcess(args, 1, "", "synthetic config failure")
        return original(args, **kwargs)
    monkeypatch.setattr(scaffold.subprocess, "run", fail_config)
    with pytest.raises(SystemExit, match="(?i)config"):
        scaffold.emit_guards(str(tmp_path), False, "synthetic-tool")


def test_wrong_existing_kit_identity_is_rejected(tmp_path):
    scaffold.emit_guards(str(tmp_path), False, "synthetic-tool")
    subprocess.run(["git", "config", "remote.origin.url", "https://github.com/example/other-kit.git"],
                   cwd=tmp_path / "guards", check=True)
    with pytest.raises(SystemExit, match="identity"):
        scaffold.emit_guards(str(tmp_path), True, "synthetic-tool")


def test_actual_git_hook_blocks_when_the_guard_is_missing(tmp_path):
    scaffold.emit_guards(str(tmp_path), False, "synthetic-tool")
    real = tmp_path / "guards/hooks/pre-commit"
    real.rename(real.with_suffix(".absent"))
    result = subprocess.run(["git", "hook", "run", "pre-commit"], cwd=tmp_path,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert "BLOCKED: guard hook missing" in result.stderr
