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
    "How to fill it: run the skill for real, take the listing of what it wrote (from OUTSIDE this",
    "repo, where that output lives), and score the names with",
    "    python tools/data_boundary.py --explain <name> <name> ...",
    "Then rewrite each name into its SCHEMATIC form and commit that. A probe carrying a real",
    "ticker, mailbox handle, channel id or counterparty name is private data in a public repo even",
    "with no file behind it, which would reintroduce the leak under the banner of preventing it.",
    "A probe that matches no shape is reported by name: that is a gap in the shared list, not a",
    "reason to delete the probe."
  ],
  "_data_home": "~/.%(name)s-config/data/   (override with $%(env)s)"
}
"""


GUARDS_URL = "https://github.com/DaizeDong/fleet-guards.git"

# The consumer's whole CI file. Checkout, python, and one `uses:` line pointing into the
# submodule, where the steps and the reasoning for them live in a single copy.
WORKFLOW_TMPL = {
    'pii-guard.yml': "# pii_guard in CI -- the authority.\n#\n# The local hooks are a fast fail, not a guarantee. On 2026-07-13 a pre-commit hook printed its\n# findings and let the commit through anyway, because the caller had piped `git commit` into `head`\n# and the severed pipe destroyed the guard's exit status. A local hook can also be skipped with\n# --no-verify, is not installed on a fresh clone until someone opts in, and does not exist at all\n# for an outside contributor.\n#\n# This runs on GitHub, on every push and every PR, and it cannot be reached by any of that.\n#\n# The steps live in the guards submodule (guards/ci/pii-guard/action.yml) so there is ONE copy of\n# them across the fleet rather than one per repo, which had already begun to drift. This file is\n# only the wiring; the action carries the reasoning for each step.\n#\n# It runs WITHOUT the operator's private denylist (that file never leaves their machine). That is\n# the point of the allowlist design: the structural checks need no private data, so they work here.\nname: pii-guard\n\non:\n  push:\n  pull_request:\n\njobs:\n  scan:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n        with:\n          submodules: true\n          fetch-depth: 0        # the history scan is the point; a shallow clone would see nothing\n      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.x'\n      - uses: ./guards/ci/pii-guard\n",
    'dash-guard.yml': "# dash-guard in CI: the house rule that published prose carries no en/em dash (the ASCII hyphen is\n# code syntax and is left alone). Style, not security, so it scans the current tree only.\n#\n# The steps live in guards/ci/dash-guard/action.yml, one copy for the whole fleet.\nname: dash-guard\n\non:\n  push:\n  pull_request:\n\njobs:\n  scan:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n        with:\n          submodules: true\n      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.x'\n      - uses: ./guards/ci/dash-guard\n",
    'load-budget.yml': "# load-budget in CI: PHILOSOPHY P7, the always-loaded budget and the no-second-copy rule.\n#\n# The steps live in guards/ci/load-budget/action.yml, one copy for the whole fleet.\nname: load-budget\n\non:\n  push:\n  pull_request:\n\njobs:\n  budget:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n        with:\n          submodules: true\n      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.x'\n      - uses: ./guards/ci/load-budget\n",
}

# Starts EMPTY on purpose. An exemption file shipped with entries in it is an off switch
# somebody else flipped, in a repo nobody has looked at yet.
PII_ALLOW_TMPL = """# One exemption per line, each with a comment saying why it is not real.
# A bare common word is not an exemption, it is an off switch for a whole class,
# written inside the repo it is supposed to protect.
"""

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

    THE KIT IS A SUBMODULE, NOT A COPY. This function used to write eleven files into the new repo.
    That produced one identical copy of the kit per repo, with nothing keeping them in step, and
    they drifted: one repo's copy fell behind the source while its CI ran the stale one and
    reported green. A scaffolder that emits copies does not create twenty guarded repos, it creates
    twenty divergent forks of a guard.

    A repo that starts without these accumulates the debt before anyone thinks to add them, and by
    then the fix is no longer an edit, it is a history rewrite and a force-push.
    """
    print("Guards (Spec v1 sections 8 + 9 + 10):")
    # git init FIRST. A submodule needs a repo to live in, and so do the hooks; before this
    # the scaffolder only copied files, which worked in a bare directory and left the gates
    # looking installed in something git had never heard of. Idempotent: git init on an
    # existing repo is a no-op that does not touch the index.
    if not os.path.isdir(os.path.join(root, ".git")):
        r = subprocess.run(["git", "init", "-q"], cwd=root, capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit("git init failed in {0}: {1}".format(root, r.stderr.strip()))
        print("  git init")
    guards = os.path.join(root, "guards")
    # No `and not force` here, unlike every other write below. --force overwrites FILES; a
    # submodule that is already present is already the desired state, and `git submodule add`
    # on an existing path fails rather than refreshing it. To move the pin, advance it in the
    # submodule and commit the new pointer; re-scaffolding is not the tool for that.
    if os.path.isdir(guards):
        print("  SKIP (exists): %s" % guards)
    else:
        r = subprocess.run(["git", "submodule", "add", "-b", "main", GUARDS_URL, "guards"],
                           cwd=root, capture_output=True, text=True)
        if r.returncode != 0:
            # Loud, not a warning. A repo scaffolded without the gates is the exact state section 8
            # exists to prevent, and printing WARN next to twenty lines of progress is how it gets
            # missed. The caller decides what to do; it must not be told this succeeded.
            raise SystemExit(
                "FAILED to add the guards submodule to {0}:{2}{1}{2}"
                "The repo is NOT guarded. Fix the clone (network, credentials, the URL "
                "above) and re-run; do not proceed and do not copy the kit in by hand."
                .format(root, r.stderr.strip(), chr(10)))
        print("  added submodule: guards -> %s" % GUARDS_URL)

    # Hooks come from the submodule. This is repo-local git config, so it is not committed and a
    # fresh clone does not inherit it; that is why CI, which cannot be opted out of, is the
    # authority and the hooks are only a fast fail.
    subprocess.run(["git", "config", "core.hooksPath", "guards/hooks"], cwd=root, check=False)
    print("  hooks: core.hooksPath = guards/hooks")

    for wf, body in WORKFLOW_TMPL.items():
        dst = os.path.join(root, ".github", "workflows", wf)
        if os.path.exists(dst) and not force:
            print("  SKIP (exists): %s" % dst)
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", encoding="utf-8", newline=chr(10)) as f:
            f.write(body)
        print("  wrote: %s" % dst)

    # .pii-allow and .dataclass.json are NOT in the submodule and never will be. Which paths are
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

    emit_guards(root, a.force, a.name)

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
