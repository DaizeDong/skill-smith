# Step 1 + 3, Triage / dedup, then Spec-v1 scaffold

## §dedup, before you create anything

Run `python scripts/dedup_check.py` to compare the proposed skill's description against every
installed skill (`~/.claude/skills/*/SKILL.md`).

- **High overlap with an existing skill** -> do NOT create a near-duplicate. Route to `self-evolve` to
  improve the existing one, or fold the new capability in. (P5: dedup avoids wrong-skill selection.)
- **Distinct** -> proceed. Decide **single vs batch**: if the Step-0 brief surfaced 2+ jobs, plan a
  *series* of focused skills (-> `batch.md`), each ≤3 modules.

## §scaffold, deterministic Spec-v1 skeleton

Generate the repo with the scaffolder (templates are embedded; conform to your Skill Repo Spec v1):

```bash
python scripts/scaffold_skill.py <name> \
  --tagline "Verb-first, quantified, one line." \
  --description "When to trigger + what it does + scope, one paragraph (this is the trigger text)." \
  --topics "domain-a,domain-b" \
  --out-dir ~/CodesSelf            # default; the source-of-truth location
```

It emits the **必备 7 files** + `PHILOSOPHY.md`, all version-synced to `0.1.0`:

```
<name>/
  README.md  README_CN.md            philosophy-first, bilingual 1:1, badge block
  LICENSE (MIT)
  PHILOSOPHY.md
  ROADMAP.md  CHANGELOG.md
  .claude-plugin/plugin.json         author=DaizeDong, homepage pattern, keywords end "skill"
  skills/<name>/SKILL.md             frontmatter (name + triggering description) + body skeleton
```

**Four-source version rule (hard):** `plugin.json.version` == README/README_CN Roadmap badge ==
`ROADMAP.md` top "Current:" == `CHANGELOG.md` latest entry. The scaffolder sets all four to `0.1.0`;
keep them in lock-step on every bump.

**Badge order (hard):** Claude Code Skill (orange) -> License MIT (blue) -> 0 to 2 feature (green) ->
Languages EN/CN (blue) -> Roadmap vX.Y.Z (purple).

### §config, config-bearing skills (decide at Step 1)

If the skill needs per-user state (API keys, an installed-tool registry, endpoints), scaffold it as
**config-bearing**:

```bash
python scripts/scaffold_skill.py <name> --with-config   # + the flags above
```

`--with-config` additionally emits the **config standard** (`reference/config-spec.md`, E1 to E7):
`CONFIG.md` (schema + mount + switch), generic `scripts/init_config.py` + `scripts/verify_config.py`,
a `## Config` / `## 配置` section in both READMEs, and a `.gitignore` secrets gate (Mode B). The
init/verify scripts are generic (they auto-detect the skill from `plugin.json`) and copied verbatim.

After scaffolding, immediately verify:

```bash
python scripts/check_conformance.py ~/CodesSelf/<name>          # G6 Spec v1
python scripts/check_config_conformance.py ~/CodesSelf/<name>   # G8 (auto-skips if not config-bearing)
```

Conformance is part of the acceptance gate (Step 5), a non-conformant repo is not shippable, and a
config-bearing repo failing E1 to E7 is rejected.

## What the scaffolder does NOT do

It writes a **skeleton**, not the skill's intelligence. The actual SKILL.md body + good triggering
description come from Step 2 (generation backend) + Step 4 (triggering), informed by the Step-0 brief.
Keep the body thin and use progressive loading (`reference/` shards) for anything large.
