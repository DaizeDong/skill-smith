"""Offline failure controls for generated guards and canonical templates."""
from pathlib import Path
from types import SimpleNamespace
import shutil
import pytest
import scaffold_skill as scaffold


def complete_kit(root, name):
    kit = root / name
    source = Path(scaffold.__file__).resolve().parents[3] / name
    shutil.copytree(source, kit, ignore=shutil.ignore_patterns('.git', '__pycache__', '.pytest_cache'))
    (kit / '.git').parent.mkdir(parents=True, exist_ok=True)
    (kit / '.git').write_text('gitdir: ../.git/modules/' + name)


def test_generated_hooks_and_style_ci_follow_canonical_sources(tmp_path, monkeypatch):
    (tmp_path / '.git').mkdir()
    complete_kit(tmp_path, 'guards')
    complete_kit(tmp_path, 'style')
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(scaffold.subprocess, 'run', run)
    scaffold.emit_guards(str(tmp_path), False, 'demo')
    assert ['git', 'config', 'core.hooksPath', '.githooks'] in calls
    source = Path(scaffold.__file__).resolve().parents[3]
    for hook in ('pre-commit', 'pre-push'):
        assert (tmp_path / '.githooks' / hook).read_bytes() == (source / '.githooks' / hook).read_bytes()
    for name in ('dash-guard', 'load-budget'):
        body = (tmp_path / '.github/workflows' / (name + '.yml')).read_text()
        assert 'uses: ./style/ci/' + name in body


def test_empty_existing_submodule_cannot_be_accepted(tmp_path, monkeypatch):
    (tmp_path / '.git').mkdir()
    (tmp_path / 'guards').mkdir()
    (tmp_path / 'style').mkdir()
    monkeypatch.setattr(scaffold.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stderr=''))
    with pytest.raises(SystemExit, match='incomplete'):
        scaffold.emit_guards(str(tmp_path), False, 'demo')


def test_hook_config_failure_is_not_reported_success(tmp_path, monkeypatch):
    (tmp_path / '.git').mkdir()
    complete_kit(tmp_path, 'guards')
    complete_kit(tmp_path, 'style')
    monkeypatch.setattr(scaffold.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1, stderr='synthetic denied'))
    with pytest.raises(SystemExit, match='hooksPath'):
        scaffold.emit_guards(str(tmp_path), False, 'demo')
