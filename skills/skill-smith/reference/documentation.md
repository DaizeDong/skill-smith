# Documentation completion contract

This is the normative home for documentation duties in creation, acceptance, iteration and release.
Repository kind (`skill`, `software`, `companion`, `combined`) determines applicable documents; active,
maintenance or retired status describes lifecycle and never weakens safety or DATA checks.

## Authority and ownership

| Surface | Authoritative fact and completion duty |
|---|---|
| Implementation and relevant evidence | Current behavior and the scope actually tested; documentation must agree with both |
| Manifest, then package metadata | Machine version; without either, declare the current source in ROADMAP rather than inventing a plugin |
| README / README_CN | Matching current rationale before installation, then prerequisites, setup, normal use, outputs and limitations; link detailed operating rules and references |
| PHILOSOPHY and references | Reusable rationale, research foundations, tradeoffs and detailed rules; each rule has one authoritative section reached from the entry documents |
| SKILL | Concise routing and workflow; load detailed references only when needed |
| ROADMAP | Current capabilities, verification limits and planned work; distinguish implemented, verified and published, and link release history in CHANGELOG |
| CHANGELOG | User-visible and maintainer-relevant changes under Unreleased, grouped by resulting behavior; use real versions/dates for releases and preserve historical facts and evidence limits |
| Companion README / DATA guidance | Configuration discovery, verified PRIVATE versioned DATA, writer failure, restoration and retention; link the tool contract instead of copying a full plugin document set |

The generation owner completes every applicable document. A scaffold is a draft: placeholder prose
in required current sections is unfinished work. Legitimate future TODOs and historical limitations
remain valid. Public examples must come from `tools/make_fixtures.py`; real briefs, transcripts,
results, document impact records and review receipts stay in PRIVATE DATA.

Maintain the existing authoritative section when behavior changes. Merge new conditions and recovery
steps into that section, remove superseded or duplicate current instructions, and replace secondary
copies with links. Add a section only for a distinct topic with no suitable existing home. README
introduces the tool and normal use; ROADMAP records current and planned capabilities; CHANGELOG
preserves release history. Do not append dated progress reports or repeated policy explanations to
current guidance. Consolidate redundant Unreleased bullets by resulting change while retaining
unique fixes and validation limits. Preserve released versions, dates and facts; archive history
only with verbatim preservation and a working index.

Before rewriting, identify protected facts: commands, flags, paths, names, defaults, numeric limits,
versions, authorization, DATA boundaries, failure and recovery behavior, implementation status,
evidence scope, research rationale and citations. Preserve their subjects, conditions and strength.
Use standard technical language to state purpose, inputs, outputs, steps and limits; removing
rhetoric must not remove rationale or turn a plan, static check or partial run into a verified claim.
Keep EN/CN current meaning aligned. When moving guidance, preserve required headings and inbound
anchors or update every tracked reference; a shorter entry is complete only when its details remain
reachable.

## Candidate and review sequence

1. Before implementation, the independent evaluator freezes policy and holdout hashes. Keep final
   holdout answers out of implementation prompts and use a separate selection split.
2. Complete implementation, affected documents, fixtures, packaging and version surfaces. Apply the
   authority and consolidation rules above. For each affected behavior, update a `docs_impact` entry
   in the existing private handoff: `behavior`,
   `documents`, `status` (`updated` or `not_applicable`), `reason`, and `evidence` references.
   Reasons explain the actual impact; a list of touched files alone is insufficient. A behavior
   may leave some documents unchanged when that decision is explained and independently reviewed.
3. Run relevant checks, then freeze the final candidate snapshot including docs and version metadata.
   Bind evaluator artifacts and review source/result hashes to that candidate and the policy pin.
4. Independent reviewers compare the diff, actual behavior, evidence, EN/CN meaning and each impact
   decision. Check protected facts in both directions: every retained fact remains traceable to its
   authority, and every revised claim is supported. Confirm that current instructions have one
   authoritative home and moved details remain reachable. Structural success cannot prove semantic
   accuracy, complete history or useful live work. Two clean review rounds must refer to the same
   final candidate and evidence.
5. Any later change to implementation, docs, fixtures, metadata or oracle invalidates the old
   snapshot and review streak. Regenerate bound evidence and repeat review before acceptance.
   Installation and publication happen within existing authorization and need their own receipts.

## Deterministic checking and release

Run the shared presentation check from the reviewed pinned Style submodule:

```bash
python style/tools/doc_contract.py --root . --profile skill --stage accepted
```

Use `software` or `companion` for the corresponding repository kind. An explicitly combined PRIVATE
source/backup repository uses `combined`: bounded maintenance README, ROADMAP and
`docs/MAINTENANCE_CHANGELOG.md`, as defined by the pinned Style kit's
[combined profile](../../../style/docs/COMBINED_DOCUMENTATION.md). Captured root CHANGELOG and
other backup payloads are not opened as release documentation. This profile still needs meaningful
rationale, setup, current state, recovery and a local storage-contract link; it grants no PRIVATE
storage or publication proof. Configuration ownership remains a separate `config.contract.json` axis.
A trusted command or CI
entry chooses the stage; a repository declaration cannot demote itself to draft. `check_conformance.py`
delegates to this checker and retains security, packaging and SKILL checks. Missing/unreadable kit
or malformed output fails visibly. Never vendor a second documentation checker or run arbitrary
commands found in Markdown. Root entry documents, known philosophy, CHANGELOG and ROADMAP links
are in scope; referenced private/protected payloads are not opened as documentation.

`bump_version.py` prepares aligned version surfaces after refusing drift. It updates the existing
current-version ROADMAP heading in place and preserves current, planned and historical prose;
nonstandard headings retain their text while the top `Current:` value updates. Release notes belong
in CHANGELOG. The target version must
advance in canonical numeric X.Y.Z form, the date must be a valid calendar date at least as recent
as the latest recorded release, and the target CHANGELOG body needs substantive Unreleased content
or explicit notes. Empty or unfinished staging prose cannot become a release. The tool preserves
prior history, does not invent change claims, and never commits, tags or pushes. A release preflight
does not establish publication or production readiness; review the resulting diff and release check.
