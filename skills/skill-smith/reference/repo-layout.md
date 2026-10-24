# Repository layout and presentation

Read this when scaffolding a public skill repository or restructuring its documents. Completion
duties and review are in [documentation.md](documentation.md); privacy and DATA rules are in the
fleet-guards checkout's `docs/DATA_BOUNDARY.md`.

## Files

For the plugin-wrapped scaffold. Standalone software uses its own package metadata; a companion
needs only its maintenance and DATA entry points.

| File | Required | Role |
|---|---|---|
| `README.md` | yes | English, authoritative |
| `README_CN.md` | yes | Chinese, section-for-section with the English one |
| `LICENSE` | yes | MIT |
| `.claude-plugin/plugin.json` | yes | Plugin manifest and machine version |
| `ROADMAP.md` | yes | Current capabilities and plans; version from the manifest |
| `CHANGELOG.md` | yes | Keep a Changelog style |
| `skills/<name>/SKILL.md` | yes | The skill |
| `PHILOSOPHY.md` | no | Long form of the design rationale |
| `CONSTITUTION.md` | no | Hard rules of a governance skill |
| `CONTRIBUTING.md`, `examples/` | no | |

A complete file set means the scaffold is complete, not that the content is done.

## `plugin.json`

`name` is the repository name in kebab-case; `version` is semver and matches ROADMAP, badges and
CHANGELOG; `description` is one paragraph of trigger situations and capabilities; `author.name` is
the repository owner; `homepage` is `https://github.com/<owner>/<repo>`; `license` is `MIT`;
`keywords` end with `"skill"`.

## README

Top block, identical in both languages: `# <repo-name>`, a one-line tagline that opens with a verb
or a number, the badges, then `[English](README.md) | [中文版](README_CN.md)`.

Badges in this order and colour: Claude Code Skill (orange, links the Claude Code docs), License MIT
(blue, `LICENSE`), 0 to 2 feature badges (green), Languages EN / CN (blue, `#languages`), Roadmap
vX.Y.Z (purple, `ROADMAP.md`). The Chinese README localizes and URL-encodes badge text.

Sections, rationale first:

1. Top block
2. `## ⭐ Read this first, the design philosophy`: why it is designed this way, one screen; long
   rationale goes to `PHILOSOPHY.md` with a summary here
3. `## What it is (and isn't)`
4. `## Install` (`/plugin install` and `git clone`)
5. `## Quick start`
6. `## Skills at a glance` (multi-skill repositories only)
7. `## How to invoke`
8. `## Example output`
9. `## Limitations`
10. `## Languages` (anchor `#languages`; Chinese `#语言`)
11. `## Roadmap · Contributing · License`

Editing one README means editing the other in the same change.

## GitHub topics

Lowercase, hyphenated, at most 50 characters each and 20 per repository. Every repository carries
the base nine: `claude-code claude-plugin claude-skill claude ai ai-agent agent llm skill`, plus up
to 11 domain topics drawn from the manifest keywords.
`gh repo edit <owner>/<repo> --add-topic <t1>,<t2>` adds without removing; clear stale ones with
`--remove-topic`.

## Versions

The manifest (or package metadata) is the machine version. README badges and ROADMAP's `Current:`
show the same number or link to the source. CHANGELOG keeps real history and an Unreleased section;
never invent release dates. A release updates every display at once (`tools/bump_version.py`);
ordinary internal changes do not need a version bump.

## No en or em dashes

Published prose carries no `–`, `—` or `―`; ASCII `-` stays legal for code, flags, file names,
versions, URLs and ranges.

- Renderers that put model-written text into user-visible output normalize the three dashes to a
  comma: `re.sub(r"\s*[–—―]+\s*", ", ", s)`.
- The repository's `.githooks/pre-commit` runs `python "$S/tools/dash_guard.py" --staged --added-only`
  from the fleet-style checkout (`git config fleet.style`) before forwarding to fleet-guards; an
  unset key blocks the commit. It checks added lines only, not history; fenced and inline code and
  lines marked `dash-guard: allow` are exempt.
- `--fix` replaces a spaced dash with `, `, an `A–B` range with `A to B`, and any other run with `,`.

## One fact, one layer

Each fact has exactly one home, chosen by what kind of fact it is. Other layers link to it and never
restate it.

| Layer | Where | Holds only | Cost |
|---|---|---|---|
| L0 | frontmatter `description` | Trigger conditions, at most 180 characters | Paid every turn |
| L1 | `SKILL.md` | Invariants, then the step table (do, with, produces, passes when), then the reference index | Paid every call |
| L2 | `reference/<topic>.md` | The single full statement of each method invariant | Loaded on demand |
| L3 | `docs/<date>-<topic>/` | Dated evidence, append-only, never cited as the source of a current rule | Never loaded |
| L4 | `README.md` / `README_CN.md` | Orientation, never the authority for a rule | Read by people |
| L5 | `CHANGELOG.md` / `ROADMAP.md` | Versions, history and plans | Read by people |

- L0 test: a model that has never read the skill can decide from the description alone whether to
  call it. No capability lists, boasts or version markers.
- L1's index states only load conditions ("to do X, read `reference/x.md`"), never summaries, and
  every file it names exists.
- Any sentence in L1 that also lives in L2 is deleted and replaced by a pointer.

Revising a rule: replace the sentence in its L2 home, in the present tense, as if it had always read
that way. Do not narrate the change ("previously X, now Y", "since v2"); the change goes into
CHANGELOG and nowhere else. Only L3 is chronological.

## Skeletons

README (both languages follow it section for section):

```markdown
# <repo-name>

<one-line tagline>

<badges>

[English](README.md) | [中文版](README_CN.md)

---

## ⭐ Read this first, the design philosophy
## What it is (and isn't)
## Install
## Quick start
## How to invoke
## Example output
## Limitations
## Languages
## Roadmap · Contributing · License
```

CHANGELOG:

```markdown
# Changelog

## [Unreleased]

## [0.1.0] - YYYY-MM-DD
### Added
- Initial release.
```

ROADMAP:

```markdown
# Roadmap

Current: v0.1.0

## v0.1.0 (current)
## Planned
```
