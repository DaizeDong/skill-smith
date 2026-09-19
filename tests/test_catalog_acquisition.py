"""Acquisition regressions using generated synthetic source inputs."""
from datetime import datetime, timezone

import pytest

from skill_smith.catalog import discover
from tools.make_fixtures import plugins, skill, write_json


def test_descriptors_alone_do_not_claim_registry_coverage(tmp_path):
    skill(tmp_path / 'plugin/skills/demo')
    result = discover({'plugin_descriptors': [{'name': 'demo@example', 'path': str(tmp_path / 'plugin')}]})
    assert result['coverage']['plugin_registries']['status'] == 'unchecked'
    assert result['coverage']['plugin_descriptors']['status'] == 'checked'
    record, = result['records']
    assert record['registry_key'] == 'demo@example'
    assert record['entrypoints']
    assert record['registry_path'] is None
    assert record['status']['enabled'] == 'unknown'


def test_conflicting_explicit_paths_are_partial_without_registry(tmp_path):
    for folder in ('first', 'second'):
        skill(tmp_path / folder / 'skills/demo')
    result = discover({'plugin_descriptors': [
        {'name': 'demo@example', 'path': str(tmp_path / folder)} for folder in ('first', 'second')]})
    assert result['coverage']['plugin_registries']['status'] == 'unchecked'
    assert result['coverage']['plugin_descriptors']['status'] == 'partial'
    assert result['records'][0]['entrypoints'] == []


def test_bare_explicit_identity_stays_ambiguous_without_registry(tmp_path):
    result = discover({'plugin_descriptors': [{'name': 'demo', 'path': str(tmp_path)}]})
    assert result['records'] == []
    assert result['coverage']['plugin_descriptors']['status'] == 'partial'


def supplied_request(tmp_path, timestamp):
    skill(tmp_path / 'skills/demo')
    request = {'skill_roots': [{'path': str(tmp_path / 'skills'), 'client': 'codex'}]}
    ep = discover(request)['records'][0]['entrypoints'][0]
    item = {key: ep[key] for key in ('source_id', 'kind', 'name', 'client', 'scope', 'relative_path', 'install_name')}
    item.update(discovered='yes', compatible='yes', observed_at=timestamp)
    request['runtime_discovery'] = write_json(tmp_path / 'runtime.json', {'entrypoints': [item]})
    request['runtime_discovery_policy'] = {'max_age_seconds': 60}
    return request


@pytest.mark.parametrize('timestamp, expected', [
    ('2026-01-01T00:00:00Z', 'yes'),
    ('2025-12-31T23:59:59Z', 'unknown'),
    ('2026-01-01T00:02:00Z', 'unknown'),
    ('invalid', 'unknown'), (None, 'unknown'),
])
def test_runtime_freshness_preserves_capture_time(tmp_path, timestamp, expected):
    request = supplied_request(tmp_path, timestamp)
    result = discover(request, now=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc))
    ep = result['records'][0]['entrypoints'][0]
    assert ep['status']['discovered'] == expected
    assert ep['status']['compatible'] == expected
    assert ep['evidence']['discovered']['observed_at'] == timestamp
    assert result['coverage']['runtime_discovery']['status'] == ('checked' if expected == 'yes' else 'partial')


def test_envelope_refresh_cannot_refresh_old_native_evidence(tmp_path):
    request = supplied_request(tmp_path, '2026-01-01T00:00:00Z')
    for minute in (2, 3):
        result = discover(request, now=f'2026-01-01T00:0{minute}:00Z')
        ep = result['records'][0]['entrypoints'][0]
        assert ep['status']['discovered'] == 'unknown'
        assert ep['evidence']['discovered']['observed_at'] == '2026-01-01T00:00:00Z'


def test_explicit_path_disagreement_cannot_claim_checked_selection(tmp_path):
    request = plugins(tmp_path)
    request['plugin_descriptors'] = [{'name': 'demo@market-b', 'path': str(tmp_path / 'wrong')}]
    result = discover(request)
    assert result['coverage']['plugin_descriptors']['status'] == 'partial'
    record = next(r for r in result['records'] if r['registry_key'] == 'demo@market-b')
    assert not record.get('explicit_selection', False)


@pytest.mark.parametrize('policy', [{}, {'max_age_seconds': True}, {'max_age_seconds': -1},
    {'max_age_seconds': 1, 'extra': 2}, [], {'max_age_seconds': '60'}])
def test_invalid_freshness_policy_cannot_accept_runtime_evidence(tmp_path, policy):
    request = supplied_request(tmp_path, '2026-01-01T00:00:00Z')
    request['runtime_discovery_policy'] = policy
    result = discover(request)
    assert result['coverage']['runtime_discovery']['status'] == 'partial'
    assert result['records'][0]['entrypoints'][0]['status']['discovered'] == 'unknown'
