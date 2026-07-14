#!/usr/bin/env python3
"""Skill Repo Spec v1 linter. Checks a skill repo dir for conformance.

Usage:  python check_conformance.py <repo_dir>
Exits 0 if all checks pass, 1 otherwise. Stdlib only. (Skill Repo Spec v1.)
"""
import json
import os
import subprocess
import re
import sys

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))


def read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def main(root):
    root = os.path.abspath(os.path.expanduser(root))
    name = os.path.basename(root)

    # 1) required files
    required = ["README.md", "README_CN.md", "LICENSE",
                os.path.join(".claude-plugin", "plugin.json"), "ROADMAP.md", "CHANGELOG.md"]
    for rel in required:
        check("file: %s" % rel, os.path.isfile(os.path.join(root, rel)))

    # 1b) the PII gate (Spec v1 section 8) -- REQUIRED, not a later hardening pass.
    # The 2026-07 audit found real private data (a phone, a home ZIP, an employer, a health-provider name, an email address on ~every commit) in five public skill repos. By the time anyone
    # noticed, the fix was no longer an edit: it was a history rewrite and a force-push on each one.
    # A repo without the gate is a repo accumulating that debt right now.
    for rel in ["tools/pii_guard.py", "tools/test_pii_guard.py",
                ".githooks/pre-commit", ".githooks/pre-push",
                ".github/workflows/pii-guard.yml", ".pii-allow"]:
        check("PII gate: %s" % rel, os.path.isfile(os.path.join(root, *rel.split("/"))))
    # The gate must actually be clean -- shipping it red is worse than not having it, because the
    # green checkbox above then means nothing.
    guard = os.path.join(root, "tools", "pii_guard.py")
    if os.path.isfile(guard):
        p = subprocess.run([sys.executable, guard, "--tree", "--history"],
                           cwd=root, capture_output=True, text=True)
        check("PII gate: scan is clean (tree + history)", p.returncode == 0,
              (p.stderr or "").strip().splitlines()[0] if p.returncode else "")

    # 1c) the DATA BOUNDARY (Spec v1 section 9) -- the PRIMARY control; the scan above is a backstop.
    #
    # The same audit found what no scanner could: real-run output from the operator's own account, their
    # private activity -- in public repos, written there by
    # the SKILLS THEMSELVES on every real run. A ticker with an entry price has no email in it, no
    # phone, no ZIP. Nothing to smell. pii_guard was green the whole time.
    #
    # So a conformant repo declares every path as TOOL / FIXTURE / DATA and ships as an UNINITIALIZED
    # TOOL: real-run output resolves to a private store, and an agent writing this repo has nothing
    # real within reach to copy.
    for rel in ["tools/data_boundary.py", "tools/datadir.py", ".dataclass.json"]:
        check("data boundary: %s" % rel, os.path.isfile(os.path.join(root, *rel.split("/"))))
    boundary = os.path.join(root, "tools", "data_boundary.py")
    if os.path.isfile(boundary):
        p = subprocess.run([sys.executable, boundary], cwd=root, capture_output=True, text=True)
        check("data boundary: repo is an uninitialized tool", p.returncode == 0,
              (p.stderr or "").strip().splitlines()[0] if p.returncode else "")

    # at least one skills/*/SKILL.md
    skill_mds = []
    skills_dir = os.path.join(root, "skills")
    if os.path.isdir(skills_dir):
        for d in os.listdir(skills_dir):
            p = os.path.join(skills_dir, d, "SKILL.md")
            if os.path.isfile(p):
                skill_mds.append(p)
    # root-skill style fallback
    if os.path.isfile(os.path.join(root, "SKILL.md")):
        skill_mds.append(os.path.join(root, "SKILL.md"))
    check("skills/*/SKILL.md present", len(skill_mds) > 0, "%d found" % len(skill_mds))

    # 2) plugin.json fingerprint
    pj_raw = read(os.path.join(root, ".claude-plugin", "plugin.json"))
    pj_ver = None
    if pj_raw:
        try:
            pj = json.loads(pj_raw)
            check("plugin.author.name == DaizeDong", pj.get("author", {}).get("name") == "DaizeDong")
            check("plugin.license == MIT", pj.get("license") == "MIT")
            check("plugin.homepage pattern",
                  pj.get("homepage") == "https://github.com/DaizeDong/%s" % pj.get("name", ""),
                  pj.get("homepage", ""))
            kw = pj.get("keywords", [])
            check("plugin.keywords end with 'skill'", bool(kw) and kw[-1] == "skill", str(kw[-3:]))
            check("plugin.name kebab-case", bool(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", pj.get("name", ""))),
                  pj.get("name", ""))
            pj_ver = pj.get("version")
        except Exception as e:
            check("plugin.json valid JSON", False, str(e))
    else:
        check("plugin.json readable", False)

    # 3) version four-source sync
    readme = read(os.path.join(root, "README.md")) or ""
    readme_cn = read(os.path.join(root, "README_CN.md")) or ""
    roadmap = read(os.path.join(root, "ROADMAP.md")) or ""
    changelog = read(os.path.join(root, "CHANGELOG.md")) or ""

    def grab(pat, text):
        m = re.search(pat, text)
        return m.group(1) if m else None

    v_readme = grab(r"Roadmap-v([0-9]+\.[0-9]+\.[0-9]+)-purple", readme)
    v_readme_cn = grab(r"Roadmap-v([0-9]+\.[0-9]+\.[0-9]+)-purple", readme_cn)
    v_roadmap = grab(r"Current:\s*\*\*v([0-9]+\.[0-9]+\.[0-9]+)\*\*", roadmap)
    v_changelog = grab(r"##\s*\[([0-9]+\.[0-9]+\.[0-9]+)\]", changelog)
    versions = {"plugin": pj_ver, "README": v_readme, "README_CN": v_readme_cn,
                "ROADMAP": v_roadmap, "CHANGELOG": v_changelog}
    uniq = set(v for v in versions.values() if v)
    check("version four-source synced", len(uniq) == 1 and all(versions.values()), str(versions))

    # 4) README philosophy-first + badge block
    check("README badge: Claude Code Skill (orange)",
          "Claude%20Code-Skill-orange" in readme)
    check("README badge: License MIT (blue)", "License-MIT-blue" in readme)
    check("README badge: Languages (blue)", "Languages-EN%20%2F%20CN-blue" in readme)
    check("README badge: Roadmap (purple)", "Roadmap-v" in readme and "-purple" in readme)
    i_phil = readme.find("## ⭐ Read this first")
    i_inst = readme.find("## Install")
    check("README philosophy-first (before Install)",
          i_phil != -1 and (i_inst == -1 or i_phil < i_inst),
          "phil@%d install@%d" % (i_phil, i_inst))
    check("README bilingual switch line", "[English](README.md)" in readme and "README_CN.md" in readme)
    check("README_CN philosophy-first", "## ⭐" in readme_cn)

    # report
    print("Skill Repo Spec v1 conformance: %s" % root)
    print("-" * 60)
    n_fail = 0
    for nm, ok, detail in results:
        tag = PASS if ok else FAIL
        if not ok:
            n_fail += 1
        line = "  [%s] %s" % (tag, nm)
        if detail and not ok:
            line += "  -> %s" % detail
        print(line)
    print("-" * 60)
    total = len(results)
    print("%d/%d passed%s" % (total - n_fail, total, "" if n_fail == 0 else "  (%d FAIL)" % n_fail))
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python check_conformance.py <repo_dir>")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
