# Triage, deduplication and Spec-v1 scaffolding

## Deduplication before creation

Run `python scripts/dedup_check.py` against the installed skill inventory. G3 and G4 use the
same user skills and active-plugin inventory; preserve unknown or unresolved entries.

- For high overlap, route to `self-evolve` to improve the existing skill or integrate the capability.
- For a distinct task, choose a single skill or batch. A Step-0 brief with 2+ jobs requires a series
  of focused skills under [batch.md](batch.md), each with at most three modules.

## Scaffold a deterministic Spec-v1 skeleton

Templates are embedded in the scaffolder. Run helper commands from `skills/skill-smith` in
the source checkout. Generate the repository with:

```bash
python scripts/scaffold_skill.py <name> \
  --tagline "Verb-first, quantified, one line." \
  --description "When to trigger + what it does + scope, one paragraph (this is the trigger text)." \
  --topics "domain-a,domain-b" \
  --out-dir ~/CodesClaude            # default; the source-of-truth location
```

The principal entry files are initialized at version `0.1.0`:

```text
<name>/
  README.md  README_CN.md            rationale before setup, matching current meaning, badges
  LICENSE (MIT)
  PHILOSOPHY.md
  ROADMAP.md  CHANGELOG.md
  .claude-plugin/plugin.json         author=DaizeDong, homepage pattern, keywords end "skill"
  skills/<name>/SKILL.md             frontmatter and body skeleton
```

The scaffold also initializes pinned Guards and Style submodules, tracked `.githooks` forwarders,
and their required checks. Keep the badge order: Claude Code Skill (orange), License MIT (blue),
0 to 2 feature badges (green), Languages EN/CN (blue), then Roadmap vX.Y.Z (purple).

Assign a generation owner to complete the applicable documents using
[documentation.md](documentation.md). Map each behavior to its existing authoritative section
before writing. Fill the scaffold's current sections; later changes revise those sections and
remove superseded copies. README covers rationale, setup and normal use, ROADMAP covers current
and planned work, and CHANGELOG preserves release history. Keep reusable rationale and detailed
rules in reachable references. A generated skeleton or a successful draft check is not completion.

## Configuration at triage

Use `--with-config` when the skill owns user settings such as API keys, an installed-tool registry
or endpoints:

```bash
python scripts/scaffold_skill.py <name> --with-config   # + the flags above
```

The option emits `CONFIG.md`, generic `scripts/init_config.py` and `scripts/verify_config.py`,
`## Config` / `## 配置` README sections, and Mode B secrets ignore rules. It also emits the source
configuration and storage declarations described in [config-spec.md](config-spec.md). The generic
initializer and doctor detect the skill from `plugin.json` and are copied verbatim; they provide
starting templates, not proof of capability-specific readiness.

Check the unfinished scaffold and its static declarations:

```bash
python scripts/check_conformance.py ~/CodesClaude/<name> --stage draft
python scripts/check_config_conformance.py ~/CodesClaude/<name> --no-run
```

Complete the implementation, documents and applicable E1-E8 evidence before accepted-stage
conformance and the final candidate snapshot. Default conformance requires completed current docs
through the pinned Style checker. Configuration applicability and measured readiness follow
`config-spec.md`; a storage-only tool does not acquire an invented settings registry.

## Bump: version preparation

`plugin.json.version`, both README Roadmap badges, ROADMAP's top `Current:` value and the latest
numeric CHANGELOG release must agree. `scripts/version_sites.py` defines these five surfaces for
the scaffolder, linter and bumper. The initial version is `0.1.0`.

```bash
python scripts/bump_version.py <repo> --level patch|minor|major   # or --set X.Y.Z
python scripts/bump_version.py <repo> --level minor --notes "One line." --dry-run
```

The bumper updates all five surfaces and changes the version in the existing
`## vX.Y.Z (current)` ROADMAP heading. It preserves that section's body, planned work and any
historical sections. A nonstandard heading is left intact while the top `Current:` value updates.
Release notes become `## [X.Y.Z] - <today>` in CHANGELOG using substantive Unreleased content or
supplied notes. The bumper refuses an already drifted repository with exit 1 and a diff: reconcile the mismatched
surfaces, check conformance, then bump. Follow [documentation.md](documentation.md) for canonical
advancing versions, valid non-regressing release dates and completed release notes. Keep ROADMAP's
release references linked to CHANGELOG rather than copying the release body.

A pre-release badge marker such as `Roadmap-v0.2.2%20alpha-purple` is preserved by default;
`--prerelease TAG` sets it and `--no-prerelease` removes it. The marker exists only in the badges;
the other version surfaces remain numeric. A Python package additionally needs the aligned
`pyproject.toml` version required by [python-api.md](python-api.md).

The bumper never commits, tags or pushes. Version preparation does not authorize publication.

## Author the skill body

Generation (Step 2) and triggering work (Step 4), informed by the research brief, supply the actual
SKILL body and description. Keep the entry focused and load large references on demand. Preserve
commands, defaults, conditions, evidence limits and research rationale during edits; the
[documentation contract](documentation.md) defines semantic review and completion duties.
