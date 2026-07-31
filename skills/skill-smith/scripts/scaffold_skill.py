#!/usr/bin/env python3
"""Scaffold a Skill-Repo-Spec-v1-conformant Claude Code skill repo skeleton.

Emits the 7 required files + PHILOSOPHY.md + skills/<name>/SKILL.md, all version-synced to one
value. Stdlib only. See ../reference/scaffold.md. After scaffolding, run check_conformance.py.

Usage:
  python scaffold_skill.py my-skill \
    --tagline "Verb-first, quantified, one line." \
    --description "When to trigger + what it does + scope, one paragraph." \
    --topics "domain-a,domain-b" [--out-dir ~/CodesClaude] [--version 0.1.0] [--force]
    [--with-config]   # also emit the config-bearing standard (config-spec E1-E7)
"""
import argparse
import json
import os
import shutil
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

## ⭐ Read this first, the design philosophy

<!-- One screen: WHY it is designed this way. Root-cause, not features. Link PHILOSOPHY.md. -->
TODO: state the single governing principle of __NAME__, then link PHILOSOPHY.md.

\U0001f4dc **[Read the full design philosophy -> PHILOSOPHY.md](PHILOSOPHY.md)**

---

## What it is (and isn't)

TODO: define scope and boundary.

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

## Roadmap · Contributing · License

See [ROADMAP.md](ROADMAP.md) · [CONTRIBUTING.md](CONTRIBUTING.md) · [LICENSE](LICENSE) (MIT).
"""

README_CN_TMPL = """# __NAME__

__TAGLINE__

__BADGES_CN__
[English](README.md) | [中文版](README_CN.md)

---

## ⭐ 先读这里, 设计理念

<!-- 一屏说清"为什么这样设计"。改根因,不堆功能。链 PHILOSOPHY.md。 -->
TODO: 写清 __NAME__ 的唯一统领原则,然后链 PHILOSOPHY.md。

\U0001f4dc **[完整设计理念 -> PHILOSOPHY.md](PHILOSOPHY.md)**

---

## 它是什么(不是什么)

TODO: 定位与边界。

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

## Roadmap · 贡献 · 许可

见 [ROADMAP.md](ROADMAP.md) · [CONTRIBUTING.md](CONTRIBUTING.md) · [LICENSE](LICENSE)(MIT)。
"""

PHILOSOPHY_TMPL = """# __NAME__, Design Philosophy

> One test governs every change: **does it fix the framing, or just patch a symptom?**

TODO: state the root-cause design principle(s) of __NAME__. Each principle should give the
patch-vs-root contrast and the concrete decision in this repo that it produced.

## P1, <principle>
- **Symptom patch:** ...
- **Root cause:** ...
- **Decision it produced:** ...
"""

ROADMAP_TMPL = """# Roadmap

Current: **v__VER__**

## v__VER__ (current)
- Initial release.

## Planned
- TODO.
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

DESIGN_BRIEF_TMPL = """# Design Brief, __NAME__

> Produced by skill-smith Step 0 (research-first). The design rationale, auditable.

## Best references (match-or-beat)
- TODO (from market-intel recon)

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
    return re.sub(r"[^a-z0-9-]+", "-", s.strip().lower()).strip("-")


ASSETS_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "config")


def _read_asset(rel):
    with open(os.path.join(ASSETS_CONFIG, rel), "r", encoding="utf-8") as f:
        return f.read()


def emit_config_bearing(root, name, force, write_fn):
    """Emit the config-bearing standard (config-spec E1-E7) into the new skill repo.

    - scripts/init_config.py + verify_config.py (verbatim generic tools; auto-detect skill)
    - CONFIG.md (schema + mount + first-time + switch)
    - README.md / README_CN.md '## Config' section appended
    - .gitignore with the secrets gate (E6)
    """
    env = name.upper().replace("-", "_") + "_CONFIG"
    defaultdir = ".%s-config" % name

    def fill(t):
        return (t.replace("__NAME__", name)
                 .replace("__ENVVAR__", env)
                 .replace("__DEFAULTDIR__", defaultdir))

    # generic scripts copied verbatim (they self-detect the skill from plugin.json)
    write_fn(os.path.join(root, "scripts", "init_config.py"), _read_asset("init_config.py"), force)
    write_fn(os.path.join(root, "scripts", "verify_config.py"), _read_asset("verify_config.py"), force)
    # authoritative config doc + secrets gitignore
    write_fn(os.path.join(root, "CONFIG.md"), fill(_read_asset("CONFIG.md.tmpl")), force)
    write_fn(os.path.join(root, ".gitignore"), _read_asset("skill-gitignore.tmpl"), force)
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
    "DATA    = anything a REAL RUN produced. Never git-tracked. Lives in the private companion",
    "          config, resolved at runtime by tools/datadir.py. This repo ships only the schema.",
    "",
    "Declare DATA paths here BEFORE the skill has anything to write, not after. A skill that",
    "appends real-run output to a git-tracked file will do it on every run, quietly, forever --",
    "that is how a public repo came to hold real-run output from the operator's own account, and no",
    "content scanner can see it (a ticker with an entry price has no email or phone in it).",
    "",
    "data_sealed = a path that HELD real data, was purged, and must stay dead. Checked like data,",
    "exempt from the .example schema requirement."
  ],
  "data": [],
  "data_sealed": [],
  "fixture": [],
  "_data_home": "~/.%(name)s-config/data/   (override with $%(env)s)"
}
"""


def emit_pii_guard(root, force, name):
    """Spec v1 sections 8 + 9: every public repo is born with BOTH gates already in it.

    Section 8 (pii_guard) is the backstop: it reads what you are about to publish and looks for
    things that smell private. The 2026-07 audit found a phone number, a home ZIP, an employer and a health-provider name in five public skill repos, because the agent writing them was looking at the
    operator's real life for its examples and nothing forced a translation step.

    Section 9 (data_boundary) is the PRIMARY control, and it exists because the same audit found
    something the scanner could never have caught: real-run output from a private account -- verdicts, purchases, and a research log -- none of it pasted in by anyone. The
    SKILLS WROTE IT THERE, on every real run, by design. A ticker with an entry price contains no
    email, no phone, no ZIP; there is nothing to smell. So the repo ships as an UNINITIALIZED TOOL:
    real-run output resolves to a private store, and an agent writing this repo has nothing real
    within reach to copy.

    A repo that starts without these accumulates the debt before anyone thinks to add them, and by
    then the fix is no longer an edit -- it is a history rewrite and a force-push.
    """
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "assets", "pii-guard")
    if not os.path.isdir(src):
        print("  WARN: assets/pii-guard missing; skipping the gates (Spec v1 s8+s9 REQUIRE them)")
        return
    print("PII gate + data boundary (Spec v1 sections 8 + 9):")
    pairs = [("pii_guard.py", os.path.join("tools", "pii_guard.py")),
             ("test_pii_guard.py", os.path.join("tools", "test_pii_guard.py")),
             ("data_boundary.py", os.path.join("tools", "data_boundary.py")),
             ("datadir.py", os.path.join("tools", "datadir.py")),
             (os.path.join("hooks", "pre-commit"), os.path.join(".githooks", "pre-commit")),
             (os.path.join("hooks", "pre-push"), os.path.join(".githooks", "pre-push")),
             (os.path.join("workflow", "pii-guard.yml"),
              os.path.join(".github", "workflows", "pii-guard.yml")),
             ("pii-allow.tmpl", ".pii-allow")]
    for rel_src, rel_dst in pairs:
        dst = os.path.join(root, rel_dst)
        if os.path.exists(dst) and not force:
            print("  SKIP (exists): %s" % dst)
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(src, rel_src), dst)
        print("  wrote: %s" % dst)

    dc = os.path.join(root, ".dataclass.json")
    if os.path.exists(dc) and not force:
        print("  SKIP (exists): %s" % dc)
    else:
        with open(dc, "w", encoding="utf-8", newline="\n") as f:
            f.write(DATACLASS_TMPL % {"name": name,
                                      "env": name.upper().replace("-", "_") + "_DATA_DIR"})
        print("  wrote: %s" % dc)


def emit_dash_guard(root, force):
    """Vendor the dash gate (Spec v1 section 10): the house rule that published prose carries no
    en/em dash. tools/dash_guard.py de-dashes Markdown and Python COMMENTS only (string literals,
    docstrings and data, are left alone so a functional literal is never corrupted), and the CI
    workflow fails a push whose prose still carries a dash. The ASCII hyphen is never touched.

    Runtime output compliance is the renderer's job, not this gate's: any skill that renders an
    LLM-supplied field into user-facing output should normalize en/em/bar dashes to a comma in its
    _inline helper (write the dash set as backslash-u escapes so the source stays dash-free)."""
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "assets", "dash-guard")
    if not os.path.isdir(src):
        print("  WARN: assets/dash-guard missing; skipping the dash gate (Spec v1 s10)")
        return
    print("Dash gate (Spec v1 section 10):")
    pairs = [("dash_guard.py", os.path.join("tools", "dash_guard.py")),
             (os.path.join("workflow", "dash-guard.yml"),
              os.path.join(".github", "workflows", "dash-guard.yml"))]
    for rel_src, rel_dst in pairs:
        dst = os.path.join(root, rel_dst)
        if os.path.exists(dst) and not force:
            print("  SKIP (exists): %s" % dst)
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(src, rel_src), dst)
        print("  wrote: %s" % dst)


def main():
    ap = argparse.ArgumentParser(description="Scaffold a Spec-v1 Claude Code skill repo.")
    ap.add_argument("name", help="skill / repo name (kebab-case)")
    ap.add_argument("--tagline", default="TODO: one-line, verb-first, quantified tagline.")
    ap.add_argument("--description", default="TODO: when to trigger + what it does + scope, one paragraph.")
    ap.add_argument("--topics", default="", help="comma-separated domain keywords (excl. trailing 'skill')")
    ap.add_argument("--out-dir", default=os.path.expanduser("~/CodesClaude"))
    ap.add_argument("--version", default="0.1.0")
    ap.add_argument("--with-config", action="store_true",
                    help="emit the config-bearing standard (config-spec E1-E7): CONFIG.md, "
                         "init/verify scripts, README Config section, secrets .gitignore")
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

    print("Scaffolding %s (v%s) at %s" % (name, ver, root))
    write(os.path.join(root, "README.md"), sub(README_TMPL), a.force)
    write(os.path.join(root, "README_CN.md"), sub(README_CN_TMPL), a.force)
    write(os.path.join(root, "LICENSE"), sub(LICENSE_TMPL), a.force)
    write(os.path.join(root, "PHILOSOPHY.md"), sub(PHILOSOPHY_TMPL), a.force)
    write(os.path.join(root, "ROADMAP.md"), sub(ROADMAP_TMPL), a.force)
    write(os.path.join(root, "CHANGELOG.md"), sub(CHANGELOG_TMPL), a.force)
    write(os.path.join(root, ".claude-plugin", "plugin.json"),
          json.dumps(plugin, indent=2, ensure_ascii=False) + "\n", a.force)
    write(os.path.join(root, "skills", name, "SKILL.md"), sub(SKILL_TMPL), a.force)
    write(os.path.join(root, "docs", "design-brief.md"), sub(DESIGN_BRIEF_TMPL), a.force)
    # progressive-loading dir for the new skill
    write(os.path.join(root, "skills", name, "reference", ".gitkeep"), "", a.force)

    emit_pii_guard(root, a.force, a.name)
    emit_dash_guard(root, a.force)

    if a.with_config:
        print("Config-bearing standard (config-spec E1-E7):")
        emit_config_bearing(root, name, a.force, write)

    print("\nDone. Next:")
    print("  0) PII gate: git init, then `git config core.hooksPath .githooks` (local config cannot")
    print("     be committed, so every clone must run it; CI does not depend on it).")
    print("     Commit identity MUST be the GitHub noreply address -- a real mailbox on the author")
    print("     line is the one leak no file scan will ever see (Spec v1 s8).")
    if a.with_config:
        print("  0b) Config-bearing: fill CONFIG.md schema, then verify with")
        print("     python skills/skill-smith/scripts/check_config_conformance.py %s" % root)
    print("  1) Fill docs/design-brief.md from a market-intel recon (Step 0).")
    print("  2) python check_conformance.py %s" % root)
    print("  3) Draft SKILL.md body + optimize the description (Step 4), then run the acceptance gate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
