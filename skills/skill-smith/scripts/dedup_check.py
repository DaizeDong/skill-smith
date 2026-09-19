#!/usr/bin/env python3
"""Cross-library description overlap check (Acceptance Gate G4).

Overlapping skill descriptions cause wrong-skill selection / dilution. This flags pairs of installed
skills whose descriptions are too similar, and (with --desc) checks a candidate against the library
before you create a near-duplicate.

Usage:
  python dedup_check.py [--skills-dir ~/.claude/skills] [--threshold 0.4]
                        [--desc "candidate description"] [--name candidate-name]
Stdlib only. Similarity = Jaccard over content-word sets. Exits 1 if any pair >= threshold.
"""
import argparse
import os
import re
import sys
from skill_smith.catalog import discover
from skill_smith.readers import library_request, load_snapshot, problems as catalog_problems, skill_entries

STOP = set("a an the of to for and or in on with without via your you this that is are be use used "
           "when use-when from into as at by it its their use-cases skill skills claude code agent "
           "user users new create creates creating using".split())


def parse_frontmatter(text):
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
        m = re.match(r"^name:\s*(.*)$", lines[i])
        if m:
            name = m.group(1).strip().strip('"\'')
        m = re.match(r"^description:\s*(.*)$", lines[i])
        if m:
            desc = m.group(1).strip().strip('"\'')
            j = i + 1
            while j < len(lines) and lines[j].startswith((" ", "\t")) and not re.match(r"^\s*\w[\w-]*:\s", lines[j]):
                desc += " " + lines[j].strip()
                j += 1
            i = j
            continue
        i += 1
    return name, desc


def words(desc):
    toks = re.findall(r"[a-z0-9][a-z0-9-]+", (desc or "").lower())
    return set(t for t in toks if t not in STOP and len(t) > 2)


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / float(len(a | b))


def items_from_catalog(snapshot):
    items, seen = [], set()
    for record, entry in skill_entries(snapshot):
        key = (record["registry_key"] or record["source_id"],
               entry.get("relative_path") or entry["resolved_path"])
        if entry["description"] and key not in seen:
            seen.add(key)
            items.append((entry["name"], words(entry["description"])))
    return items


def main(argv=None, snapshot=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--skills-dir", default=os.path.expanduser("~/.claude/skills"))
    ap.add_argument("--code-root", default=os.path.expanduser("~/CodesClaude"),
                    help="approved target root for installed skill junctions")
    ap.add_argument("--threshold", type=float, default=0.4)
    ap.add_argument("--desc", default="", help="candidate description to compare against library")
    ap.add_argument("--name", default="<candidate>")
    ap.add_argument("--catalog-json", help="consume the same snapshot as budget/fleet")
    a = ap.parse_args(argv)

    base = os.path.abspath(os.path.expanduser(a.skills_dir))
    if snapshot is None:
        snapshot = load_snapshot(a.catalog_json) if a.catalog_json else discover(library_request(
            base, code_root=os.path.abspath(os.path.expanduser(a.code_root)), max_depth=2))
    items = items_from_catalog(snapshot)
    problems = catalog_problems(snapshot)
    for problem in problems:
        print("UNRESOLVED: " + problem)
    if not items:
        print("dedup_check: no measurable skills; coverage is incomplete or empty")
        return 2

    flagged = 0

    if a.desc:
        cand = words(a.desc)
        print("Candidate '%s' vs library (threshold %.2f):" % (a.name, a.threshold))
        sims = sorted(((jaccard(cand, w), nm) for nm, w in items), reverse=True)
        for s, nm in sims[:8]:
            mark = "  <== OVERLAP" if s >= a.threshold else ""
            print("  %.2f  %s%s" % (s, nm, mark))
            if s >= a.threshold:
                flagged += 1
        print("-" * 50)
        if flagged:
            print("RESULT: %d overlap(s) >= %.2f -> consider improving the existing skill "
                  "(self-evolve) instead of creating a duplicate." % (flagged, a.threshold))
            return 1
        print("RESULT: distinct enough. OK to create.")
        return 2 if problems else 0

    # pairwise across the library
    print("Pairwise description overlap (threshold %.2f), %d skills:" % (a.threshold, len(items)))
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            s = jaccard(items[i][1], items[j][1])
            if s >= a.threshold:
                flagged += 1
                print("  %.2f  %s  <->  %s" % (s, items[i][0], items[j][0]))
    print("-" * 50)
    if flagged:
        print("RESULT: %d overlapping pair(s) -> dedup/merge or sharpen descriptions." % flagged)
        return 1
    print("RESULT: no overlaps >= threshold. OK.")
    return 2 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
