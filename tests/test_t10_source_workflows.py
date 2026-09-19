"""Source recipe tests use only generated fixtures and synthetic revision pins."""
import pytest

from tools.make_fixtures import text_file
from test_runtime_overlays import source, caps
from skill_smith import overlays, source_workflows, conflicts


def reviewed(tmp_path, monkeypatch, name='research-review'):
    body = ('# Synthetic review\n\n## Constants\n- REVIEWER_BACKEND = oracle-pro\n'
        '## Workflow\n```yaml\nspawn_agent:\n  message: |\n    Full initial context\n    Request score and evidence\n```\n'
        '```yaml\nsend_input:\n  target: saved\n  message: Full revised materials\n```\n')
    if name == 'auto-review-loop':
        body += '```yaml\nsend_input:\n  target: saved\n  message: Debate and re-score\n```\n'
        body += '## Output Protocols\nRead [protocol](../../references/output.md).\n'
        text_file(tmp_path / 'references/output.md', 'Synthetic output protocol')
    else:
        body += '## Prompt Templates\nGive a results-to-claims matrix.\n'
    record = source(tmp_path, body, name=name)
    monkeypatch.setitem(source_workflows.REVIEWED, name, record['entrypoints'][0]['source_hash'])
    return record


@pytest.mark.parametrize('name', ['research-review', 'auto-review-loop'])
def test_reviewed_source_routes_use_inherited_llmcall_and_keep_prompts(tmp_path, monkeypatch, name):
    record = reviewed(tmp_path, monkeypatch, name)
    descriptor = overlays.build(record, 'codex', caps('llmcall.contexts', 'llmcall.independent_review'))
    assert descriptor['status'] == 'ready', descriptor
    assert 'oracle-pro' not in descriptor['template']
    assert 'spawn_agent' not in descriptor['template']
    assert 'gpt-' not in descriptor['template']
    assert descriptor['steps'][0]['prompt'] == 'Full initial context\nRequest score and evidence'
    assert descriptor['steps'][1]['prompt'] == 'Full revised materials'
    assert overlays.validate(descriptor)
    if name == 'auto-review-loop':
        for expected in ('MAX_ROUNDS=4', 'REVIEWER_MEMORY.md', 'HUMAN_CHECKPOINT', 'CLAIMS_FROM_RESULTS.md', 'Method Description', 'not ready'):
            assert expected in descriptor['template']
        assert descriptor['resources'][0]['relative_path'] == 'references/output.md'


def test_unreviewed_revision_cannot_use_source_recipe(tmp_path):
    record = source(tmp_path, 'Use oracle-pro review.', name='research-review')
    result = overlays.build(record, 'codex', caps('llmcall.contexts'))
    assert result['status'] == 'unsupported'


@pytest.mark.parametrize('args', [
    ['exec', '--full-auto'], ['exec', '--sandbox', 'danger-full-access'],
    ['exec', '--ask-for-approval', 'never'], ['exec', '-a', 'on-request'],
    ['exec', 'resume', 'native-session-id'], ['resume', '--last'],
    ['exec', '--config', 'other=true'],
])
def test_non_equivalent_flags_and_native_ids_are_not_dropped(args):
    with pytest.raises(ValueError):
        source_workflows.cli_request(args)


def test_cli_preserves_explicit_model_effort_workspace_and_sandbox():
    result = source_workflows.cli_request(['codex', 'exec', '--skip-git-repo-check',
        '-m', 'user-model', '-c', 'model_reasoning_effort="high"',
        '-C', '/synthetic/work', '--sandbox', 'workspace-write'])
    assert result['exact_model'] == 'user-model'
    assert result['effort'] == 'high' and result['cwd'] == '/synthetic/work'
    assert result['requirements'] == {'access': 'workspace_write', 'replay': 'never_after_start'}
    assert result['repo_check'] == 'not_required_by_caller'
    resumed = source_workflows.cli_request(['exec', '--skip-git-repo-check', 'resume', '--last'])
    assert resumed['resume'] and resumed['requirements'] is None


def test_missing_selection_inputs_are_explicit():
    assert conflicts.select({}, {}, None, {})['reason'] == 'runtime_policy_missing'
    assert conflicts.select({}, None, {'schema_version': 1}, {})['reason'] == 'capability_snapshot_missing'


def test_source_specific_resource_examples_keep_script_arguments(tmp_path, monkeypatch):
    record = source(tmp_path, 'Use `scripts/thumbnail.py deck.pptx [prefix]`.\n', name='pptx',
                    metadata='license: Proprietary. LICENSE.txt has complete terms\n')
    text_file(tmp_path / 'skills/pptx/scripts/thumbnail.py', '# Synthetic script')
    text_file(tmp_path / 'skills/pptx/LICENSE.txt', 'Synthetic license')
    monkeypatch.setitem(source_workflows.RESOURCE_REVISIONS, 'pptx', record['entrypoints'][0]['source_hash'])
    built = overlays.build(record, 'codex', caps('llmcall.contexts'))
    assert built['status'] == 'ready'
    assert 'scripts/thumbnail.py deck.pptx [prefix]' in built['template']
    assert {item['relative_path'] for item in built['resources']} == {'skills/pptx', 'skills/pptx/scripts/thumbnail.py', 'skills/pptx/LICENSE.txt'}
    assert overlays.validate(built)
