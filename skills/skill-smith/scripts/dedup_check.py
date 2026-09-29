#!/usr/bin/env python3
"""Cross-library description overlap check (Acceptance Gate G4).

Overlapping skill descriptions cause wrong-skill selection / dilution. This flags pairs of installed
skills whose descriptions are too similar, and (with --desc) checks a candidate against the library
before you create a near-duplicate.

Usage:
  python dedup_check.py [--skills-dir ~/.claude/skills] [--threshold 0.4]
                        [--installed-plugins ~/.claude/plugins/installed_plugins.json]
                        [--desc "candidate description"] [--name candidate-name]
Uses the same active user and plugin inventory as G3. Stale cache copies are not scanned.
Stdlib only. Similarity = Jaccard over content-word sets. Exits 1 if any pair >= threshold,
2 if coverage is incomplete without a known overlap, and 0 only for a complete distinct library.
"""
import argparse
import os
import re
import sys
from budget_check import library_inventory, parse_frontmatter

STOP = set("a an the of to for and or in on with without via your you this that is are be use used "
           "when use-when from into as at by it its their use-cases skill skills claude code agent "
           "user users new create creates creating using".split())


def words(desc):
    toks = re.findall(r"[a-z0-9][a-z0-9-]+", (desc or "").lower())
    return set(t for t in toks if t not in STOP and len(t) > 2)


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / float(len(a | b))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skills-dir", default=os.path.expanduser("~/.claude/skills"))
    ap.add_argument("--installed-plugins",
                    default=os.path.expanduser("~/.claude/plugins/installed_plugins.json"))
    ap.add_argument("--threshold", type=float, default=0.4)
    ap.add_argument("--desc", default="", help="candidate description to compare against library")
    ap.add_argument("--name", default="<candidate>")
    a = ap.parse_args()

    base = os.path.abspath(os.path.expanduser(a.skills_dir))
    rows, problems = library_inventory(base, os.path.expanduser("~/CodesClaude"),
                                      os.path.abspath(os.path.expanduser(a.installed_plugins)))
    items = [("%s:%s" % (row.owner, row.name) if row.owner else row.name, words(row.desc))
             for row in rows]
    if problems:
        print("INCOMPLETE library coverage:")
        for problem in problems:
            print("  %s" % problem)

    flagged = 0

    if a.desc:
        cand = words(a.desc)
        print("Candidate '%s' vs library (threshold %.2f):" % (a.name, a.threshold))
        sims = sorted(((jaccard(cand, w), nm) for nm, w in items), reverse=True)
        flagged = sum(s >= a.threshold for s, _nm in sims)
        for s, nm in sims[:8]:
            mark = "  <== OVERLAP" if s >= a.threshold else ""
            print("  %.2f  %s%s" % (s, nm, mark))
        print("-" * 50)
        if flagged:
            print("RESULT: %d overlap(s) >= %.2f -> consider improving the existing skill "
                  "(self-evolve) instead of creating a duplicate." % (flagged, a.threshold))
        elif not problems:
            print("RESULT: distinct enough. OK to create.")
    else:
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
        elif not problems:
            print("RESULT: no overlaps >= threshold. OK.")
    state = "FAIL" if flagged else ("UNKNOWN" if problems else "OK")
    if problems:
        print("RESULT: coverage incomplete; overlap results cover only the measured skills.")
    print("DEDUP: %s skills=%d overlaps=%d unresolved=%d"
          % (state, len(items), flagged, len(problems)))
    return {"FAIL": 1, "UNKNOWN": 2, "OK": 0}[state]


if __name__ == "__main__":
    sys.exit(main())
