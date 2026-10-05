"""Regressions from independent review; all inputs are generated or synthetic."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from test_acceptance import evaluate, rewrite_gate, gate_module
from test_scaffold_guards import scaffold
from test_fleet_acceptance_boundaries import fc
from make_fixtures import config_lifecycle, write_json

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT/'skills/skill-smith/scripts'
spec = importlib.util.spec_from_file_location('config_review_regression', SCRIPTS/'check_config_conformance.py')
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, check=True, timeout=30)


@pytest.mark.parametrize('gate', ['G1', 'G2'])
@pytest.mark.parametrize('status,exit_code', [('failed', 73), ('unavailable', 74), ('passed', True), ('passed', '0')])
def test_measured_scores_do_not_override_failed_completion(tmp_path, gate, status, exit_code):
    def mutate(_policy, manifest, root):
        rewrite_gate(manifest, root, gate, lambda value: value.update(gate=gate, status=status, exit_code=exit_code))
    result = evaluate(tmp_path, mutate)
    assert result['gates'][gate]['status'] == 'rejected'
    assert gate in result['resume_gates'] and not result['accepted']


def test_relabeling_fixtures_cannot_self_approve_acceptance(tmp_path):
    def mutate(_policy, manifest, root):
        for gate in manifest['gates']:
            rewrite_gate(manifest, root, gate, lambda value: value['provenance'].update(fixture=False))
    result = evaluate(tmp_path, mutate)
    assert result['contract_valid'] and not result['accepted']
    assert result['verdict'] == 'independent_review_required'


@pytest.mark.parametrize('hook', ['pre-commit', 'pre-push'])
def test_actual_forwarder_blocks_empty_guard_and_reinstall_rejects_it(tmp_path, hook):
    scaffold.emit_guards(str(tmp_path), False, 'synthetic-tool')
    (tmp_path/'guards/hooks'/hook).write_bytes(b'')
    result = subprocess.run(['git', 'hook', 'run', hook], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and 'BLOCKED' in result.stderr
    with pytest.raises(SystemExit, match='empty|modified|dirty'):
        scaffold.emit_guards(str(tmp_path), True, 'synthetic-tool')


def test_gitlink_mismatch_rejects_existing_kit(tmp_path):
    scaffold.emit_guards(str(tmp_path), False, 'synthetic-tool')
    git(tmp_path, 'update-index', '--cacheinfo', '160000,'+'a'*40+',guards')
    with pytest.raises(SystemExit, match='revision|gitlink'):
        scaffold.verify_kit(str(tmp_path), scaffold.GUARDS_URL, 'guards')


def test_hook_permission_failure_is_not_reported_as_installed(tmp_path, monkeypatch):
    git(tmp_path, 'init', '-q')
    def fail_permissions(*args, **kwargs):
        raise OSError('synthetic permission failure')
    monkeypatch.setattr(scaffold.os, 'chmod', fail_permissions)
    with pytest.raises(OSError, match='permission failure'):
        scaffold.emit_hook_forwarders(str(tmp_path), False)


@pytest.mark.parametrize('description', [None, 'Use: quoted "content"', 'First line\nSecond: line', 'Text --- delimiter'])
def test_scaffold_frontmatter_is_valid_yaml(tmp_path, description):
    args = [sys.executable, str(SCRIPTS/'scaffold_skill.py'), 'acme-generated', '--out-dir', str(tmp_path)]
    if description is not None:
        args += ['--description', description]
    result = subprocess.run(args, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    front = (tmp_path/'acme-generated/skills/acme-generated/SKILL.md').read_text(encoding='utf-8')[4:].split('\n---\n', 1)[0]
    fields = yaml.safe_load(front)
    assert isinstance(fields['description'], str)
    if description is not None:
        assert fields['description'] == description


@pytest.mark.parametrize('name', ['on', 'true', 'null'])
def test_valid_skill_names_remain_yaml_strings(tmp_path, monkeypatch, name):
    monkeypatch.setattr(scaffold, 'emit_guards', lambda *args: None)
    monkeypatch.setattr(sys, 'argv', ['scaffold_skill.py', name, '--out-dir', str(tmp_path)])
    assert scaffold.main() == 0
    document = (tmp_path/name/'skills'/name/'SKILL.md').read_text(encoding='utf-8')
    assert yaml.safe_load(document[4:].split('\n---\n', 1)[0])['name'] == name


def test_snapshot_changes_when_executable_mode_changes(tmp_path):
    git(tmp_path, 'init', '-q')
    (tmp_path/'entry.sh').write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
    git(tmp_path, 'add', '--chmod=-x', 'entry.sh')
    gate = gate_module()
    before = gate.candidate_snapshot(tmp_path)
    git(tmp_path, 'update-index', '--chmod=+x', 'entry.sh')
    assert gate.candidate_snapshot(tmp_path) != before


def test_snapshot_binds_submodule_gitlink_and_checked_out_revision(tmp_path):
    scaffold.emit_guards(str(tmp_path), False, 'synthetic-tool')
    gate = gate_module()
    before = gate.candidate_snapshot(tmp_path)
    git(tmp_path, 'update-index', '--cacheinfo', '160000,'+'a'*40+',guards')
    assert gate.candidate_snapshot(tmp_path) != before


@pytest.mark.parametrize('condition', ['false', '"false"', '${{ false }}', '${{ (false) }}'])
@pytest.mark.parametrize('scope', ['job', 'step'])
def test_disabled_expression_is_not_guard_coverage(condition, scope):
    job_condition = f'    if: {condition}\n' if scope == 'job' else ''
    step_condition = f'        if: {condition}\n' if scope == 'step' else ''
    body = ('jobs:\n  guard:\n'+job_condition+'    steps:\n      - uses: ./guards/ci/pii-guard\n'+step_condition)
    assert fc.workflow_guards(body) == []


@pytest.mark.parametrize('steps', ['unavailable', {}, [None], [{'status': 'unknown'}]])
def test_malformed_steps_never_prove_execution(monkeypatch, steps):
    monkeypatch.setattr(fc, 'run', lambda *args, **kwargs: (0, json.dumps({'jobs': [{'steps': steps}]}), ''))
    assert fc.ci_execution_detail('fake-gh', 'example/acme', 1, 10)[0] == 'unknown'


@pytest.mark.parametrize('status,conclusion', [('queued', None), ('completed', 'skipped')])
def test_recorded_but_unexecuted_step_is_not_execution(monkeypatch, status, conclusion):
    payload = {'jobs': [{'steps': [{'number': 1, 'status': status, 'conclusion': conclusion}]}]}
    monkeypatch.setattr(fc, 'run', lambda *args, **kwargs: (0, json.dumps(payload), ''))
    assert fc.ci_execution_detail('fake-gh', 'example/acme', 1, 10)[0] == 'unknown'


def test_unknown_condition_is_reported_without_claiming_execution():
    conditional = set()
    body = "jobs:\n  guard:\n    if: github.ref == 'refs/heads/main'\n    steps:\n      - uses: ./guards/ci/pii-guard\n"
    assert fc.workflow_guards(body, conditional) == ['pii-guard']
    assert conditional == {'pii-guard'}


@pytest.mark.parametrize('branch,rc,stderr,expected', [('', 0, '', 'no default branch'), ('', 1, 'unavailable', 'could not reach')])
def test_remote_branch_failures_keep_their_meaning(monkeypatch, branch, rc, stderr, expected):
    monkeypatch.setattr(fc.shutil, 'which', lambda name: 'fake-gh')
    monkeypatch.setattr(fc, 'run', lambda *args, **kwargs: (rc, branch, stderr))
    found, reason = fc.remote_guard_coverage('example/acme', [], 10)
    assert found is None and expected in reason


def test_online_main_uses_real_workflow_path_with_only_remote_transport_mocked(tmp_path, monkeypatch, capsys):
    code = tmp_path/'code'
    repo = code/'acme-tool'
    repo.mkdir(parents=True)
    skills = tmp_path/'skills'
    skills.mkdir()
    git(repo, 'init', '-q')
    git(repo, 'config', 'remote.origin.url', 'https://github.com/example/acme-tool.git')
    visibility = tmp_path/'visibility.json'
    write_json(visibility, {'example/acme-tool': 'PUBLIC'})
    real_run, real_which = fc.run, fc.shutil.which
    requests = []
    def run(args, **kwargs):
        if args[0] != 'synthetic-gh':
            return real_run(args, **kwargs)
        requests.append(args)
        if args[-1] == '.visibility': return 0, 'PUBLIC\n', ''
        if args[-1] == '.default_branch': return 0, 'main\n', ''
        if '/contents/.github/workflows?' in args[2]: return 0, 'custom.yml\n', ''
        if '/contents/.github/workflows/custom.yml?' in args[2]:
            return 0, 'jobs:\n  guard:\n    steps:\n      - uses: ./guards/ci/pii-guard\n      - uses: ./style/ci/dash-guard\n', ''
        if args[1:3] == ['run', 'list']: return 0, '[]', ''
        raise AssertionError('Unexpected remote transport: '+repr(args))
    monkeypatch.setattr(fc, 'run', run)
    monkeypatch.setattr(fc.shutil, 'which', lambda name: 'synthetic-gh' if name == 'gh' else real_which(name))
    assert isinstance(fc.main(['--code-root', str(code), '--skills-dir', str(skills), '--visibility', str(visibility), '--no-status']), int)
    assert any('/contents/.github/workflows/custom.yml?' in args[2] for args in requests if args[1] == 'api')
    assert 'remote actions:' in capsys.readouterr().out


def test_static_g8_keeps_all_elements_without_accepting(tmp_path, capsys):
    repo = config_lifecycle(tmp_path/'acme-config-tool')
    assert config.main(str(repo), True) != 0
    output = capsys.readouterr().out
    assert 'E4' in output and 'E5' in output and '6/8' in output
    assert 'ACCEPT' not in output and 'static_not_executed' in output


def test_empty_successful_initializer_is_not_a_template(tmp_path, monkeypatch, capsys):
    repo = config_lifecycle(tmp_path/'acme-config-tool')
    monkeypatch.setattr(config, 'run', lambda *args, **kwargs: subprocess.CompletedProcess([], 0, '', ''))
    assert config.main(str(repo), False) == 1
    assert '[FAIL] E4' in capsys.readouterr().out


def test_blank_template_requires_configuration_then_both_swap_legs_work(tmp_path, capsys):
    repo = config_lifecycle(tmp_path/'acme-config-tool')
    assert config.main(str(repo), False) != 0
    output = capsys.readouterr().out
    assert 'configuration_required' in output and 'not configurable' not in output
    configs = []
    for leg in ('alpha', 'bravo'):
        destination = tmp_path/leg/'companion'
        source = tmp_path/leg/'source'
        source.mkdir(parents=True)
        (source/'source.txt').write_text(leg, encoding='utf-8')
        init = subprocess.run([sys.executable, str(repo/'scripts/init_config.py'), '--out', str(destination)], capture_output=True, timeout=30)
        assert init.returncode == 0
        env = dict(os.environ, ACME_CONFIG_TOOL_CONFIG=str(destination))
        blank = subprocess.run([sys.executable, str(repo/'scripts/verify_config.py')], env=env, capture_output=True, timeout=30)
        assert blank.returncode != 0 and b'NOT READY' in blank.stdout
        write_json(destination/'registry.json', {'schema_version': 1, 'required_root': str(source)})
        for script in ('verify_config.py', 'exercise.py'):
            configured = subprocess.run([sys.executable, str(repo/'scripts'/script)], env=env, capture_output=True, timeout=30)
            assert configured.returncode == 0
            if script == 'exercise.py': assert configured.stdout.strip().decode() == leg
        configs.append(str(destination))
    assert config.main(str(repo), False, config_a=configs[0], config_b=configs[1]) == 0
    assert '8/8 elements pass' in capsys.readouterr().out
