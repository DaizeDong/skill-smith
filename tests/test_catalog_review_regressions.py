"""Counterexamples from the independent catalog review, using generated inputs."""
import copy
import json
from pathlib import Path

import budget_check
import dedup_check
import fleet_check
import pytest
from skill_smith.catalog import discover
from tools.make_fixtures import plugins, skill, write_json


def test_plugin_enablement_is_scoped_to_the_supplied_effective_settings(tmp_path):
    request = plugins(tmp_path)
    descriptor = request['plugin_registries'][0]
    path = Path(descriptor['path'])
    registry = json.loads(path.read_text())
    project = copy.deepcopy(registry['plugins']['demo@market-a'][0])
    project.update(scope='project', projectPath=str(tmp_path / 'project'))
    registry['plugins']['demo@market-a'].append(project)
    write_json(path, registry)
    snapshot = discover(request)
    projected = next(row for row in snapshot['records'] if row.get('scope') == 'project')
    assert projected['status']['enabled'] == 'unknown'
    project_descriptor = dict(descriptor, scope='project', scope_path=project['projectPath'])
    project_descriptor['settings_path'] = write_json(tmp_path / 'project-settings.json', {
        'enabledPlugins': {'demo@market-a': True}})
    request['plugin_registries'].append(project_descriptor)
    snapshot = discover(request)
    rows = [r for r in snapshot['records'] if r['registry_key'] == 'demo@market-a']
    assert len(rows) == 2
    assert {r['scope']: r['status']['enabled'] for r in rows} == {'user': 'no', 'project': 'yes'}


def test_plugin_directory_aliases_keep_separate_budget_and_dedup_rows(tmp_path):
    request = plugins(tmp_path)
    root = tmp_path / 'cache/market-b/2/skills'
    skill(root / 'alpha', 'shared')
    skill(root / 'beta', 'shared')
    snapshot = discover(request)
    plugin = next(r for r in snapshot['records'] if r['registry_key'] == 'demo@market-b')
    assert {e['install_name'] for e in plugin['entrypoints']} == {'demo', 'alpha', 'beta'}
    assert {e['relative_path'] for e in plugin['entrypoints']} == {
        'skills/demo/SKILL.md', 'skills/alpha/SKILL.md', 'skills/beta/SKILL.md'}
    assert len(budget_check.rows_from_catalog(snapshot, None)[0]) == 3
    assert len(dedup_check.items_from_catalog(snapshot)) == 3


def test_depth_two_includes_a_child_of_an_existing_skill(tmp_path):
    root = tmp_path / 'skills'
    skill(root / 'group', 'parent')
    skill(root / 'group/child', 'child')
    snapshot = discover({'skill_roots': [{'path': str(root), 'max_depth': 2}]})
    assert {e['name'] for r in snapshot['records'] for e in r['entrypoints']} == {'parent', 'child'}


def test_runtime_can_identify_one_of_two_equal_frontmatter_names(tmp_path):
    request = plugins(tmp_path)
    root = tmp_path / 'cache/market-b/2/skills'
    skill(root / 'alpha', 'shared')
    skill(root / 'beta', 'shared')
    snapshot = discover(request)
    record = next(r for r in snapshot['records'] if r['registry_key'] == 'demo@market-b')
    request['runtime_discovery'] = write_json(tmp_path / 'runtime.json', {'entrypoints': [{
        'source_id': record['source_id'], 'kind': 'skill', 'name': 'shared',
        'client': 'claude', 'scope': 'user', 'relative_path': 'skills/alpha/SKILL.md',
        'discovered': 'yes', 'compatible': 'yes',
    }]})
    result = discover(request)
    record = next(r for r in result['records'] if r['registry_key'] == 'demo@market-b')
    states = {e['install_name']: e['status']['discovered'] for e in record['entrypoints']}
    assert states == {'demo': 'unknown', 'alpha': 'yes', 'beta': 'unknown'}


def test_structured_binding_identifier_is_not_serialized(tmp_path):
    value = {'env': {'TOKEN': 'SYNTHETIC_CANARY_VALUE'}}
    request = {'private_bindings': write_json(tmp_path / 'bindings.json', {'bindings': [
        {'id': 'demo', 'kind': 'mcp_binding', 'server': value},
        {'id': 'mail', 'kind': 'app_connector', 'connector': value},
    ]})}
    snapshot = discover(request)
    assert snapshot['coverage']['private_bindings']['status'] == 'partial'
    assert snapshot['records'] == []
    assert 'SYNTHETIC_CANARY_VALUE' not in json.dumps(snapshot)


@pytest.mark.parametrize('field', ['scope', 'projectPath', 'version', 'gitCommitSha'])
def test_structured_plugin_metadata_is_partial_and_does_not_escape(tmp_path, field):
    request = plugins(tmp_path)
    path = Path(request['plugin_registries'][0]['path'])
    data = json.loads(path.read_text())
    data['plugins']['demo@market-a'][0][field] = {'TOKEN': 'SYNTHETIC_CANARY_VALUE'}
    write_json(path, data)
    snapshot = discover(request)
    assert snapshot['coverage']['plugin_registries']['status'] == 'partial'
    assert 'SYNTHETIC_CANARY_VALUE' not in json.dumps(snapshot)


def test_fleet_main_keeps_repository_discovery_unknown_in_human_and_json(tmp_path, capsys):
    out = tmp_path / 'status.json'
    missing = str(tmp_path / 'missing')
    fleet_check.main(['--code-root', missing, '--skills-dir', missing,
                      '--installed-plugins', str(tmp_path / 'no-plugins.json'),
                      '--visibility', str(tmp_path / 'no-visibility.json'),
                      '--offline', '--status-json', str(out)])
    human = capsys.readouterr().out
    report = json.loads(out.read_text())
    assert any('repository discovery' in row for row in report['unobserved'])
    assert 'repository discovery' in human
