#!/usr/bin/env python3
"""Library system-prompt budget check (Acceptance Gate G3).

Skills inject their `name` + `description` into the system prompt. There is a hard budget
(~15k chars / ~4k tokens of skill metadata); past it, descriptions are SILENTLY TRUNCATED and
those skills become invisible. This sums the metadata across all installed skills so a batch
cannot quietly overflow the set.

Usage:
  python budget_check.py [--skills-dir ~/.claude/skills] [--max-chars 15000]
                         [--extra "candidate description to test-add"]
Stdlib only. Token estimate = chars / 4 (rough). Exits 1 if over budget.
"""
import argparse
import os
import re
import sys
import glob

WARN_RATIO = 0.8


def parse_frontmatter(text):
    """Return (name, description) from a SKILL.md frontmatter block."""
    text = text.lstrip("﻿")  # tolerate a UTF-8 BOM (common from Windows editors)
    if not text.startswith("---"):
        return None, None
    end = text.find("\n---", 3)
    if end == -1:
        return None, None
    block = text[3:end]
    name = desc = None
    lines = block.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^name:\s*(.*)$", line)
        if m:
            name = m.group(1).strip().strip('"\'')
        m = re.match(r"^description:\s*(.*)$", line)
        if m:
            desc = m.group(1).strip().strip('"\'')
            # join folded/continuation lines (indented, no top-level key)
            j = i + 1
            while j < len(lines) and (lines[j].startswith((" ", "\t")) and not re.match(r"^\s*\w[\w-]*:\s", lines[j])):
                desc += " " + lines[j].strip()
                j += 1
            i = j
            continue
        i += 1
    return name, desc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skills-dir", default=os.path.expanduser("~/.claude/skills"))
    ap.add_argument("--max-chars", type=int, default=15000)
    ap.add_argument("--extra", default="", help="a candidate description to hypothetically add")
    a = ap.parse_args()

    base = os.path.abspath(os.path.expanduser(a.skills_dir))
    if not os.path.isdir(base):
        print("skills dir not found: %s" % base)
        return 2

    # find SKILL.md at depth 1 (<skill>/SKILL.md) and depth 2 (plugin/<skill>/SKILL.md).
    # NTFS is case-insensitive, so dedupe by normcase to avoid double-counting the same file.
    raw = glob.glob(os.path.join(base, "*", "SKILL.md")) + glob.glob(os.path.join(base, "*", "*", "SKILL.md"))
    seen, paths = set(), []
    for p in raw:
        k = os.path.normcase(os.path.abspath(p))
        if k not in seen:
            seen.add(k)
            paths.append(p)

    rows = []
    total = 0
    for p in sorted(paths):
        try:
            with open(p, "r", encoding="utf-8") as f:
                txt = f.read()
        except Exception:
            continue
        name, desc = parse_frontmatter(txt)
        if desc is None:
            continue
        cost = len(name or "") + len(desc) + 12  # rough per-skill metadata overhead
        total += cost
        rows.append((name or os.path.basename(os.path.dirname(p)), len(desc), cost))

    rows.sort(key=lambda r: -r[2])
    print("Skill metadata budget  (dir: %s)" % base)
    print("-" * 64)
    print("  %-34s %8s %8s" % ("skill", "desc", "cost"))
    for nm, dlen, cost in rows:
        print("  %-34s %8d %8d" % (nm[:34], dlen, cost))
    print("-" * 64)
    extra = 0
    if a.extra:
        extra = len(a.extra) + 12
        print("  + candidate description                     %8d %8d" % (len(a.extra), extra))
    grand = total + extra
    tokens = grand / 4.0
    print("  %d skills | total %d chars (~%d tokens) | budget %d chars" %
          (len(rows), grand, int(tokens), a.max_chars))
    ratio = grand / float(a.max_chars)
    if grand > a.max_chars:
        print("  STATUS: OVER BUDGET (%.0f%%) -> truncation risk. Prune/merge before adding." % (ratio * 100))
        return 1
    if ratio >= WARN_RATIO:
        print("  STATUS: WARNING (%.0f%% of budget) -> close to truncation." % (ratio * 100))
        return 0
    print("  STATUS: OK (%.0f%% of budget)." % (ratio * 100))
    return 0


if __name__ == "__main__":
    sys.exit(main())
