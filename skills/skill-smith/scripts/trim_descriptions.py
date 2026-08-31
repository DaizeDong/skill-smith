#!/usr/bin/env python3
"""Trim skill SKILL.md frontmatter descriptions to a char cap — SEMANTICS-PRESERVING.

Library-maintenance tool for the Acceptance Gate's budget concern (G3): when the installed skill
set exceeds the system-prompt metadata budget, descriptions get silently truncated. This trims them
down without losing trigger intent — but never by blind truncation.

Phases:
  --scan  : find installed skills whose `description` exceeds --cap; write a worklist JSON:
            [{path, name, cap, old, old_len, new: ""}]  (one entry per over-cap skill).
            You (or an LLM) then fill each `new` with a <=cap rewrite that preserves trigger intent.
  --apply : read the (filled) worklist; for each entry with a non-empty `new`, show old->new diff,
            and UNLESS --dry-run: back up the SKILL.md, then replace its description in-place.

Safety: apply NEVER truncates blindly — it writes only the reviewed `new`. Always backs up. If a
file changed since --scan (its current description != worklist `old`), that entry is SKIPPED.
Stdlib only.
"""
import argparse
import glob
import json
import os
import re
import sys
import shutil
import datetime


def find_skill_mds(base):
    raw = glob.glob(os.path.join(base, "*", "SKILL.md")) + glob.glob(os.path.join(base, "*", "*", "SKILL.md"))
    seen, out = set(), []
    for p in raw:
        k = os.path.normcase(os.path.abspath(p))
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def parse_desc(lines):
    """Given frontmatter lines (between the --- fences), return (ds, de, name, desc) where
    ds..de is the line span of the description (de exclusive); None if no description."""
    name = None
    for ln in lines:
        m = re.match(r"^name:\s*(.*)$", ln)
        if m:
            name = m.group(1).strip().strip('"\'')
            break
    ds = de = None
    desc = None
    for i, ln in enumerate(lines):
        m = re.match(r"^description:\s*(.*)$", ln)
        if m:
            ds = i
            desc = m.group(1).strip().strip('"\'')
            j = i + 1
            while j < len(lines) and lines[j].startswith((" ", "\t")) and not re.match(r"^\s*\w[\w-]*:\s", lines[j]):
                desc += " " + lines[j].strip()
                j += 1
            de = j
            break
    return ds, de, name, desc


def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read().lstrip("﻿")  # tolerate UTF-8 BOM


def yaml_scalar(s):
    """Emit a YAML-safe single-line value: quote only when needed."""
    needs = (s != s.strip() or re.search(r":\s", s) or " #" in s
             or (s[:1] in "!&*?|>%@`\"'#-[]{}," if s else False))
    if needs:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def do_scan(base, cap, out_path):
    rows = []
    for p in find_skill_mds(base):
        txt = read_text(p)
        if not txt.startswith("---"):
            continue
        lines = txt.split("\n")
        try:
            c = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
        except StopIteration:
            continue
        ds, de, name, desc = parse_desc(lines[1:c])
        if desc is None or len(desc) <= cap:
            continue
        rows.append({"path": p, "name": name or os.path.basename(os.path.dirname(p)),
                     "cap": cap, "old": desc, "old_len": len(desc), "new": ""})
    rows.sort(key=lambda r: -r["old_len"])
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print("scan: %d skills over cap %d -> %s" % (len(rows), cap, out_path))
    print("total over-cap description chars: %d" % sum(r["old_len"] for r in rows))
    return 0


def do_apply(worklist_path, dry_run, backup_dir):
    with open(worklist_path, "r", encoding="utf-8") as f:
        rows = json.load(f)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = os.path.join(os.path.expanduser(backup_dir), "desc-trim-%s" % stamp)
    applied = skipped = 0
    for r in rows:
        new = (r.get("new") or "").strip()
        if not new:
            continue
        p = r["path"]
        if not os.path.isfile(p):
            print("  SKIP (missing): %s" % p)
            skipped += 1
            continue
        txt = read_text(p)
        lines = txt.split("\n")
        try:
            c = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
        except StopIteration:
            print("  SKIP (no frontmatter): %s" % p)
            skipped += 1
            continue
        fm = lines[1:c]
        ds, de, name, cur = parse_desc(fm)
        if ds is None:
            print("  SKIP (no description): %s" % p)
            skipped += 1
            continue
        if cur != r.get("old"):
            print("  SKIP (changed since scan): %s" % (name or p))
            skipped += 1
            continue
        if len(new) > r.get("cap", 9999):
            print("  WARN over cap (%d>%d), applying anyway: %s" % (len(new), r.get("cap"), name))
        print("\n* %s  (%d -> %d chars)" % (name or os.path.basename(os.path.dirname(p)), len(cur), len(new)))
        print("  OLD: %s" % cur)
        print("  NEW: %s" % new)
        if dry_run:
            applied += 1
            continue
        bdir = os.path.join(backup_root, re.sub(r"[:\\/]+", "_", p))
        os.makedirs(os.path.dirname(bdir), exist_ok=True)
        shutil.copy2(p, bdir)
        new_fm = fm[:ds] + ["description: " + yaml_scalar(new)] + fm[de:]
        new_lines = [lines[0]] + new_fm + lines[c:]
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(new_lines))
        applied += 1
    print("\n%s: %d entr%s %s, %d skipped." % (
        "DRY-RUN" if dry_run else "APPLIED", applied, "y" if applied == 1 else "ies",
        "to apply" if dry_run else "written", skipped))
    if not dry_run and applied:
        print("backups: %s" % backup_root)
    return 0


_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))


def _companion_root():
    """Where this skill's private companion is, via tools/datadir.py. None when there is none."""
    p = os.path.join(_REPO_ROOT, "tools", "datadir.py")
    if not os.path.isfile(p):
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location("_dd_for_trim", p)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fn = getattr(mod, "resolve_companion_root", None)
    return fn("skill-smith") if fn else None


def _default_out_path():
    """The default worklist destination, which must not be inside this public repo.

    `--out` used to default to the bare relative name `worklist.json`, written from the current
    directory, which is the repo root whenever anyone runs this the obvious way. The file is not a
    scratch artifact: every row carries an ABSOLUTE on-disk path, so it contains the operator's
    username, and the live `description` of every over-cap SKILL.md under ~/.claude/skills, which
    includes skills that are not in any public repository. It was neither tracked nor gitignored, so
    one `git add -A` after a scan would have committed it.

    That is real-run output about a person's machine, and this repo is the template every other
    skill is scaffolded from, so the defect propagated by construction.
    """
    root = _companion_root()
    if root is not None:
        return os.path.join(str(root), "data", "worklist.json")
    return os.path.expanduser(os.path.join("~", ".skill-smith", "worklist.json"))


def _reject_in_repo(path):
    """A worklist inside this repo is refused, whatever route produced the path.

    Covers the default, an explicit --out, and a relative path resolved against a current directory
    that happens to be the repo. One check instead of three, and it raises rather than silently
    relocating: a tool that writes somewhere other than where it was told is a worse surprise than
    one that stops and says why.
    """
    p = os.path.abspath(os.path.expanduser(path))
    if os.path.commonpath([p, _REPO_ROOT]) == _REPO_ROOT:
        raise SystemExit(
            "trim_descriptions: refusing to write the worklist inside this public repo:\n"
            "  %s\n"
            "Every row carries an absolute on-disk path and the live description of skills that may\n"
            "not be public. Pass --out with a path outside this repo, or leave it unset to use\n"
            "  %s" % (p, _default_out_path()))
    return p


def main():
    ap = argparse.ArgumentParser(description="Trim over-cap skill descriptions (semantics-preserving).")
    ap.add_argument("--skills-dir", default=os.path.expanduser("~/.claude/skills"))
    ap.add_argument("--cap", type=int, default=170)
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--apply", metavar="WORKLIST.json")
    ap.add_argument("--out", default=None,
                    help="where to write the scan worklist. Defaults OUTSIDE this repo; see "
                         "_default_out_path for why a bare relative name was wrong.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--backup-dir", default=os.environ.get("SKILL_SMITH_BACKUP_DIR", "~/.skill-smith/backup"))
    a = ap.parse_args()
    base = os.path.abspath(os.path.expanduser(a.skills_dir))
    if a.scan:
        out = _reject_in_repo(a.out if a.out else _default_out_path())
        os.makedirs(os.path.dirname(out), exist_ok=True)
        return do_scan(base, a.cap, out)
    if a.apply:
        return do_apply(a.apply, a.dry_run, a.backup_dir)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
