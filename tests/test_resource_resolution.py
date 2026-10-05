"""Resource manifests from generated synthetic templates; no script execution."""
from copy import deepcopy
from pathlib import Path

import pytest

from skill_smith import overlays, source_workflows
from test_runtime_overlays import caps, source
from tools.make_fixtures import directory_link, text_file


@pytest.mark.parametrize('command,script', [
    ('scripts/check.sh agents/[identifier].md --strict', 'scripts/check.sh'),
    ('"scripts/check file.sh" "agents/[identifier].md"', 'scripts/check file.sh'),
    ("'scripts/check file.py' 'agents/[identifier].md'", 'scripts/check file.py'),
    ('python "scripts/check file.py" agents/[identifier].md', 'scripts/check file.py'),
    ('bash scripts/check.sh agents/[identifier].md', 'scripts/check.sh'),
])
def test_command_pins_executable_separately_from_placeholder_argument(tmp_path, command, script):
    body = 'Output: `agents/[identifier].md`. Validate with: `' + command + '`.'
    record = source(tmp_path, body)
    text_file(tmp_path / 'skills/demo' / script, '# Synthetic inert script\n')
    built = overlays.build(record, 'codex', caps('llmcall.contexts'))
    assert built['status'] == 'ready', built
    assert built['template'] == body
    assert [r['relative_path'] for r in built['resources']] == ['skills/demo/' + script]
    assert built['resources'][0]['reference'] == script
    assert overlays.validate(built)


def test_command_static_assets_are_pinned_even_in_options(tmp_path):
    record = source(tmp_path, 'Run `scripts/check.sh agents/[identifier].md '
                    '--schema="references/input schema.json" assets/sample.json`.')
    for relative in ('scripts/check.sh', 'references/input schema.json', 'assets/sample.json'):
        text_file(tmp_path / 'skills/demo' / relative, 'Synthetic input\n')
    built = overlays.build(record, 'codex', caps('llmcall.contexts'))
    assert built['status'] == 'ready', built
    assert {r['relative_path'] for r in built['resources']} == {
        'skills/demo/scripts/check.sh', 'skills/demo/references/input schema.json',
        'skills/demo/assets/sample.json'}
    text_file(tmp_path / 'skills/demo/references/input schema.json', 'Changed input\n')
    assert not overlays.validate(built)


@pytest.mark.parametrize('body', [
    'Read `"references/a guide.md"`.',
    "Read `'references/a guide.md'`.",
    'Read [guide](<references/a guide.md> "Guide title").',
    'Read [guide][ref].\n[ref]: <references/a guide.md> "Guide title"\n',
])
def test_quoted_static_paths_with_spaces_are_not_commands(tmp_path, body):
    record = source(tmp_path, body)
    text_file(tmp_path / 'skills/demo/references/a guide.md', 'Synthetic guide')
    built = overlays.build(record, 'codex', caps('llmcall.contexts'))
    assert built['status'] == 'ready', built
    assert [r['relative_path'] for r in built['resources']] == ['skills/demo/references/a guide.md']
    assert overlays.validate(built)


@pytest.mark.parametrize('body,reason', [
    ('Run `scripts/missing.sh agents/[identifier].md`.', 'resource_missing:scripts/missing.sh'),
    ('Run `scripts/check.sh --schema=references/missing.json`.', 'resource_missing:references/missing.json'),
    ('Read [missing](references/missing.md).', 'resource_missing:references/missing.md'),
    ('Read `references/[identifier].md`.', 'unresolved_resource_reference'),
    ('Read [output](agents/[identifier].md).', 'unresolved_resource_reference'),
    ('Read `references/a guide.md`.', 'ambiguous_resource_reference'),
    ('Run `scripts/check.sh && scripts/other.sh`.', 'unsupported_resource_command'),
    ('Run `scripts/check.sh > agents/output.md`.', 'unsupported_resource_command'),
    ('Run `scripts/check.sh $(touch CANARY)`.', 'unsupported_resource_command'),
    ('Run `scripts/check.sh --input=$INPUT`.', 'unsupported_resource_command'),
    ('Run `scripts/check.sh references/*.json`.', 'unresolved_resource_reference'),
    ('Run `"scripts/check.sh`.', 'unsupported_resource_command'),
    ('Run `scripts/check.sh --schema=../../../escape.json`.', 'resource_outside_source_root'),
])
def test_missing_ambiguous_dynamic_and_escaping_references_fail_closed(tmp_path, body, reason):
    record = source(tmp_path, body)
    text_file(tmp_path / 'skills/demo/scripts/check.sh', '# Synthetic inert script')
    built = overlays.build(record, 'codex', caps('llmcall.contexts'))
    assert built['status'] == 'unsupported', built
    assert built['reasons'] == [reason]
    assert 'template' not in built
    assert not (tmp_path / 'CANARY').exists()


def bound_role(tmp_path, monkeypatch):
    body = ('## Synthetic creation instructions\nCreate `agents/[identifier].md`.\n'
            '```markdown\n### File Created\n`agents/[identifier].md`\n'
            'Validate with: `scripts/validate-agent.sh agents/[identifier].md`\n```\n')
    record = source(tmp_path, body, kind='agent_template', name='agent-creator',
                    metadata='tools: ["Read", "Write"]\n')
    ep = record['entrypoints'][0]
    path = tmp_path / 'agents/agent-creator.md'
    text_file(path, Path(ep['resolved_path']).read_text(encoding='utf-8'))
    ep.update(relative_path='agents/agent-creator.md', resolved_path=str(path))
    helper = tmp_path / 'skills/agent-development/scripts/validate-agent.sh'
    text_file(helper, '# Synthetic inert helper; never execute.\n')
    # Preserve the production binding shape, but authorize only generated bytes.
    binding = deepcopy(source_workflows.RESOURCE_BINDINGS['agent-creator'])
    binding['source_hash'] = ep['source_hash']
    binding['references']['scripts/validate-agent.sh']['hash'] = overlays.digest(helper.read_bytes())
    monkeypatch.setitem(source_workflows.RESOURCE_BINDINGS, 'agent-creator', binding)
    return record, helper


def test_reviewed_template_resolves_exact_sibling_helper_without_search(tmp_path, monkeypatch):
    record, helper = bound_role(tmp_path, monkeypatch)
    for relative in ('scripts/validate-agent.sh', 'agents/scripts/validate-agent.sh',
                     'skills/other/scripts/validate-agent.sh'):
        text_file(tmp_path / relative, '# Decoy helper, never select\n')
    built = overlays.build(record, 'codex', caps('llmcall.agent', 'llmcall.permissions'))
    assert built['status'] == 'ready', built
    assert len(built['resources']) == 1
    resource = built['resources'][0]
    assert resource['relative_path'] == 'skills/agent-development/scripts/validate-agent.sh'
    assert Path(resource['resolved_path']) == helper
    assert resource['binding']['hash'] == overlays.digest(helper.read_bytes())
    assert overlays.validate(built)
    text_file(helper, '# Changed helper\n')
    assert not overlays.validate(built)
    assert overlays.build(record, 'codex', caps('llmcall.agent', 'llmcall.permissions'))['reasons'] == ['resource_binding_drift']


@pytest.mark.parametrize('change', ['source_hash', 'kind', 'relative_path', 'name'])
def test_sibling_binding_requires_exact_reviewed_entrypoint(tmp_path, monkeypatch, change):
    record, _ = bound_role(tmp_path, monkeypatch)
    ep = record['entrypoints'][0]
    if change == 'source_hash':
        path = Path(ep['resolved_path'])
        text_file(path, path.read_text(encoding='utf-8') + '\nUnreviewed revision.\n')
        ep['source_hash'] = overlays.digest(path.read_bytes())
    else:
        ep[change] = {'kind': 'skill', 'relative_path': 'other/agent-creator.md',
                      'name': 'other-role'}[change]
    built = overlays.build(record, 'codex', caps('llmcall.agent', 'llmcall.contexts', 'llmcall.permissions'))
    assert built['reasons'] == ['resource_missing:scripts/validate-agent.sh']


def test_explicit_root_remains_boundary_and_never_resource_search_path(tmp_path, monkeypatch):
    record, helper = bound_role(tmp_path / 'plugin', monkeypatch)
    built = overlays.build(record, 'codex', caps('llmcall.agent', 'llmcall.permissions'), resource_root=tmp_path)
    assert built['status'] == 'ready', built
    assert built['resources'][0]['relative_path'] == 'plugin/skills/agent-development/scripts/validate-agent.sh'
    assert overlays.validate(built)
    rejected = overlays.build(record, 'codex', caps('llmcall.agent', 'llmcall.permissions'), resource_root=helper.parent.parent)
    assert rejected['reasons'] == ['source_outside_explicit_resource_root']
    helper.unlink()
    text_file(tmp_path / 'plugin/skills/other/scripts/validate-agent.sh', '# Decoy\n')
    assert overlays.build(record, 'codex', caps('llmcall.agent', 'llmcall.permissions'))['reasons'] == ['resource_missing:scripts/validate-agent.sh']


def test_resource_links_cannot_escape_even_with_matching_bound_bytes(tmp_path, monkeypatch):
    root = tmp_path / 'plugin'
    record, helper = bound_role(root, monkeypatch)
    outside = tmp_path / 'outside'
    text_file(outside / helper.name, helper.read_text(encoding='utf-8'))
    helper.unlink()
    helper.parent.rmdir()
    directory_link(helper.parent, outside)
    built = overlays.build(record, 'codex', caps('llmcall.agent', 'llmcall.permissions'))
    assert built['reasons'] == ['resource_outside_source_root']


def test_explicit_directory_resource_rejects_escaping_child_link(tmp_path):
    root = tmp_path / 'plugin'
    record = source(root, 'Read `assets`.\nRead `${CLAUDE_PLUGIN_ROOT}/assets/`.')
    text_file(tmp_path / 'outside/guide.md', 'Synthetic outside resource')
    directory_link(root / 'assets/linked', tmp_path / 'outside')
    built = overlays.build(record, 'codex', caps('llmcall.contexts'))
    assert built['reasons'] == ['resource_link_escape']


def test_binding_does_not_supply_missing_permission_evidence(tmp_path, monkeypatch):
    record, _ = bound_role(tmp_path, monkeypatch)
    built = overlays.build(record, 'codex', caps('llmcall.agent'))
    assert built['status'] == 'blocked'
    assert built['reasons'] == ['capability:llmcall.permissions']
    assert built['requirements']['required_tools'] == ['Read', 'Write']


@pytest.mark.parametrize('reviewed', [False, True])
def test_output_link_exception_still_requires_exact_source_pin(tmp_path, monkeypatch, reviewed):
    record = source(tmp_path, 'Return [output](/absolute/path/to/model.xlsx).', name='Excel')
    if reviewed:
        monkeypatch.setitem(source_workflows.RESOURCE_REVISIONS, 'Excel', record['entrypoints'][0]['source_hash'])
    built = overlays.build(record, 'codex', caps('llmcall.contexts'))
    assert built['status'] == ('ready' if reviewed else 'unsupported')
    if reviewed:
        assert built['resources'] == []
    else:
        assert built['reasons'] == ['resource_outside_source_root']


def test_internal_resource_link_is_pinned_and_retargeting_invalidates(tmp_path):
    record = source(tmp_path, 'Read `references/linked/guide.md`.')
    text_file(tmp_path / 'first/guide.md', 'Synthetic first guide')
    text_file(tmp_path / 'second/guide.md', 'Synthetic second guide')
    link = tmp_path / 'skills/demo/references/linked'
    directory_link(link, tmp_path / 'first')
    built = overlays.build(record, 'codex', caps('llmcall.contexts'))
    assert built['status'] == 'ready', built
    assert overlays.validate(built)
    # Remove only the test link, leaving its target intact on either platform.
    if link.is_symlink():
        link.unlink()
    else:
        link.rmdir()
    directory_link(link, tmp_path / 'second')
    assert not overlays.validate(built)


def test_ambiguous_inline_path_is_not_disambiguated_by_existing_files(tmp_path):
    record = source(tmp_path, 'Read `references/a guide.md`.')
    text_file(tmp_path / 'skills/demo/references/a', 'Synthetic first candidate')
    text_file(tmp_path / 'skills/demo/references/a guide.md', 'Synthetic second candidate')
    built = overlays.build(record, 'codex', caps('llmcall.contexts'))
    assert built['reasons'] == ['ambiguous_resource_reference']
