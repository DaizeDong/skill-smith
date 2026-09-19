"""Offline failure controls for the final T07 review findings."""
import builtins
import errno
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys

import budget_check
import dedup_check
import pytest
import scaffold_skill as scaffold
from skill_smith import catalog
from tools.make_fixtures import directory_link, external, plugins, skill, text_file, write_json

ROOT = Path(__file__).resolve().parents[1]
CANARY = 'SYNTHETIC_CANARY_VALUE'
KIT_ENTRIES = {
    'guards': ('hooks/pre-commit', 'hooks/pre-push', 'ci/pii-guard/action.yml',
               'tools/pii_guard.py', 'tools/data_boundary.py', 'tools/test_pii_guard.py',
               'tools/test_pii_guard_v2.py', 'tools/test_datadir.py',
               'tools/test_companion_contract.py'),
    'style': ('ci/dash-guard/action.yml', 'ci/load-budget/action.yml',
              'tools/dash_guard.py', 'tools/load_budget.py',
              'tools/test_dash_guard.py', 'tools/test_load_budget.py'),
}


def prepared_target(root):
    for name in KIT_ENTRIES:
        shutil.copytree(ROOT / name, root / name,
                        ignore=shutil.ignore_patterns('.git', '__pycache__', '.pytest_cache'))
        text_file(root / name / '.git', 'gitdir: ../.git/modules/' + name)
    (root / '.git').mkdir()
    text_file(root / 'README.md', 'Synthetic existing work; preserve on failure.\n')
    return root


def tree_contents(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() if p.is_file() else None
            for p in root.rglob('*')}


def no_transport(*args, **kwargs):
    pytest.fail('preflight must finish before any Git mutation')


def test_scaffold_invoked_through_real_directory_link(tmp_path, monkeypatch):
    link = tmp_path / 'profile/skills/skill-smith'
    try:
        directory_link(link, ROOT / 'skills/skill-smith')
    except OSError as exc:
        if getattr(exc, 'winerror', None) == 1314 or (os.name != 'nt' and exc.errno == errno.EPERM):
            pytest.skip('OS privilege to create directory links is unavailable')
        raise
    if os.name == 'nt':
        assert link.is_junction()
    target = prepared_target(tmp_path / 'out/demo')
    invoked = link / 'scripts/scaffold_skill.py'
    assert invoked != invoked.resolve()
    calls = []
    def git(command, **kwargs):
        assert command == ['git', 'config', 'core.hooksPath', '.githooks']
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, '', '')
    monkeypatch.setattr(subprocess, 'run', git)
    monkeypatch.setattr(sys, 'argv', [str(invoked), 'demo', '--out-dir', str(target.parent), '--force'])
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(invoked), run_name='__main__')
    assert result.value.code == 0
    assert len(calls) == 1
    for relative in ('.githooks/pre-commit', '.github/workflows/pii-guard.yml'):
        assert (target / relative).read_bytes() == (ROOT / relative).read_bytes()


@pytest.mark.parametrize('missing', [
    '.githooks/pre-commit', '.githooks/pre-push',
    '.github/workflows/pii-guard.yml', '.github/workflows/dash-guard.yml',
    '.github/workflows/load-budget.yml',
])
@pytest.mark.parametrize('existing', [False, True])
def test_missing_template_stops_before_any_mutation(tmp_path, monkeypatch, missing, existing):
    source = tmp_path / 'source'
    for directory in ('.githooks', '.github/workflows'):
        shutil.copytree(ROOT / directory, source / directory)
    (source / missing).unlink()
    monkeypatch.setattr(scaffold, 'SOURCE_ROOT', str(source))
    target = tmp_path / 'out/demo'
    if existing:
        prepared_target(target)
    before = tree_contents(tmp_path / 'out')
    monkeypatch.setattr(scaffold.subprocess, 'run', no_transport)
    monkeypatch.setattr(sys, 'argv', ['scaffold', 'demo', '--out-dir', str(target.parent), '--force'])
    with pytest.raises(SystemExit, match='template'):
        scaffold.main()
    assert tree_contents(tmp_path / 'out') == before
    assert target.exists() == existing


@pytest.mark.parametrize('kit,missing', [(kit, entry) for kit, entries in KIT_ENTRIES.items() for entry in entries])
def test_missing_required_kit_entry_stops_before_any_mutation(tmp_path, monkeypatch, kit, missing):
    target = prepared_target(tmp_path / 'out/demo')
    (target / kit / missing).unlink()
    before = tree_contents(target)
    monkeypatch.setattr(scaffold.subprocess, 'run', no_transport)
    monkeypatch.setattr(sys, 'argv', ['scaffold', 'demo', '--out-dir', str(target.parent), '--force'])
    with pytest.raises(SystemExit, match='incomplete ' + kit):
        scaffold.main()
    assert tree_contents(target) == before


@pytest.mark.parametrize('failure', ['decode', 'read', 'stat'])
def test_unreadable_agent_retains_readable_skill_and_partial_coverage(tmp_path, monkeypatch, failure):
    request = plugins(tmp_path)
    agent = Path(text_file(tmp_path / 'cache/market-b/2/agents/reviewer.md', 'Synthetic agent.'))
    if failure == 'decode':
        agent.write_bytes(b'\xff')
    elif failure == 'read':
        def denied(path, *args, **kwargs):
            if Path(path) == agent:
                raise PermissionError(CANARY)
            return builtins.open(path, *args, **kwargs)
        monkeypatch.setattr(catalog, 'open', denied, raising=False)
    else:
        original_stat = os.stat
        def denied_stat(path, *args, **kwargs):
            if Path(path) == agent:
                raise PermissionError(CANARY)
            return original_stat(path, *args, **kwargs)
        monkeypatch.setattr(os, 'stat', denied_stat)
    snapshot = catalog.discover(request)
    plugin = next(r for r in snapshot['records'] if r['registry_key'] == 'demo@market-b')
    assert plugin['status']['resolved'] == 'yes'
    assert plugin['resolution'] == 'resolved'
    assert snapshot['coverage']['plugin_registries']['status'] == 'partial'
    assert [(e['kind'], e['name']) for e in plugin['entrypoints']] == [('skill', 'demo')]
    rows, problems = budget_check.rows_from_catalog(snapshot, None)
    assert [(r.name, r.owner) for r in rows] == [('demo', 'demo@market-b')]
    assert len(dedup_check.items_from_catalog(snapshot)) == 1
    assert problems and any(p.get('source_id') == plugin['source_id'] for p in snapshot['problems'])
    assert CANARY not in json.dumps(snapshot)


EXTERNAL_FIELDS = [('repo', f) for f in ('url', 'dir', 'branch', 'commit')]
EXTERNAL_FIELDS += [('skill', f) for f in ('name', 'subPath')]
EXTERNAL_FIELDS += [('vendored', f) for f in ('name', 'subPath', 'upstream', 'commit', 'vendored')]
EXTERNAL_FIELDS += [('manifest', f) for f in ('skillRepoRoot', 'vendoredRoot')]


@pytest.mark.parametrize('section,field', EXTERNAL_FIELDS)
@pytest.mark.parametrize('shape', ['object', 'list'])
def test_malformed_external_fields_never_reach_records_or_hashing(tmp_path, monkeypatch, capsys, section, field, shape):
    request = external(tmp_path)
    skill(tmp_path / 'vendor/local-copy')
    skill(tmp_path / 'repos/demo-kit/skills/invoice')
    manifest = Path(request['external_skill_repos'])
    data = json.loads(manifest.read_text())
    item = {'repo': data['repos'][0], 'skill': data['repos'][0]['skills'][0],
            'vendored': data['vendored'][0], 'manifest': data}[section]
    item[field] = {'env': {'TOKEN': CANARY}} if shape == 'object' else [CANARY]
    write_json(manifest, data)
    original_record = catalog.new_record
    def checked_record(*args, **kwargs):
        assert CANARY not in json.dumps([args, kwargs]), 'validation must precede identity hashing'
        return original_record(*args, **kwargs)
    monkeypatch.setattr(catalog, 'new_record', checked_record)
    snapshot = catalog.discover(request)
    assert snapshot['coverage']['external_skill_repos']['status'] == 'partial'
    assert len(snapshot['records']) == 1, 'healthy sibling declarations must survive'
    assert snapshot['records'][0]['status']['resolved'] == 'yes'
    assert CANARY not in json.dumps(snapshot)
    captured = capsys.readouterr()
    assert CANARY not in captured.out + captured.err


@pytest.mark.parametrize('field', ['approved_roots', 'profile_home'])
@pytest.mark.parametrize('shape', ['object', 'list'])
def test_malformed_request_roots_are_partial_without_disclosure(tmp_path, field, shape):
    request = external(tmp_path)
    request[field] = {'env': {'TOKEN': CANARY}} if shape == 'object' else [{'TOKEN': CANARY}]
    snapshot = catalog.discover(request)
    assert snapshot['coverage']['external_skill_repos']['status'] == 'partial'
    assert snapshot['records'] == []
    assert CANARY not in json.dumps(snapshot)
