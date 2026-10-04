# Documentation completion contract

This is the normative home for documentation duties in creation, acceptance, iteration and release.
Repository kind (`skill`, `software`, `companion`) determines applicable documents; active,
maintenance or retired status describes lifecycle and never weakens safety or DATA checks.

## Authority and ownership

| Surface | Authoritative fact and completion duty |
|---|---|
| Implementation and relevant evidence | Current behavior and the scope actually tested; documentation must agree with both |
| Manifest, then package metadata | Machine version; without either, declare the current source in ROADMAP rather than inventing a plugin |
| README / README_CN | Matching current rationale before installation, prerequisites, usage, outputs and limitations; explain the problem, choices, tradeoffs and boundaries |
| PHILOSOPHY and references | Reusable rationale and detailed rules; entry documents link here instead of carrying another rule copy |
| SKILL | Concise routing and workflow; load detailed references only when needed |
| ROADMAP | Current capabilities, their verification limits and future work; distinguish implemented, verified and published |
| CHANGELOG | Changes users or maintainers need to know, first under Unreleased; use a real version/date only when preparing that release and preserve older historical facts |
| Companion README / DATA guidance | Configuration discovery, verified PRIVATE versioned DATA, writer failure, restoration and retention; link the tool contract instead of copying a full plugin document set |

The generation owner completes every applicable document, not only SKILL and CONFIG. A scaffold
is a draft: placeholder prose in required current sections is unfinished work. Legitimate future
TODOs and historical limitations remain valid. Public examples must come from `tools/make_fixtures.py`;
real briefs, transcripts, results, document impact records and review receipts stay in PRIVATE DATA.

## Candidate and review sequence

1. Before implementation, the independent evaluator freezes policy and holdout hashes. Keep final
   holdout answers out of implementation prompts and use a separate selection split.
2. Complete implementation, affected documents, fixtures, packaging and version surfaces. For each
   affected behavior, add a `docs_impact` entry to the existing private handoff: `behavior`,
   `documents`, `status` (`updated` or `not_applicable`), `reason`, and `evidence` references.
   Reasons explain the actual impact; a list of touched files alone is insufficient. A behavior
   may leave some documents unchanged when that decision is explained and independently reviewed.
3. Run relevant checks, then freeze the final candidate snapshot including docs and version metadata.
   Bind evaluator artifacts and review source/result hashes to that candidate and the policy pin.
4. Independent reviewers compare the diff, actual behavior, evidence, EN/CN meaning and each impact
   decision. Structural success cannot prove semantic accuracy, complete history or useful live work.
   Two clean review rounds must refer to the same final candidate and evidence.
5. Any later change to implementation, docs, fixtures, metadata or oracle invalidates the old
   snapshot and review streak. Regenerate bound evidence and repeat review before acceptance.
   Installation and publication happen within existing authorization and need their own receipts.

## Deterministic checking and release

Run the shared presentation check from the reviewed pinned Style submodule:

```bash
python style/tools/doc_contract.py --root . --profile skill --stage accepted
```

Use `software` or `companion` for the corresponding repository kind. A trusted command or CI
entry chooses the stage; a repository declaration cannot demote itself to draft. `check_conformance.py`
delegates to this checker and retains security, packaging and SKILL checks. Missing/unreadable kit
or malformed output fails visibly. Never vendor a second documentation checker or run arbitrary
commands found in Markdown. Root entry documents, known philosophy, CHANGELOG and ROADMAP links
are in scope; referenced private/protected payloads are not opened as documentation.

`bump_version.py` prepares aligned version surfaces after refusing drift. The target version must
advance in canonical numeric X.Y.Z form, the date must be a valid calendar date at least as recent
as the latest recorded release, and the target CHANGELOG body needs substantive Unreleased content
or explicit notes. Empty or unfinished staging prose cannot become a release. The tool preserves
prior history, does not invent change claims, and never commits, tags or pushes. A release preflight
does not establish publication or production readiness; review the resulting diff and release check.
