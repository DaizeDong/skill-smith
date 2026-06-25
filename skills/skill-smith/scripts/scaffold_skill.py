#!/usr/bin/env python3
"""Scaffold a Skill-Repo-Spec-v1-conformant Claude Code skill repo skeleton.

Emits the 7 required files + PHILOSOPHY.md + skills/<name>/SKILL.md, all version-synced to one
value. Stdlib only. See ../reference/scaffold.md. After scaffolding, run check_conformance.py.

Usage:
  python scaffold_skill.py my-skill \
    --tagline "Verb-first, quantified, one line." \
    --description "When to trigger + what it does + scope, one paragraph." \
    --topics "domain-a,domain-b" [--out-dir ~/CodesSelf] [--version 0.1.0] [--force]
"""
import argparse
import json
import os
import sys
import datetime
import re

REQUIRED_BADGES = (
    "[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-orange?style=flat)]"
    "(https://docs.anthropic.com/en/docs/claude-code)\n"
    "[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)\n"
    "[![Languages](https://img.shields.io/badge/Languages-EN%20%2F%20CN-blue?style=flat)](#languages)\n"
    "[![Roadmap](https://img.shields.io/badge/Roadmap-v__VER__-purple?style=flat)](ROADMAP.md)\n"
)

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

## ⭐ Read this first — the design philosophy

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

## ⭐ 先读这里 — 设计理念

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

PHILOSOPHY_TMPL = """# __NAME__ — Design Philosophy

> One test governs every change: **does it fix the framing, or just patch a symptom?**

TODO: state the root-cause design principle(s) of __NAME__. Each principle should give the
patch-vs-root contrast and the concrete decision in this repo that it produced.

## P1 — <principle>
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

DESIGN_BRIEF_TMPL = """# Design Brief — __NAME__

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


def write(path, content, force):
    if os.path.exists(path) and not force:
        print("  SKIP (exists): %s" % path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print("  wrote: %s" % path)


def main():
    ap = argparse.ArgumentParser(description="Scaffold a Spec-v1 Claude Code skill repo.")
    ap.add_argument("name", help="skill / repo name (kebab-case)")
    ap.add_argument("--tagline", default="TODO: one-line, verb-first, quantified tagline.")
    ap.add_argument("--description", default="TODO: when to trigger + what it does + scope, one paragraph.")
    ap.add_argument("--topics", default="", help="comma-separated domain keywords (excl. trailing 'skill')")
    ap.add_argument("--out-dir", default=os.path.expanduser("~/CodesSelf"))
    ap.add_argument("--version", default="0.1.0")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    name = kebab(a.name)
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
        "version": ver,
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

    print("\nDone. Next:")
    print("  1) Fill docs/design-brief.md from a market-intel recon (Step 0).")
    print("  2) python check_conformance.py %s" % root)
    print("  3) Draft SKILL.md body + optimize the description (Step 4), then run the acceptance gate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
