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
Apply requires PyYAML to validate the complete replacement frontmatter before writing.
"""
import argparse
import hashlib
import glob
import json
import os
import re
import sys
import shutil
import datetime
import importlib.util
import uuid
from budget_check import frontmatter_end, parse_frontmatter


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
    """Return the description's line span and the loader's decoded string metadata."""
    name, desc = parse_frontmatter("---\n" + "\n".join(lines) + "\n---\n")
    for index, line in enumerate(lines):
        if re.match(r"^description:\s*", line):
            end = index + 1
            while (end < len(lines) and lines[end].startswith((" ", "\t"))
                   and not re.match(r"^\s*\w[\w-]*:\s", lines[end])):
                end += 1
            return index, end, name, desc
    return None, None, name, desc


def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read().lstrip("﻿")  # tolerate UTF-8 BOM


def yaml_scalar(s):
    """JSON quoting is a YAML-compatible string scalar, including escaped newlines."""
    return json.dumps(s, ensure_ascii=True)


def validate_replacement(text, name, description):
    """Require both valid YAML and the loader's exact metadata round trip."""
    try:
        import yaml
    except ImportError as exc:
        raise ValueError("PyYAML is required to validate replacement frontmatter") from exc
    lines = text.split("\n")
    try:
        end = frontmatter_end(lines)
        metadata = yaml.safe_load("\n".join(lines[1:end]) + "\n")
    except (StopIteration, yaml.YAMLError) as exc:
        raise ValueError("Replacement frontmatter is malformed") from exc
    if (not isinstance(metadata, dict) or metadata.get("description") != description
            or metadata.get("name") != name or parse_frontmatter(text) != (name, description)):
        raise ValueError("Replacement frontmatter did not preserve string metadata")


def do_scan(base, cap, out_path):
    out_path = _storage_path(out_path)
    rows = []
    for p in find_skill_mds(base):
        txt = read_text(p)
        if not txt.startswith("---"):
            continue
        lines = txt.split("\n")
        try:
            c = frontmatter_end(lines)
        except StopIteration:
            continue
        ds, de, name, desc = parse_desc(lines[1:c])
        if desc is None or len(desc) <= cap:
            continue
        rows.append({"path": p, "name": name or os.path.basename(os.path.dirname(p)),
                     "cap": cap, "old": desc, "old_len": len(desc), "new": ""})
    rows.sort(key=lambda r: -r["old_len"])
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    _storage_module().reject_output_aliases(out_path)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print("scan: %d skills over cap %d -> %s" % (len(rows), cap, out_path))
    print("total over-cap description chars: %d" % sum(r["old_len"] for r in rows))
    return 0


def do_apply(worklist_path, dry_run, backup_dir):
    worklist_path = _storage_path(worklist_path)
    if not dry_run:
        backup_dir = _storage_path(backup_dir, directory=True)
    with open(worklist_path, "r", encoding="utf-8") as f:
        rows = json.load(f)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = None if dry_run else os.path.join(backup_dir, "desc-trim-%s-%s" % (stamp, uuid.uuid4().hex))
    applied = skipped = 0
    pending = []
    backup_paths = set()
    for r in rows:
        new = r.get("new")
        if new is None or new == "":
            continue
        if not isinstance(new, str):
            raise ValueError("Reviewed description must be a string")
        if not new.strip():
            continue
        p = r["path"]
        if not os.path.isfile(p):
            print("  SKIP (missing): %s" % p)
            skipped += 1
            continue
        txt = read_text(p)
        if parse_frontmatter(txt)[1] is None:
            raise ValueError("Current frontmatter has missing or malformed metadata")
        lines = txt.split("\n")
        try:
            c = frontmatter_end(lines)
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
        new_fm = fm[:ds] + ["description: " + yaml_scalar(new)] + fm[de:]
        new_text = "\n".join([lines[0]] + new_fm + lines[c:])
        validate_replacement(new_text, name, new)
        print("\n* %s  (%d -> %d chars)" % (name or os.path.basename(os.path.dirname(p)), len(cur), len(new)))
        print("  OLD: %s" % cur)
        print("  NEW: %s" % new)
        if dry_run:
            applied += 1
            continue
        identity = os.path.normcase(os.path.abspath(p))
        bdir = os.path.join(backup_root, hashlib.sha256(os.fsencode(identity)).hexdigest() + ".bak")
        if bdir in backup_paths:
            raise ValueError("Duplicate source identity in description worklist")
        backup_paths.add(bdir)
        _storage_module().reject_output_aliases(bdir)
        if os.path.lexists(bdir):
            raise FileExistsError("Description backup destination already exists: " + bdir)
        pending.append((p, bdir, new_text))
    if pending:
        _storage_module().reject_output_aliases(backup_root)
        os.makedirs(backup_root, exist_ok=False)
        # Finish every exclusive backup before changing any source file.
        for p, bdir, _new_text in pending:
            _storage_module().reject_output_aliases(bdir)
            with open(p, "rb") as source, open(bdir, "xb") as backup:
                shutil.copyfileobj(source, backup)
            shutil.copystat(p, bdir)
        for p, _bdir, new_text in pending:
            with open(p, "w", encoding="utf-8", newline="\n") as source:
                source.write(new_text)
            applied += 1
    print("\n%s: %d entr%s %s, %d skipped." % (
        "DRY-RUN" if dry_run else "APPLIED", applied, "y" if applied == 1 else "ies",
        "to apply" if dry_run else "written", skipped))
    if not dry_run and applied:
        print("backups: %s" % backup_root)
    return 0


_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))


def _storage_module():
    """Use the same pinned-resolver and provider checks as the fleet report writer."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fleet_check.py")
    spec = importlib.util.spec_from_file_location("_fleet_storage_for_trim", path)
    if spec is None or spec.loader is None:
        raise ImportError("fleet storage validator is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.HERE = os.path.join(_REPO_ROOT, "skills", "skill-smith", "scripts")
    return module


def _default_out_path():
    """Require initialized companion storage; never fall back to an unmanaged folder."""
    return _storage_module().default_data_path("worklist.json")


def _storage_path(path, directory=False):
    module = _storage_module()
    result, proof = module.resolve_status_path(
        path, module.DEFAULT_VISIBILITY, default_name="description-backups" if directory else "worklist.json",
        directory=directory)
    print("storage: " + proof)
    return result


def main():
    ap = argparse.ArgumentParser(description="Trim over-cap skill descriptions (semantics-preserving).")
    ap.add_argument("--skills-dir", default=os.path.expanduser("~/.claude/skills"))
    ap.add_argument("--cap", type=int, default=170)
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--apply", metavar="WORKLIST.json")
    ap.add_argument("--out", default=None,
                    help="worklist in a verified PRIVATE Git repository; default uses the pinned companion resolver")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--backup-dir", default=os.environ.get("SKILL_SMITH_BACKUP_DIR"),
                    help="verified PRIVATE backup directory; defaults to companion DATA/description-backups")
    a = ap.parse_args()
    base = os.path.abspath(os.path.expanduser(a.skills_dir))
    try:
        if a.scan:
            return do_scan(base, a.cap, a.out)
        if a.apply:
            return do_apply(a.apply, a.dry_run, a.backup_dir)
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        print("trim rejected: %s" % exc, file=sys.stderr)
        return 1
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
