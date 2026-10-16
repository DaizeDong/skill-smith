#!/usr/bin/env python3
"""Scaffold a Skill-Repo-Spec-v1-conformant Claude Code skill repo skeleton.

Creates version-aligned entry documents, a skill skeleton and .githooks shims.
Complete the draft content under ../reference/scaffold.md before accepted-stage conformance.
Stdlib only.

Usage:
  python scaffold_skill.py my-skill \
    --tagline "Verb-first, quantified, one line." \
    --description "When to trigger + what it does + scope, one paragraph." \
    --topics "domain-a,domain-b" [--out-dir ~/CodesClaude] [--version 0.1.0] [--force]
    [--with-config]   # also emit the config-bearing standard (config-spec E1-E8)
"""
import argparse
import json
import os
import shlex
import subprocess
import sys
import datetime
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import version_sites  # noqa: E402  (sibling module: the one definition of where a version lives)

# The badge block, including the Roadmap badge that is one of the five version sites, is defined
# once in version_sites.py. check_conformance.py reads those sites and bump_version.py rewrites
# them; if the shape were re-typed here, a bump could stamp a badge its own linter rejects.
REQUIRED_BADGES = version_sites.REQUIRED_BADGES

LICENSE_TMPL = """MIT License

Copyright (c) __YEAR__ DaizeDong

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

README_TMPL = """# __NAME__

__TAGLINE__

__BADGES__
[English](README.md) | [中文版](README_CN.md)

---

## ⭐ Design philosophy

TODO: explain the problem __NAME__ addresses, relevant evidence, the chosen approach,
tradeoffs and limits. Keep the summary here and detailed rationale in PHILOSOPHY.md.

[Design rationale](PHILOSOPHY.md)

---

## Purpose and scope

TODO: identify intended users, inputs, outputs and operating boundaries.

## Install

```
/plugin install github:DaizeDong/__NAME__
```

Or clone manually:

```bash
git clone https://github.com/DaizeDong/__NAME__.git ~/.claude/plugins/__NAME__
```

## Quick start

TODO.

## How to invoke

TODO: trigger words.

## Example output

TODO.

## Limitations

TODO.

## Languages

English (`README.md`, authoritative) · 中文 (`README_CN.md`)

## Roadmap · License

See [ROADMAP.md](ROADMAP.md) · [LICENSE](LICENSE) (MIT).
"""

README_CN_TMPL = """# __NAME__

__TAGLINE__

__BADGES_CN__
[English](README.md) | [中文版](README_CN.md)

---

## ⭐ 设计理念

TODO: 说明 __NAME__ 要解决的问题、相关证据、采用的方法、取舍和限制。
本节保留概述，详细设计依据写在 PHILOSOPHY.md。

[设计依据](PHILOSOPHY.md)

---

## 用途与范围

TODO: 说明目标用户、输入、输出和运行边界。

## 安装

```
/plugin install github:DaizeDong/__NAME__
```

或手动克隆:

```bash
git clone https://github.com/DaizeDong/__NAME__.git ~/.claude/plugins/__NAME__
```

## 快速开始

TODO。

## 如何触发

TODO: 触发词。

## 示例输出

TODO。

## 局限

TODO。

## 语言

中文 (`README_CN.md`) · English (`README.md`, 权威版)

## Roadmap · 许可

见 [ROADMAP.md](ROADMAP.md) · [LICENSE](LICENSE)(MIT)。
"""

PHILOSOPHY_TMPL = """# __NAME__, Design Philosophy

TODO: explain the problem, relevant evidence and design choices for __NAME__.
Update each principle when its decision changes; retain supporting references and known limits.

## P1, <principle>
- **Problem and evidence:** TODO.
- **Decision:** TODO.
- **Tradeoffs and limits:** TODO.
"""

ROADMAP_TMPL = """# Roadmap

Current: **v__VER__**

Release history is recorded in [CHANGELOG.md](CHANGELOG.md).

## v__VER__ (current)
- TODO: describe implemented capabilities and their verification limits.

## Planned
- TODO: describe planned work separately from current capabilities.
"""

CHANGELOG_TMPL = """# Changelog

All notable changes to this project are documented here (Keep a Changelog style).

## [__VER__] - __DATE__
### Added
- Initial release.
"""

SKILL_TMPL = """---
name: __NAME__
description: __DESC__
---

# __NAME__

> Governing principle (full text in the repo's `PHILOSOPHY.md`): TODO one line.

## When to use / when to stop

TODO: when this fires, and what to route elsewhere.

## Workflow

TODO: thin steps. Push large content into `reference/<shard>.md` loaded on demand.

## Hard rules

TODO.

## Progressive loading

This `SKILL.md` is the only always-loaded file. Read `reference/<shard>.md` on demand.
"""

PUBLIC_RATIONALE_TMPL = """# Public design rationale, __NAME__

> TOOL documentation for reusable behavior. Keep the complete real research brief, user inputs,
> scope decisions and evaluation artifacts in verified PRIVATE versioned DATA. Do not copy real
> run reports or private artifact paths into this document. Examples must be generated synthetic data.

## Best references (match-or-beat)
- TODO: public implementation references relevant to the reusable tool design.

## Frontier ideas to incorporate
- TODO

## Anti-patterns to avoid
- TODO

## Proof bar (how we will show it is tested-real)
- TODO (defines the eval signal for the acceptance gate + self-evolve)

## Scope & focus (one job, <=3 modules)
- TODO
"""


def kebab(s):
    return re.sub(r"[^a-z0-9]+", "-", s.strip().lower()).strip("-")


ASSETS_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "config")


def _read_asset(rel):
    with open(os.path.join(ASSETS_CONFIG, rel), "r", encoding="utf-8") as f:
        return f.read()


def emit_config_bearing(root, name, force, write_fn):
    """Emit the config-bearing standard (config-spec E1-E8) into the new skill repo.

    - scripts/{init_config,verify_config,config_runtime}.py (consumer-bound config tools)
    - CONFIG.md (schema + mount + first-time + switch)
    - README.md / README_CN.md '## Config' section appended
    - .gitignore with the secrets gate (E6)
    - storage.contract.json declaring companion artifacts and retention (E8)
    """
    env = name.upper().replace("-", "_") + "_CONFIG"
    applicability = {
        "schema_version": 1, "repository_kind": "skill", "configuration": "settings",
        "rationale": "This scaffold owns companion settings; capability-specific readiness remains unfinished.",
        "documentation": ["README.md", "README_CN.md", "CONFIG.md"],
        "settings": {
            "schema_document": "CONFIG.md", "discovery_document": "CONFIG.md",
            "environment": env, "aliases": [name.upper().replace("-", "_") + "_DATA_DIR"],
            "precedence": ["explicit config directory", env, "shared companion resolver"],
            "required_fields": ["capability.required_resource"],
            "initializer": {"path": "scripts/init_config.py", "args": ["--out", "{output}"]},
            "doctor": {"path": "scripts/verify_config.py", "args": []}}}
    write_fn(os.path.join(root, "config.contract.json"), json.dumps(applicability, indent=2) + "\n", force)

    def fill(t):
        return (t.replace("__NAME__", name)
                 .replace("__ENVVAR__", env)
                 .replace("__DATAENV__", name.upper().replace("-", "_") + "_DATA_DIR"))

    # The shared runtime binds both commands to the emitted consumer's plugin identity.
    for script in ("init_config.py", "verify_config.py", "config_runtime.py"):
        write_fn(os.path.join(root, "scripts", script), _read_asset(script), force)
    # authoritative config doc + secrets gitignore
    write_fn(os.path.join(root, "CONFIG.md"), fill(_read_asset("CONFIG.md.tmpl")), force)
    write_fn(os.path.join(root, ".gitignore"), _read_asset("skill-gitignore.tmpl"), force)
    contract = {
        "schema_version": 1,
        "tool": name,
        "max_bytes": 64 * 1024 * 1024,
        "artifacts": [
            {
                "artifact_id": "registry",
                "path_pattern": "registry.json",
                "purpose": "Current installed-tool settings and credential references.",
                "schema": "CONFIG.md: registry.json schema_version 1",
                "producer": "scripts/init_config.py and explicit configuration updates",
                "consumer_or_final_deliverable": "scripts/verify_config.py and configured tools",
                "rebuild_or_restore": "Restore the current registry from the PRIVATE companion backup.",
                "retention_rule": {"class": "core", "rule": "Keep while any configured tool depends on these settings; retire only after migration is verified."},
            },
            {
                "artifact_id": "selected_credentials",
                "path_pattern": "secrets/**",
                "purpose": "Selected credentials and current backup and recovery instructions.",
                "schema": "CONFIG.md: UTF-8 credential env files; Markdown recovery instructions",
                "producer": "scripts/init_config.py and explicit credential setup or rotation",
                "consumer_or_final_deliverable": "Configured tools and the operator performing recovery",
                "rebuild_or_restore": "Use the selected PRIVATE backup described in secrets/README.md; reissue revoked credentials.",
                "retention_rule": {"class": "core", "rule": "Keep required credentials and recovery instructions while their configured tools remain active; review retirement after removal or rotation."},
            },
            {
                "artifact_id": "recovery_readme",
                "path_pattern": "README.md",
                "purpose": "Current companion setup, backup and restoration instructions.",
                "schema": "Markdown companion recovery instructions",
                "producer": "Operator completing companion setup",
                "consumer_or_final_deliverable": "Operator restoring the current configuration",
                "rebuild_or_restore": "Restore from the PRIVATE companion backup and verify the documented recovery procedure.",
                "retention_rule": {"class": "core", "rule": "Keep the current recovery procedure while the companion is in use; replace obsolete instructions after verifying the replacement."},
            },
            {
                "artifact_id": "credential_ignore_rules",
                "path_pattern": ".gitignore",
                "purpose": "Default exclusions for credentials not selected for versioned backup.",
                "schema": "Git ignore patterns described in CONFIG.md",
                "producer": "scripts/init_config.py and reviewed backup-policy updates",
                "consumer_or_final_deliverable": "Git staging and scripts/verify_config.py",
                "rebuild_or_restore": "Restore the reviewed rules from the PRIVATE companion backup; initialization provides the default rules.",
                "retention_rule": {"class": "core", "rule": "Keep effective exclusion rules while the companion stores configuration or credentials."},
            },
            {
                "artifact_id": "companion_ownership",
                "path_pattern": ".companion",
                "purpose": "Optional ownership marker for companion discovery.",
                "schema": "UTF-8 text containing the tool name from this contract",
                "producer": "Operator selecting marker-based companion ownership",
                "consumer_or_final_deliverable": "fleet_guards.runtime.companion_resolver companion discovery",
                "rebuild_or_restore": "Restore the marker from the PRIVATE companion backup or regenerate it using this contract's tool identity.",
                "retention_rule": {"class": "core", "rule": "Keep while discovery relies on the marker; retire only after an alternative ownership proof is verified."},
            },
            {
                "artifact_id": "tools_directory_marker",
                "path_pattern": "tools/.gitkeep",
                "purpose": "Preserve the initially empty tool-configuration directory.",
                "schema": "Empty file",
                "producer": "scripts/init_config.py",
                "consumer_or_final_deliverable": "Git checkout of the empty tools directory",
                "rebuild_or_restore": "Recreate an empty tools/.gitkeep when the directory has no configured tools.",
                "retention_rule": {"class": "rebuildable", "rule": "Keep while tools is empty; it may be retired after a tracked tool configuration preserves the directory."},
            },
            {
                "artifact_id": "tool_launcher_templates",
                "path_pattern": "tools/*/claude.json.template",
                "purpose": "Required launcher settings for each configured tool.",
                "schema": "CONFIG.md: per-tool JSON template with UPPER_SNAKE placeholders",
                "producer": "Operator configuring a selected tool",
                "consumer_or_final_deliverable": "The selected tool's launcher configuration",
                "rebuild_or_restore": "Restore the current template from the PRIVATE companion backup and substitute selected credentials privately.",
                "retention_rule": {"class": "core", "rule": "Keep while the corresponding registry tool is configured; review retirement after uninstalling it and verifying no consumer remains."},
            },
            {
                "artifact_id": "tool_environment_templates",
                "path_pattern": "tools/*/env.template",
                "purpose": "Required environment variable names for each configured tool.",
                "schema": "CONFIG.md: UTF-8 KEY=UPPER_SNAKE-placeholder template",
                "producer": "Operator configuring a selected tool",
                "consumer_or_final_deliverable": "The selected tool's credential setup and environment loader",
                "rebuild_or_restore": "Restore the current template from the PRIVATE companion backup and obtain values from the selected credential backup.",
                "retention_rule": {"class": "core", "rule": "Keep while the corresponding registry tool is configured; review retirement after uninstalling it and verifying no consumer remains."},
            },
        ],
    }
    write_fn(os.path.join(root, "storage.contract.json"),
             json.dumps(contract, indent=2, ensure_ascii=False) + "\n", force)
    # append README '## Config' sections (idempotent: skip if already present)
    for readme, asset in (("README.md", "readme-config-section.md.tmpl"),
                          ("README_CN.md", "readme-config-section.cn.md.tmpl")):
        p = os.path.join(root, readme)
        existing = ""
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                existing = f.read()
        section = fill(_read_asset(asset))
        if "## Config" in existing or "## 配置" in existing:
            print("  SKIP (Config section exists): %s" % p)
            continue
        with open(p, "a", encoding="utf-8", newline="\n") as f:
            f.write("\n" + section)
        print("  appended Config section: %s" % p)


def write(path, content, force):
    if os.path.exists(path) and not force:
        print("  SKIP (exists): %s" % path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print("  wrote: %s" % path)


DATACLASS_TMPL = """{
  "_comment": [
    "Spec v1 s9 -- every path in this repo belongs to exactly one class.",
    "TOOL    = code, SKILL.md, docs, and metrics ABOUT THE SKILL. Public, hand-written, no data.",
    "FIXTURE = tests and examples. Public, SYNTHETIC, produced by tools/make_fixtures.py.",
    "DATA    = anything a REAL RUN produced. Versioned in the verified PRIVATE companion,",
    "          never in this public tool repo. Resolve with fleet_guards.runtime.companion_resolver.",
    "",
    "Declare DATA paths here BEFORE the skill has anything to write, not after. A skill that",
    "appends real-run output to a git-tracked file will do it on every run, quietly, forever --",
    "that is how a public repo came to hold real-run output from the operator's own account, and no",
    "content scanner can see it (a ticker with an entry price has no email or phone in it).",
    "",
    "data_sealed = a path that HELD real data, was purged, and must stay dead. Checked like data,",
    "exempt from the .example schema requirement.",
    "",
    "An EMPTY declaration is not a free pass and it is not a place for an argument: check 4 reads",
    "the tracked file list, not this manifest, and fails any file wearing the shape of real-run",
    "output (a jsonl under metrics/, a runs/ tree, a dated file under an output dir, a live-ledger",
    "filename, a database). Six repos once shipped a careful paragraph here concluding they had",
    "nothing to declare, and a verifier committed metrics/live-runs.jsonl into every one of them",
    "with the boundary check still exiting 0. `tool` is that check's per-path allowlist, for a",
    "hand-written TOOL file that happens to wear the shape; write the reason next to it."
  ],
  "data": [],
  "data_sealed": [],
  "fixture": [],
  "tool": [],
  "_run_shape_probes": [],
  "_probes_comment": [
    "THIS MANIFEST IS DELIBERATELY INCOMPLETE, and the boundary check will say so until you fill",
    "it. Two keys are yours to complete before this skill is published, and neither can be filled",
    "at scaffold time because neither is knowable before the skill has run.",
    "",
    "_audited      why the `data` list above is empty, or what is in it. Not a paragraph for its",
    "              own sake: name where this skill's real output actually goes and how you checked.",
    "_run_shape_probes",
    "              SCHEMATIC filenames naming what a real run of THIS skill writes. Check 4 objects",
    "              only to what it RECOGNISES, so a shape list that recognises nothing prints",
    "              exactly what a clean repo prints. Measured across the fleet on 2026-08-29: the",
    "              shared shape list matched 16 of 54 real output names, and 7 of 18 repos scored",
    "              zero, while every one of them writes output on every run.",
    "",
    "How to fill it: inspect shipped write paths and synthetic runs; inspect real output only",
    "when authorized. Score schematic output names with",
    "    python $(git config --get fleet.guards)/tools/data_boundary.py --explain <name> <name> ...",
    "Then rewrite each name into its SCHEMATIC form and commit that. A probe carrying a real",
    "ticker, mailbox handle, channel id or counterparty name is private data in a public repo even",
    "with no file behind it, which would reintroduce the leak under the banner of preventing it.",
    "A probe that matches no shape is reported by name: that is a gap in the shared list, not a",
    "reason to delete the probe."
  ],
  "_data_home": "Verified PRIVATE versioned %(name)s-config companion (override with $%(env)s); no in-repo fallback."
}
"""


# The standard .githooks shims. The checks live in the local fleet-guards and fleet-style
# checkouts named by git config fleet.guards and fleet.style; an unset key is a block.
HOOK_SHIMS = {
    "pre-commit": '#!/bin/sh\n# Privacy checks run from the local fleet-guards checkout named by git config fleet.guards.\nG=$(git config --get fleet.guards)\nif [ -z "$G" ] || [ ! -s "$G/hooks/pre-commit" ]; then\n  echo "BLOCKED: git config fleet.guards is unset or has no hooks/pre-commit; nothing was checked." >&2\n  exit 1\nfi\nS=$(git config --get fleet.style)\nif [ -z "$S" ] || [ ! -s "$S/tools/dash_guard.py" ]; then\n  echo "BLOCKED: git config fleet.style is unset or has no tools/dash_guard.py; nothing was checked." >&2\n  exit 1\nfi\npython "$S/tools/dash_guard.py" --check --staged --added-only </dev/null || exit 1\nexec sh "$G/hooks/pre-commit" "$@"\n',
    "pre-push": '#!/bin/sh\n# Privacy checks run from the local fleet-guards checkout named by git config fleet.guards.\nG=$(git config --get fleet.guards)\nif [ -z "$G" ] || [ ! -s "$G/hooks/pre-push" ]; then\n  echo "BLOCKED: git config fleet.guards is unset or has no hooks/pre-push; nothing was checked." >&2\n  exit 1\nfi\nexec sh "$G/hooks/pre-push" "$@"\n',
}

# Starts EMPTY on purpose. An exemption file shipped with entries in it is an off switch
# somebody else flipped, in a repo nobody has looked at yet.
PII_ALLOW_TMPL = """# One exemption per line, each with a comment saying why it is not real.
# A bare common word is not an exemption, it is an off switch for a whole class,
# written inside the repo it is supposed to protect.
"""

def checked_git(root, *args):
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise SystemExit("git %s failed: %s" % (args[0], result.stderr.strip()))
    return result.stdout.strip()


def emit_hook_shims(root, force):
    """Write the tracked .githooks shims and enable them with core.hooksPath."""
    for hook, body in HOOK_SHIMS.items():
        target = os.path.join(root, ".githooks", hook)
        if os.path.exists(target) and not force:
            with open(target, encoding="utf-8") as f:
                if f.read() != body:
                    raise SystemExit("Existing %s differs; review it before using --force." % target)
        write(target, body, force)
        os.chmod(target, 0o755)
    checked_git(root, "add", "--chmod=+x", "--", ".githooks/pre-commit", ".githooks/pre-push")
    checked_git(root, "config", "core.hooksPath", ".githooks")


def emit_guards(root, force, name):
    """Spec v1 sections 8 + 9 + 10: every public repo is born with the gates already in it.

    Section 8 (pii_guard) is the backstop: it reads what you are about to publish and looks for
    things that smell private. The 2026-07 audit found a phone number, a home ZIP, an employer and
    a health-provider name in five public skill repos, because the agent writing them was looking
    at the operator's real life for its examples and nothing forced a translation step.

    Section 9 (data_boundary) is the PRIMARY control, and it exists because the same audit found
    something the scanner could never have caught: real-run output from a private account, none of
    it pasted in by anyone. The SKILLS WROTE IT THERE, on every real run, by design. A ticker with
    an entry price contains no email, no phone, no ZIP; there is nothing to smell. So the repo
    ships as an UNINITIALIZED TOOL: real-run output resolves to a private store, and an agent
    writing this repo has nothing real within reach to copy.

    Section 10 (dash_guard) is the house rule that published prose carries no en/em dash.

    The checks are not copied into the repo. The tracked .githooks shims run the local
    fleet-guards and fleet-style checkouts named by git config fleet.guards and fleet.style.

    A repo that starts without these accumulates the debt before anyone thinks to add them, and by
    then the fix is no longer an edit, it is a history rewrite and a force-push.
    """
    print("Guards (Spec v1 sections 8 + 9 + 10):")
    # git init FIRST: the hooks need a repo. Idempotent on an existing repo.
    if not os.path.exists(os.path.join(root, ".git")):
        checked_git(root, "init", "-q")
        print("  git init")
    emit_hook_shims(root, force)
    print("  hooks: tracked .githooks shims; core.hooksPath = .githooks")

    # .pii-allow and .dataclass.json stay in the repo, never in the kit. Which paths are
    # TOOL, FIXTURE or DATA, and which findings are exempt, are facts about THIS repo. A shared
    # copy would be an exemption list written once and applied to repos nobody checked.
    allow = os.path.join(root, ".pii-allow")
    if os.path.exists(allow) and not force:
        print("  SKIP (exists): %s" % allow)
    else:
        with open(allow, "w", encoding="utf-8", newline=chr(10)) as f:
            f.write(PII_ALLOW_TMPL)
        print("  wrote: %s" % allow)

    dc = os.path.join(root, ".dataclass.json")
    if os.path.exists(dc) and not force:
        print("  SKIP (exists): %s" % dc)
    else:
        with open(dc, "w", encoding="utf-8", newline=chr(10)) as f:
            f.write(DATACLASS_TMPL % {"name": name,
                                      "env": name.upper().replace("-", "_") + "_DATA_DIR"})
        print("  wrote: %s" % dc)


def main():
    ap = argparse.ArgumentParser(description="Scaffold a Spec-v1 Claude Code skill repo.")
    ap.add_argument("name", help="skill / repo name (kebab-case)")
    ap.add_argument("--tagline", default="TODO: one-line, verb-first, quantified tagline.")
    ap.add_argument("--description", default="TODO: when to trigger + what it does + scope, one paragraph.")
    ap.add_argument("--topics", default="", help="comma-separated domain keywords (excl. trailing 'skill')")
    ap.add_argument("--out-dir", default=os.path.expanduser("~/CodesClaude"))
    ap.add_argument("--version", default="0.1.0")
    ap.add_argument("--with-config", action="store_true",
                    help="emit the config-bearing standard (config-spec E1-E8): CONFIG.md, "
                         "init/verify scripts, README Config section, secrets .gitignore, storage contract")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    name = kebab(a.name)
    if not name:
        print("ERROR: name %r normalizes to empty kebab-case; give a name with letters/digits." % a.name)
        return 2
    if name != a.name:
        print("normalized name -> %s" % name)
    ver = a.version
    year = str(datetime.date.today().year)
    date = datetime.date.today().isoformat()
    root = os.path.join(a.out_dir, name)

    if os.path.isdir(root) and not a.force:
        print("ERROR: %s already exists. Use --force to overwrite individual files." % root)
        return 2

    domain_topics = [kebab(t) for t in a.topics.split(",") if t.strip()]
    keywords = domain_topics + ["skill"]

    badges = REQUIRED_BADGES.replace("__VER__", ver)
    # CN localizes the Languages + Roadmap label text minimally (badge URLs already encode EN/CN).
    badges_cn = badges

    def sub(t):
        return (t.replace("__NAME__", name)
                 .replace("__TAGLINE__", a.tagline)
                 .replace("__DESC__", a.description)
                 .replace("__VER__", ver)
                 .replace("__YEAR__", year)
                 .replace("__DATE__", date)
                 .replace("__BADGES_CN__", badges_cn)
                 .replace("__BADGES__", badges))

    plugin = {
        "name": name,
        # Same reason as the badge: the field name is a version SITE, owned by version_sites.py.
        version_sites.PLUGIN_VERSION_FIELD: ver,
        "description": a.description,
        "author": {"name": "DaizeDong"},
        "homepage": "https://github.com/DaizeDong/%s" % name,
        "license": "MIT",
        "keywords": keywords,
    }

    try:
        import yaml
    except ImportError as exc:
        raise SystemExit("PyYAML is required to validate generated metadata: python -m pip install PyYAML") from exc
    skill_template = SKILL_TMPL.replace('name: __NAME__', 'name: __YAML_NAME__').replace('__DESC__', '__YAML_DESCRIPTION__')
    skill_text = sub(skill_template).replace('__YAML_NAME__', json.dumps(name)).replace(
        '__YAML_DESCRIPTION__', json.dumps(a.description, ensure_ascii=False))
    frontmatter = yaml.safe_load(skill_text[4:].split('\n---\n', 1)[0])
    if frontmatter != {'name': name, 'description': a.description}:
        raise SystemExit("Generated skill frontmatter did not preserve its metadata")

    print("Scaffolding %s (v%s) at %s" % (name, ver, root))
    write(os.path.join(root, "README.md"), sub(README_TMPL), a.force)
    write(os.path.join(root, "README_CN.md"), sub(README_CN_TMPL), a.force)
    write(os.path.join(root, "LICENSE"), sub(LICENSE_TMPL), a.force)
    write(os.path.join(root, "PHILOSOPHY.md"), sub(PHILOSOPHY_TMPL), a.force)
    write(os.path.join(root, "ROADMAP.md"), sub(ROADMAP_TMPL), a.force)
    write(os.path.join(root, "CHANGELOG.md"), sub(CHANGELOG_TMPL), a.force)
    write(os.path.join(root, ".claude-plugin", "plugin.json"),
          json.dumps(plugin, indent=2, ensure_ascii=False) + "\n", a.force)
    write(os.path.join(root, "skills", name, "SKILL.md"), skill_text, a.force)
    write(os.path.join(root, "docs", "design-rationale.md"), sub(PUBLIC_RATIONALE_TMPL), a.force)
    # progressive-loading dir for the new skill
    write(os.path.join(root, "skills", name, "reference", ".gitkeep"), "", a.force)

    emit_guards(root, a.force, name)

    if a.with_config:
        print("Config-bearing standard (config-spec E1-E8):")
        emit_config_bearing(root, name, a.force, write)
    else:
        applicability = {"schema_version": 1, "repository_kind": "skill", "configuration": "none",
                         "rationale": "Draft scaffold has no settings or runtime DATA producer; review when adding either.",
                         "documentation": ["README.md", "README_CN.md"]}
        write(os.path.join(root, "config.contract.json"), json.dumps(applicability, indent=2) + "\n", a.force)

    scripts = os.path.dirname(os.path.abspath(__file__))
    print("\nDraft scaffold created; documentation and acceptance are unfinished. Next:")
    print("  0) PII gate: every clone runs `git config core.hooksPath .githooks` (local config cannot")
    print("     be committed); the shims need git config fleet.guards and fleet.style set.")
    print("     Commit identity MUST be the GitHub noreply address -- a real mailbox on the author")
    print("     line is the one leak no file scan will ever see (Spec v1 s8).")
    print("  1) Store the real Step 0 brief in verified PRIVATE versioned DATA/research/.")
    print("     Freeze evaluator policy + holdout BEFORE implementation or drafting candidate docs.")
    print("     docs/design-rationale.md is public TOOL documentation; use only reusable design and synthetic examples.")
    if a.with_config:
        print("  2a) Config-bearing: fill CONFIG.md and declare each additional artifact in storage.contract.json, then verify with")
        print("     python %s %s" % (shlex.quote(os.path.join(scripts, "check_config_conformance.py")), shlex.quote(root)))
    print("  2) python %s %s --stage draft" % (shlex.quote(os.path.join(scripts, "check_conformance.py")), shlex.quote(root)))
    print("  3) The generation owner completes README.md + README_CN.md with matching philosophy,")
    print("     prerequisites, usage, outputs and limitations; finish PHILOSOPHY.md, ROADMAP.md,")
    print("     CHANGELOG.md, SKILL.md, public design rationale and applicable CONFIG/reference docs.")
    print("     Follow reference/documentation.md; required current prose cannot remain a placeholder.")
    print("  4) Finish implementation, docs")
    print("     and version metadata BEFORE the candidate snapshot, evidence and independent review.")
    print("  5) Optimize the description on the selection split; run accepted-stage conformance and")
    print("     hand off docs_impact for each affected behavior with the frozen candidate evidence.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
