"""Synthetic native protocol and process-tree cleanup tests; never launch Codex."""
import importlib.util
import json
from pathlib import Path
import sys
import time

import pytest

from skill_smith.catalog import discover
from tools.make_fixtures import skill, text_file, write_json


@pytest.fixture
def native():
    assert importlib.util.find_spec('skill_smith.native_discovery'), 'bounded native acquisition is missing'
    from skill_smith import native_discovery
    return native_discovery


def config(tmp_path):
    executable = tmp_path / 'codex.exe'
    text_file(executable, 'synthetic executable placeholder')
    (tmp_path / 'codex-home').mkdir(exist_ok=True)
    return dict(enabled=True, executable=str(executable), codex_home=str(tmp_path / 'codex-home'),
                cwd=str(tmp_path), timeout_seconds=4, max_output_bytes=65536)


SERVER = r'''
import json, pathlib, subprocess, sys, time
mode = sys.argv[1]
root = pathlib.Path.cwd()
subprocess.Popen([sys.executable, '-B', '-c',
    "import pathlib,time; p=pathlib.Path('heartbeat');\nwhile True: p.write_text(str(time.monotonic())); time.sleep(.03)"])
deadline = time.monotonic() + 2
while not (root / 'heartbeat').exists() and time.monotonic() < deadline: time.sleep(.01)
if mode == 'timeout': time.sleep(30)
if mode == 'stdout': sys.stdout.write('x' * 100000); sys.stdout.flush(); time.sleep(30)
if mode == 'stderr': sys.stderr.write('x' * 100000); sys.stderr.flush(); time.sleep(30)
if mode == 'malformed': print('{broken', flush=True); time.sleep(30)
for line in sys.stdin:
    row = json.loads(line)
    with (root / 'methods.jsonl').open('a') as f: f.write(json.dumps(row) + '\n')
    if row['method'] == 'initialize':
        print(json.dumps({'id': 1, 'result': {}}), flush=True)
    elif row['method'] == 'skills/list':
        if mode == 'rpc_error': print(json.dumps({'id': 2, 'error': {'message': 'SYNTHETIC_SECRET'}}), flush=True)
        elif mode == 'wrong_id': print(json.dumps({'id': 99, 'result': {}}), flush=True)
        else: print(json.dumps({'id': 2, 'result': {'data': [{'cwd': str(root), 'skills': [], 'errors': []}]}}), flush=True)
        time.sleep(30)
'''


@pytest.mark.skipif(sys.platform != 'win32', reason='WindowsJob containment contract')
@pytest.mark.parametrize('mode, error', [('success', None), ('timeout', 'timeout'),
    ('stdout', 'output_limit'), ('stderr', 'output_limit'), ('malformed', 'invalid_protocol'),
    ('rpc_error', 'rpc_error'), ('wrong_id', 'invalid_protocol')])
def test_bounded_protocol_and_descendant_cleanup(native, monkeypatch, tmp_path, mode, error):
    from llmcall import process
    settings = config(tmp_path)
    real_job = process.WindowsJob
    children = []

    class SyntheticJob(real_job):
        def spawn(self, command, **options):
            assert command == [settings['executable'], 'app-server', '--strict-config',
                               '-c', 'check_for_update_on_startup=false', '-c', 'analytics.enabled=false']
            assert options['env']['CODEX_HOME'] == settings['codex_home']
            assert options['cwd'] == settings['cwd']
            child = super().spawn([sys.executable, '-B', '-c', SERVER, mode], **options)
            children.append(child)
            return child

    monkeypatch.setattr(process, 'WindowsJob', SyntheticJob)
    started = time.monotonic()
    if error:
        with pytest.raises(native.NativeDiscoveryError) as caught:
            native.acquire(settings)
        assert caught.value.code == error
        assert 'SYNTHETIC_SECRET' not in str(caught.value)
    else:
        capture = native.acquire(settings)
        assert capture['result']['data'][0]['skills'] == []
        assert capture['observed_at']
    assert time.monotonic() - started < 5
    assert all(child.poll() is not None for child in children)
    before = (tmp_path / 'heartbeat').read_text()
    time.sleep(.15)
    assert (tmp_path / 'heartbeat').read_text() == before
    if mode == 'success':
        messages = [json.loads(line) for line in (tmp_path / 'methods.jsonl').read_text().splitlines()]
        assert [m['method'] for m in messages] == ['initialize', 'initialized', 'skills/list']
        assert messages[2]['params'] == {'cwds': [str(tmp_path)], 'forceReload': True}


@pytest.mark.parametrize('change', [dict(enabled=1), dict(executable='codex.exe'),
    dict(codex_home='relative'), dict(cwd='.'), dict(command=['arbitrary']),
    dict(timeout_seconds=0), dict(timeout_seconds=61), dict(timeout_seconds=float('nan')),
    dict(max_output_bytes=True), dict(max_output_bytes=17000000), dict(timeout_seconds=10 ** 1000)])
def test_invalid_acquisition_never_spawns(native, monkeypatch, tmp_path, change):
    from llmcall import process
    monkeypatch.setattr(process, 'WindowsJob', lambda: pytest.fail('invalid input launched a job'))
    with pytest.raises(native.NativeDiscoveryError):
        native.acquire(dict(config(tmp_path), **change))


def test_disabled_acquisition_never_spawns(native, monkeypatch):
    from llmcall import process
    monkeypatch.setattr(process, 'WindowsJob', lambda: pytest.fail('disabled input launched a job'))
    assert native.acquire({'enabled': False}) is None


def test_exact_native_mapping_preserves_disabled_and_unknown_entries(native, monkeypatch, tmp_path):
    for folder in ('first', 'second', 'third'):
        skill(tmp_path / 'skills' / folder, 'same-name')
    captured = '2026-01-01T00:00:10Z'
    rows = [{'path': str(tmp_path / 'skills' / folder / 'SKILL.md'), 'enabled': value,
             'name': 'irrelevant-native-name', 'scope': 'User'}
            for folder, value in [('first', True), ('second', False), ('third', None)]]
    rows.append({'path': str(tmp_path / 'unmapped/SKILL.md'), 'enabled': True, 'name': 'same-name'})
    monkeypatch.setattr(native, 'acquire', lambda _: {'observed_at': captured,
        'result': {'data': [{'cwd': str(tmp_path), 'skills': rows, 'errors': []}]}})
    result = discover({'skill_roots': [{'path': str(tmp_path / 'skills'), 'client': 'codex'}],
                       'native_discovery': {'enabled': True, 'cwd': str(tmp_path)}}, now='2026-01-01T00:01:00Z')
    entries = {ep['install_name']: ep for r in result['records'] for ep in r['entrypoints']}
    assert {name: ep['status']['discovered'] for name, ep in entries.items()} == {
        'first': 'yes', 'second': 'no', 'third': 'unknown'}
    assert entries['first']['evidence']['discovered']['observed_at'] == captured
    assert entries['second']['status']['enabled'] == 'no'
    assert all(ep['status']['compatible'] == 'unknown' for ep in entries.values())
    assert result['coverage']['native_discovery']['status'] == 'partial'
    observed = result['native_discovery']['entrypoints']
    assert len(observed) == 4
    assert observed[0]['source_id'] == entries['first']['source_id']
    assert observed[-1]['match'] == 'unmatched'


def test_duplicate_exact_catalog_paths_never_choose_a_source(native, monkeypatch, tmp_path):
    skill(tmp_path / 'skills/demo')
    monkeypatch.setattr(native, 'acquire', lambda _: {'observed_at': '2026-01-01T00:00:00Z',
        'result': {'data': [{'cwd': str(tmp_path), 'skills': [
            {'path': str(tmp_path / 'skills/demo/SKILL.md'), 'enabled': True}], 'errors': []}]}})
    result = discover({'skill_roots': [{'path': str(tmp_path / 'skills'), 'client': 'codex', 'namespace': ns}
                                      for ns in ('one', 'two')],
                       'native_discovery': {'enabled': True, 'cwd': str(tmp_path)}})
    assert len(result['records']) == 2
    assert all(ep['status']['discovered'] == 'unknown' for r in result['records'] for ep in r['entrypoints'])
    assert result['native_discovery']['entrypoints'][0]['match'] == 'ambiguous'
    assert result['coverage']['native_discovery']['status'] == 'partial'


@pytest.mark.parametrize('mode', ['load_error', 'missing_enabled', 'duplicate', 'wrong_cwd', 'bad_errors'])
def test_partial_native_data_never_promotes_unknown(native, monkeypatch, tmp_path, mode):
    skill(tmp_path / 'skills/demo')
    row = {'path': str(tmp_path / 'skills/demo/SKILL.md'), 'enabled': True}
    scope = {'cwd': str(tmp_path), 'skills': [row], 'errors': []}
    if mode == 'load_error': scope['errors'] = [{'message': 'SYNTHETIC_SECRET'}]
    if mode == 'missing_enabled': row.pop('enabled')
    if mode == 'duplicate': scope['skills'].append(dict(row, enabled=False))
    if mode == 'wrong_cwd': scope['cwd'] = str(tmp_path / 'other')
    if mode == 'bad_errors': scope['errors'] = {}
    monkeypatch.setattr(native, 'acquire', lambda _: {'observed_at': '2026-01-01T00:00:00Z', 'result': {'data': [scope]}})
    result = discover({'skill_roots': [{'path': str(tmp_path / 'skills'), 'client': 'codex'}],
                       'native_discovery': {'enabled': True, 'cwd': str(tmp_path)}})
    assert result['coverage']['native_discovery']['status'] == 'partial'
    assert 'SYNTHETIC_SECRET' not in json.dumps(result)
    ep = result['records'][0]['entrypoints'][0]
    assert ep['status']['discovered'] == ('yes' if mode in ('load_error', 'bad_errors') else 'unknown')


@pytest.mark.skipif(sys.platform != 'win32', reason='WindowsJob containment contract')
@pytest.mark.parametrize('failure', ['close', 'start', 'spawn', 'thread_start'])
def test_lifecycle_failures_are_not_success(native, monkeypatch, tmp_path, failure):
    from llmcall import process
    settings = config(tmp_path)
    real_job = process.WindowsJob
    children, jobs = [], []

    class SyntheticJob(real_job):
        def __init__(self):
            super().__init__()
            jobs.append(self)

        def spawn(self, command, **options):
            if failure == 'spawn': raise OSError('SYNTHETIC_SECRET')
            child = super().spawn([sys.executable, '-B', '-c', SERVER, 'success'], **options)
            children.append(child)
            return child

        def start(self, child):
            if failure == 'start': raise OSError('SYNTHETIC_SECRET')
            super().start(child)

        def close(self):
            super().close()
            if failure == 'close': raise OSError('SYNTHETIC_SECRET')

    monkeypatch.setattr(process, 'WindowsJob', SyntheticJob)
    if failure == 'thread_start':
        monkeypatch.setattr(native.Thread, 'start', lambda _: (_ for _ in ()).throw(RuntimeError('SYNTHETIC_SECRET')))
    with pytest.raises(native.NativeDiscoveryError) as caught:
        native.acquire(settings)
    assert caught.value.code == ('cleanup_failed' if failure == 'close' else
                                 'launch_failed' if failure == 'spawn' else 'io_failed')
    assert all(child.poll() is not None for child in children)
    assert all(job.handle is None for job in jobs)


def test_parent_cancellation_and_deadline_prevent_launch(native, monkeypatch, tmp_path):
    from threading import Event
    from llmcall import process
    settings = config(tmp_path)
    monkeypatch.setattr(process, 'WindowsJob', lambda: pytest.fail('cancelled input launched a job'))
    cancel = Event()
    cancel.set()
    with process.execution_scope(cancel=cancel), pytest.raises(native.NativeDiscoveryError, match='cancelled'):
        native.acquire(settings)
    with process.execution_scope(timeout=0), pytest.raises(native.NativeDiscoveryError, match='timeout'):
        native.acquire(settings)


def test_ambiguous_native_result_does_not_retain_supplied_yes(native, monkeypatch, tmp_path):
    skill(tmp_path / 'skills/demo')
    request = {'skill_roots': [{'path': str(tmp_path / 'skills'), 'client': 'codex'}]}
    ep = discover(request)['records'][0]['entrypoints'][0]
    prior = {key: ep[key] for key in ('source_id', 'kind', 'name', 'client', 'scope')}
    prior.update(discovered='yes', observed_at='2026-01-01T00:00:00Z')
    request['runtime_discovery'] = write_json(tmp_path / 'prior.json', {'entrypoints': [prior]})
    request['native_discovery'] = {'enabled': True, 'cwd': str(tmp_path)}
    row = {'path': str(tmp_path / 'skills/demo/SKILL.md'), 'enabled': True}
    monkeypatch.setattr(native, 'acquire', lambda _: {'observed_at': '2026-01-01T00:01:00Z',
        'result': {'data': [{'cwd': str(tmp_path), 'skills': [row, dict(row, enabled=False)], 'errors': []}]}})
    result = discover(request)
    assert result['records'][0]['entrypoints'][0]['status']['discovered'] == 'unknown'


@pytest.mark.parametrize('malformed', [None, [], {'enabled': True, 'command': 'arbitrary'}])
def test_catalog_contains_invalid_native_config_as_partial(native, malformed):
    result = discover({'native_discovery': malformed})
    assert result['coverage']['native_discovery']['status'] == 'partial'
    assert result['problems'][0]['reason'] == 'invalid_config'


def test_catalog_native_failure_keeps_independent_inventory(native, monkeypatch, tmp_path):
    skill(tmp_path / 'skills/demo')

    def fail(_):
        raise native.NativeDiscoveryError('timeout')

    monkeypatch.setattr(native, 'acquire', fail)
    result = discover({'skill_roots': [{'path': str(tmp_path / 'skills'), 'client': 'codex'}],
                       'native_discovery': {'enabled': True}})
    assert len(result['records']) == 1
    assert result['coverage']['skill_roots']['status'] == 'checked'
    assert result['coverage']['native_discovery']['status'] == 'partial'
    assert result['records'][0]['entrypoints'][0]['status']['discovered'] == 'unknown'


def test_missing_process_owner_api_is_explicit(native, monkeypatch, tmp_path):
    from llmcall import process
    monkeypatch.delattr(process, 'remaining_timeout')
    with pytest.raises(native.NativeDiscoveryError, match='process_owner_unavailable'):
        native.acquire(config(tmp_path))
