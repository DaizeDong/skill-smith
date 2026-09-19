"""Reviewed, exact-source compatibility recipes; never edit upstream bytes.

The ARIS converters' useful structure is retained: isolate metadata, extract
fenced calls, preserve prompt blocks and resource-relative paths. Their global
substitutions and parameter deletion are deliberately not conversion authority.
Only the reviewed source revisions below authorize these semantic recipes.
"""
from copy import deepcopy
import re


REVIEWED = {
    'research-review': 'sha256:c9bee081de76ff4985f49aa33478323cb87771c118116e845ffbc7eaf19e5e11',
    'auto-review-loop': 'sha256:757efdc8029ab794a269eeb178b102e152feec04e929846043595ac80001fa21',
    'codex': 'sha256:6a832536cc8a130046ecb5f902785e28b32cad50091b0fc751f1f343cced2950',
}

RESOURCE_REVISIONS = {
    'Excel': 'sha256:1fe73706761665673b5451e55597c7788a2c82bcadcc797cda3114df5a56dea0',
    'xlsx': 'sha256:6712b39718fe815054abca9c3ee72f989613e6f771c8a5c58f30a65a6c905622',
    'pptx': 'sha256:66c1b7e8f8a6da04f1cb813f5948d61a041a32b41d7aee6fdac337785dc9ec2f',
}


RESOURCE_BINDINGS = {
    'agent-creator': {
        'kind': 'agent_template',
        'relative_path': 'agents/agent-creator.md',
        'source_hash': 'sha256:99ca808b7577e5c4b816cd7e621a1dea4b0ba9104ba24629cd713170cfe9dbd3',
        'references': {
            'scripts/validate-agent.sh': {
                'path': '${CLAUDE_PLUGIN_ROOT}/skills/agent-development/scripts/validate-agent.sh',
                'hash': 'sha256:d22e1292f997169fb745793dc50ebe3e9c6631603e1d77f04c2e79bb1fc63cba',
            },
        },
    },
}


def resource_binding(entry, reference):
    """Bind one reviewed token to one pinned helper in the same source tree."""
    binding = RESOURCE_BINDINGS.get(entry.get('name'))
    if binding and all(entry.get(key) == binding[key]
                       for key in ('kind', 'relative_path', 'source_hash')):
        return binding['references'].get(reference)
    return None


def resource_reference(entry, reference):
    """Classify only reviewed source examples, without changing their text."""
    name = entry.get('name')
    if entry.get('source_hash') != RESOURCE_REVISIONS.get(name):
        return reference
    if name == 'Excel' and reference == '/absolute/path/to/model.xlsx':
        return None  # Explicit output-link placeholder, not a shipped resource.
    return reference


def resource_template(entry, relative, digest):
    if (entry.get('name') in {'research-review', 'auto-review-loop'}
        and entry.get('source_hash') == REVIEWED[entry['name']]
        and relative.endswith('shared-references/review-tracing.md')):
        if digest != 'sha256:5f017ff5e4b30a568a064db0a7cf05e6d99f5ab25fb8b6adcc8db8cac9feac97':
            raise ValueError('review_tracing_revision_unsupported')
        return '''# llmcall Review Tracing Protocol

Trace each critique, scoring, claim verification, experiment audit, patch gate,
debate and adversarial review through the same llmcall workflow context. Record
the full prompt and verbatim raw response, purpose, current files, call number,
workflow/context/request IDs, timestamps, actual provider-reported model/family,
effort, elapsed time, execution_started, effects, outcome and decisions.
The caller's private SYNC workflow history owns immutable request/result records
and uncertain outcomes. No native agent/session handle is a resume credential.

Optional project exports retain .aris/traces/<skill-name>/<date>_run<NN>/ with
run.meta.json, NNN-<purpose>.request.json, NNN-<purpose>.response.md and
NNN-<purpose>.meta.json. Append a compact review_trace event with purpose,
workflow/context ID, trace path and status to .aris/meta/events.json when those
project writes are authorized. Use full prompt/response exports by default;
trace: meta exports metadata only and trace: off disables optional exports.
Private replay protection remains required; if its storage is disallowed, stop
with an explicit unsupported persistence policy. Keep project exports private.
'''
    return None


def section(body, heading):
    """Extract a Markdown section, ignoring headings inside fenced examples."""
    lines, selected, level, fence = [], False, 0, None
    for line in body.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith(('```', '~~~')):
            token = stripped[:3]
            fence = None if fence == token else token if fence is None else fence
        match = re.match(r'^(#{1,6}) (.+?)\s*$', line) if fence is None else None
        if match:
            if selected and len(match[1]) <= level:
                break
            if match[2] == heading:
                selected, level = True, len(match[1])
        if selected:
            lines.append(line)
    if not selected:
        raise ValueError('reviewed_source_section_missing:' + heading)
    return ''.join(lines)


COMMON = '''# Review through llmcall

Use the installed profile_bridge.workflows.DurableWorkflow entrypoint. Every
model decision uses llmcall judge mode; delegated implementation or repository
inspection uses llmcall agent mode. All nested work uses this same interface.
Inherit current routing, model, effort, timeout, cancellation and permissions.
An explicit user model is exact, and an explicit user effort overrides inherited
effort. Source model/backend constants are obsolete provenance, never defaults.
The former alternate reviewer route uses these same llmcall review semantics;
there is no separate provider ladder. A requested model unavailable to llmcall
is an explicit failure, not permission to substitute another model.

Supply complete current file contents, claims, results, evidence and questions,
plus the actual producer Result. Independent review requires provider-reported
producer/reviewer families and llmcall avoid enforcement. Unknown identity cannot
be called an independent review. Use caller-owned workflow/context/request IDs;
each continuation includes the complete prior transcript and current inputs.
Native session IDs are not accepted. Persist full immutable request/result and
execution/effects evidence in private SYNC state before returning to the caller.
Interrupted requests remain uncertain and must not be automatically rerun.
Poll only reads a completed result. Keep raw responses verbatim for all rounds.
Project output/notification/experiment actions remain with the authorized caller;
the adapter does not execute them as a side effect of a review call.
'''

RESEARCH = '''
Gather project narrative, paper drafts, notes, experiment history, methodology,
core claims, key results and known weaknesses. Run the initial senior ML review,
then continue in the same explicit context with revised materials and rebuttals.
Ask for logical gaps, missing experiments, narrative weaknesses and contribution
strength. Each round responds with evidence, targeted followups and concrete
experiment designs, outlines or results-to-claims matrices. Continue until claims
and evidence requirements, an experiment plan and narrative structure converge.
Save a self-contained review document: every round's criticisms and responses,
final consensus, claims matrix, prioritized TODOs with compute costs, and any
paper outline. Update only caller-authorized project notes. Record context ID,
actual reviewer identity, prompt, raw result, decisions and action items.
'''

LOOP = '''
Default MAX_ROUNDS=4. Preserve user overrides, HUMAN_CHECKPOINT and COMPACT.
Initialization reads review-stage/REVIEW_STATE.json and AUTO_REVIEW.md (legacy
project paths may be read), current narrative, results and open TODOs. COMPACT
may prefer findings.md and EXPERIMENT_LOG.md. Private immutable SYNC request/result
history is replay authority. Never delete stale state to authorize a replay.
A completed workflow needs an explicitly new workflow ID for a new run.

Phase A reviews full current context and changes since the last round. Medium
uses judge review. Hard also supplies the entire REVIEWER_MEMORY.md and requires
a verbatim Memory update. Nightmare adds a fresh independent repository reviewer
in a separate context using agent mode with enforced read_only requirements;
it checks actual code, logs, result files and drafts, not executor summaries.
If that hard capability is unavailable, nightmare is explicitly unsupported.
Phase B saves the complete raw response then extracts score 1-10, verdict and
ranked minimum fixes. Stop only for score >= 6 AND an explicit ready/almost
verdict, never by matching 'ready' inside 'not ready'. Hard/nightmare append
reviewer memory before project state, and debate up to three high-impact
weaknesses with evidence. Continue that reviewer context for its ruling; only
mark a concern resolved when the reviewer accepts the rebuttal.

If HUMAN_CHECKPOINT is enabled, wait for go/custom/skip/stop before Phase C.
Phase C implements authorized fixes in priority order; record excessive compute
or unavailable data/model work as deferred. Delegation uses llmcall agent mode
with required permissions. Phase D monitors launched experiments and records
training-health evidence or its unavailability. Phase E appends assessment,
verbatim raw response, debate, actions, results and continuation status to
review-stage/AUTO_REVIEW.md, updates REVIEW_STATE.json, and appends compact
findings when selected. Each new review round includes actual implemented fixes
and their measured results. Caller time budget and cancellation apply throughout.

Termination sets completed state, saves a final summary and Method Description,
updates authorized project notes, and requests result-to-claim output
CLAIMS_FROM_RESULTS.md when available. Otherwise report that missing capability.
At the round limit list remaining blockers, effort and continue/pivot options.
Configured notifications and training tools remain explicit caller capabilities;
the adapter neither sends notifications nor silently claims these outputs exist.
Trace every review/debate/adversarial call with immutable raw request/result,
identity, score/verdict, fixes, rulings, context ID and memory update. Project
trace off/meta controls optional exports, not the private replay safety record.
'''

CODEX = '''# Codex workflow compatibility through llmcall

Use profile_bridge.workflows.DurableWorkflow.run_cli with a parsed argv list,
the prompt, explicit caller workflow ID and unique request ID. No shell command
or provider CLI is executed. A followup is a fresh llmcall agent call with full
explicit local context; it is not native provider session resumption. Report this
compatibility mode to the user. An existing native session ID is unsupported.
Reuse inherited model/effort/requirements across turns unless the user explicitly
overrides them. All nested agent instructions use llmcall. Capture the complete
result, errors, warnings and execution/effects evidence; never hide stderr failures.
Judge suggestions against evidence, discuss disagreements using the caller's
actual identity, and preserve unresolved ambiguity for the user. Do not impose
obsolete source model choices or redundant approval questions on authorized work.
'''


def adapt(entry, body, parse_call, fence_pattern):
    name = entry.get('name')
    if name not in REVIEWED or entry.get('source_hash') != REVIEWED[name]:
        return None
    if name == 'codex':
        return {'template': CODEX, 'steps': [], 'workflow_kind': 'cli_compat',
                'recipe': {'kind': 'cli_compat', 'context_mode': 'explicit_local_history'}}
    calls = []
    for fence in fence_pattern.finditer(body):
        parsed = parse_call(fence.group(3))
        if parsed:
            calls.append(parsed)
    if len(calls) != (2 if name == 'research-review' else 3):
        raise ValueError('reviewed_source_call_count_changed')
    # Exact source pins bound the semantic adaptation; prompt blocks stay whole.
    template = COMMON + (RESEARCH if name == 'research-review' else LOOP)
    if name == 'research-review':
        template += '\n' + section(body, 'Prompt Templates')
    else:
        template += '\n' + section(body, 'Output Protocols')
    return {'template': template, 'calls': calls, 'workflow_kind': 'review',
            'recipe': {'kind': name, 'max_rounds': 4 if name == 'auto-review-loop' else None,
                       'context_mode': 'explicit_local_history', 'independent_review': True}}


def cli_request(argv):
    """Translate supported CLI intent, never shell text or provider sessions.

    Approval modes/full-auto and danger-full-access have no equivalent hard
    llmcall contract. Reject them instead of dropping them. Repo-check skipping
    is an execution preflight, not a permission grant, and is recorded explicitly.
    """
    args = list(argv)
    if args[:1] == ['codex']:
        args.pop(0)
    if args[:1] != ['exec']:
        raise ValueError('unsupported_cli_command')
    args.pop(0)
    result = {'resume': False, 'exact_model': None, 'effort': None, 'cwd': None,
              'requirements': None, 'source_argv': deepcopy(argv), 'repo_check': 'llmcall_default'}
    access = None
    while args:
        flag = args.pop(0)
        if flag == 'resume':
            if result['resume']:
                raise ValueError('duplicate_resume')
            result['resume'] = True
        elif flag == '--last':
            if not result['resume']:
                raise ValueError('last_requires_explicit_workflow_resume')
        elif flag == '--skip-git-repo-check':
            result['repo_check'] = 'not_required_by_caller'
        elif flag in ('-m', '--model', '-C', '--cd', '-c', '--config', '--sandbox'):
            if not args:
                raise ValueError('missing_cli_value')
            value = args.pop(0)
            if flag in ('-m', '--model'):
                result['exact_model'] = value
            elif flag in ('-C', '--cd'):
                result['cwd'] = value
            elif flag in ('-c', '--config'):
                key, sep, effort = value.partition('=')
                effort = effort.strip('"\'')
                if key != 'model_reasoning_effort' or not sep or effort not in ('low', 'medium', 'high', 'xhigh'):
                    raise ValueError('unsupported_cli_config')
                result['effort'] = effort
            else:
                access = {'read-only': 'read_only', 'workspace-write': 'workspace_write'}.get(value)
                if access is None:
                    raise ValueError('unsupported_cli_sandbox')
        else:
            raise ValueError('unsupported_cli_flag_or_native_session')
    if access is not None or not result['resume']:
        result['requirements'] = {'access': access or 'read_only', 'replay': 'never_after_start'}
    return result
