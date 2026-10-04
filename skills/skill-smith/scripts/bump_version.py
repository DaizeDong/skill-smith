#!/usr/bin/env python3
"""Bump the version of a Skill-Repo-Spec-v1 repo at all five sites at once.

WHY THIS EXISTS. scaffold_skill.py stamps the five version sites once, at creation, and
check_conformance.py only READS them. Between those two there was nothing: every release was five
hand edits across five files in the right order, and the cost of forgetting one was invisible until
someone ran the linter. Predictably, most repos ended up drifted, usually as a half-applied
release (plugin.json and CHANGELOG moved, the README badges and ROADMAP did not). A five-file
manual ritual is not a process, it is a pending bug.

The five sites are defined in version_sites.py, shared with the scaffolder and the linter, so
this tool cannot stamp a shape its own linter would reject.

TWO RULES THAT ARE THE POINT OF THE TOOL:

  1. It REFUSES on an already-drifted repo (exit 1) and prints the diff. Bumping over drift would
     "fix" the linter while destroying the evidence of which site was left behind and at what
     version, and the half-applied release would never be understood. Resolve the drift by hand
     first, deliberately, then bump.

  2. It requires completed release prose, valid dates and advancing canonical versions before
     writing. It NEVER commits, tags or pushes; review the planned release within authorization.

Usage:
  python bump_version.py <repo> --level patch|minor|major
  python bump_version.py <repo> --set 1.2.0 [--notes "one line"] [--dry-run]
  python bump_version.py <repo> --level minor --prerelease alpha    # badge reads v0.3.0%20alpha
  python bump_version.py <repo> --level minor --no-prerelease       # drop an existing marker

Stdlib only. Exit 0 on success, 1 on release preflight refusal, 2 on bad CLI usage.
"""
from __future__ import annotations

import argparse
import datetime
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import version_sites as vs  # noqa: E402


def validate_release_version(version):
    """Require canonical numeric semver, without ambiguous leading zeroes."""
    if not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", version):
        raise ValueError("release version must be canonical X.Y.Z: %r" % version)
    return vs.parse_semver(version)


def validate_release_date(value):
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("release date must be YYYY-MM-DD")
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("release date is not a valid calendar date: %s" % value) from exc


def release_body(text, heading):
    end = re.search(r"^##\s", text[heading.end():], re.M)
    return text[heading.end():heading.end() + end.start()] if end else text[heading.end():]


def substantive_notes(text):
    """Reject unfinished target release prose; historical/future sections are not inspected."""
    prose = re.sub(r"<!--.*?-->", "", text or "", flags=re.S)
    prose = re.sub(r"```.*?```", "", prose, flags=re.S)
    lines = [line.strip() for line in prose.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if any(unfinished_note(line) for line in lines):
        return False
    return any(len(re.sub(r"[^\w]", "", line)) >= 12 for line in lines)


def unfinished_note(line):
    return bool(re.search(r"^\s*(?:[-*+]\s+)?(?:TODO|TBD|FIXME|placeholder)\b|<\s*(?:fill|insert)[^>]*>", line, re.I))


def release_notes(text, notes):
    """Use completed Unreleased notes, or supplied notes when the staging body is unfinished."""
    headings = list(vs.RE_CHANGELOG_UNRELEASED.finditer(text))
    if len(headings) > 1:
        raise ValueError("CHANGELOG.md: multiple Unreleased sections; reconcile before releasing")
    heading = headings[0] if headings else None
    body = release_body(text, heading) if heading else ""
    if substantive_notes(body):
        return body
    if substantive_notes(notes):
        remaining = re.sub(r"<!--.*?-->", "", body, flags=re.S)
        remaining = "\n".join(line for line in remaining.splitlines()
                              if not unfinished_note(line))
        if substantive_notes(remaining):
            raise ValueError("finish the partially completed Unreleased body; --notes cannot discard existing changes")
        return "### Changed\n- %s\n" % notes.strip()
    raise ValueError("release requires substantive Unreleased content or --notes; no placeholder release is written")


# --- atomic-ish write -----------------------------------------------------------------------------
def _atomic_write(path, text):
    """Write via a temp file in the same directory + os.replace, so a reader never sees a partial
    file and a crash mid-write cannot truncate the original."""
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".bump-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _commit_all(planned):
    """Write every planned (path, new_text) or restore every original.

    Five separate files cannot be replaced in one filesystem operation, so atomicity here means:
    compute and validate ALL new content first (nothing is written while an edit can still fail),
    then replace them one by one, and if any replace throws, put the already-written ones back from
    the originals held in memory. A repo left half-bumped is the exact drift this tool exists to
    prevent, so a partial failure must not be able to create one.
    """
    written = []
    try:
        for path, _old, new in planned:
            _atomic_write(path, new)
            written.append(path)
    except Exception as e:
        for path, old, _new in planned:
            if path in written:
                try:
                    _atomic_write(path, old)
                except Exception:
                    print("ROLLBACK FAILED for %s, restore it from git" % path, file=sys.stderr)
        raise RuntimeError("write failed (%s); rolled back %d file(s)" % (e, len(written)))
    return written


# --- ROADMAP ----------------------------------------------------------------------------------------
def plan_roadmap(text, new_ver, notes):
    """Update 'Current: **vX.Y.Z**' and, if the file uses the '## vX.Y.Z (current)' convention,
    demote that heading and open a new one above it.

    Repos that lay their roadmap out differently (buy-me-a-car heads its body with
    '## What shipped (through 0.2.2)') get the Current line updated and their body left alone: a
    writer that reshapes prose it does not understand is worse than one that says what it skipped.
    Returns (new_text, note_for_the_operator).
    """
    nl = vs.newline_of(text)
    out, n = vs.set_roadmap_current(text, new_ver)
    if n == 0:
        raise ValueError("ROADMAP.md: no 'Current: **vX.Y.Z**' line to update")

    m = None
    for cand in vs.RE_ROADMAP_CURRENT_HEADING.finditer(out):
        if "(current)" in cand.group(2):
            m = cand
            break
    if not m:
        return out, "ROADMAP.md: no '## vX.Y.Z (current)' heading found, body left untouched"

    demoted = m.group(0).replace(" (current)", "", 1)
    # ROADMAP is a current capability view, not a second copy of release history.
    body = "See [CHANGELOG.md](CHANGELOG.md) for this release; current capabilities follow below."
    new_section = "## v%s (current)%s%s%s%s" % (new_ver, nl, body, nl, nl)
    out = out[:m.start()] + new_section + demoted + out[m.end():]
    return out, "ROADMAP.md: demoted the previous heading, opened '## v%s (current)'" % new_ver


# --- CHANGELOG ----------------------------------------------------------------------------------
def plan_changelog(text, new_ver, date, notes):
    """Open a '## [X.Y.Z] - <date>' section, absorbing an '## [Unreleased]' body if there is one.

    Absorbing rather than appending is the whole reason Unreleased exists: work accumulates there
    between releases and the bump is the moment it acquires a number. Leaving it behind would
    publish a release whose changelog entry is a TODO while the real notes sit above it, unversioned.
    Returns (new_text, note_for_the_operator).
    """
    nl = vs.newline_of(text)
    validate_release_version(new_ver)
    validate_release_date(date)
    heading = vs.changelog_heading(new_ver, date)
    body = release_notes(text, notes).strip().replace("\r\n", "\n").replace("\n", nl)

    m = vs.RE_CHANGELOG_UNRELEASED.search(text)
    if m:
        end = m.end() + len(release_body(text, m))
        out = text[:m.start()] + heading + nl + body + nl + nl + text[end:]
        return out, "CHANGELOG.md: absorbed the Unreleased body into %s" % heading

    section = "%s%s%s%s%s" % (heading, nl, body, nl, nl)
    m = vs.RE_CHANGELOG_HEADING.search(text)
    if m:
        out = text[:m.start()] + section + text[m.start():]
    else:
        sep = "" if text.endswith(nl) else nl
        out = text + sep + nl + section
    return out, "CHANGELOG.md: inserted %s" % heading


# --- main ---------------------------------------------------------------------------------------
def build_plan(root, new_ver, cur_ver, date, notes, prerelease):
    """Compute the new content of all five sites. Raises before anything is written if any fails."""
    if validate_release_version(new_ver) <= validate_release_version(cur_ver):
        raise ValueError("target release version must advance the current version")
    release_date = validate_release_date(date)
    changelog = vs.read_text(os.path.join(root, vs.SITE_FILES["CHANGELOG"]))
    if changelog is None:
        raise ValueError("CHANGELOG.md: unreadable")
    latest = vs.RE_CHANGELOG_HEADING.search(changelog)
    if latest:
        current_line = changelog[latest.start():].splitlines()[0]
        match = re.fullmatch(r"##\s*\[[0-9]+\.[0-9]+\.[0-9]+\]\s*-\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*", current_line)
        if not match or release_date < validate_release_date(match.group(1)):
            raise ValueError("release date must be valid and not precede the latest recorded release")
    release_notes(changelog, notes)
    planned, notes_out = [], []

    def site(key):
        path = os.path.join(root, vs.SITE_FILES[key])
        raw = vs.read_text(path)
        if raw is None:
            raise ValueError("%s: unreadable" % vs.SITE_FILES[key])
        return path, raw

    # 1) plugin.json
    path, raw = site("plugin")
    planned.append((path, raw, vs.set_plugin_version(raw, cur_ver, new_ver)))

    # 2+3) the two README badges
    for key in ("README", "README_CN"):
        path, raw = site(key)
        new, n = vs.set_badge_version(raw, new_ver, prerelease)
        if n == 0:
            raise ValueError("%s: no Roadmap badge to update" % vs.SITE_FILES[key])
        planned.append((path, raw, new))

    # 4) ROADMAP.md
    path, raw = site("ROADMAP")
    new, note = plan_roadmap(raw, new_ver, notes)
    planned.append((path, raw, new))
    notes_out.append(note)

    # 5) CHANGELOG.md
    path, raw = site("CHANGELOG")
    new, note = plan_changelog(raw, new_ver, date, notes)
    planned.append((path, raw, new))
    notes_out.append(note)

    return planned, notes_out


def refuse_if_drifted(root, versions):
    """The precondition. Print the same picture check_conformance.py prints, then refuse."""
    print("REFUSING: %s is already version-drifted." % root)
    print("-" * 70)
    print("  [FAIL] version four-source synced  -> %s" % versions)
    for key in vs.SITE_ORDER:
        v = versions.get(key)
        print("    %-10s %-24s %s" % (key, v if v else "MISSING / unparseable", vs.SITE_FILES[key]))
    print("-" * 70)
    print("Bumping over drift would hide which site was left behind and at what version, and the")
    print("half-applied release behind it would never be understood. Bring the five sites to one")
    print("agreed version by hand, confirm with:")
    print("  python check_conformance.py %s" % root)
    print("then run this again.")
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Bump a Spec-v1 skill repo's version at all five sites.")
    ap.add_argument("repo", help="path to the skill repo")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--level", choices=["major", "minor", "patch"], help="semver bump level")
    g.add_argument("--set", dest="set_to", metavar="X.Y.Z", help="set an exact version")
    ap.add_argument("--notes", default="", help="one-line release note for ROADMAP + CHANGELOG")
    pre = ap.add_mutually_exclusive_group()
    pre.add_argument("--prerelease", metavar="TAG",
                     help="badge pre-release marker, e.g. alpha -> Roadmap-vX.Y.Z%%20alpha-purple")
    pre.add_argument("--no-prerelease", action="store_true",
                     help="drop an existing badge pre-release marker")
    ap.add_argument("--date", default=None, metavar="YYYY-MM-DD",
                    help="CHANGELOG date; defaults to the system clock (override is for tests)")
    ap.add_argument("--dry-run", action="store_true", help="print what would change, write nothing")
    a = ap.parse_args(argv)

    root = os.path.abspath(os.path.expanduser(a.repo))
    if not os.path.isdir(root):
        print("ERROR: not a directory: %s" % root)
        return 2

    # PRECONDITION: all five sites must already agree.
    versions = vs.collect(root)
    if not vs.is_synced(versions):
        return refuse_if_drifted(root, versions)
    cur_ver = versions["plugin"]

    if a.set_to:
        try:
            vs.parse_semver(a.set_to)
        except ValueError as e:
            print("ERROR: %s" % e)
            return 2
        new_ver = a.set_to
    else:
        new_ver = vs.next_version(cur_ver, a.level)

    if new_ver == cur_ver:
        print("ERROR: %s is already at %s; nothing to bump." % (root, cur_ver))
        return 2

    # The badge pre-release marker round-trips by default: buy-me-a-car ships
    # "Roadmap-v0.2.2%20alpha-purple" on purpose, and a bump that silently flattened it to
    # "v0.2.3-purple" would quietly promote a pre-release to a release in the one place users look.
    if a.prerelease is not None:
        if not vs.RE_PRERELEASE_TAG.match(a.prerelease):
            print("ERROR: --prerelease must be alphanumeric / dots: %r" % a.prerelease)
            return 2
        prerelease = "%%20%s" % a.prerelease
    elif a.no_prerelease:
        prerelease = ""
    else:
        prerelease = None  # keep whatever each badge already carries
    existing_pre = vs.collect_prerelease(root)

    date = a.date or datetime.date.today().isoformat()

    try:
        planned, notes_out = build_plan(root, new_ver, cur_ver, date, a.notes, prerelease)
    except ValueError as e:
        print("REFUSING: %s" % e)
        return 1

    print("%s: %s -> %s%s" % (root, cur_ver, new_ver, "  (dry run)" if a.dry_run else ""))
    kept = existing_pre.get("README") or ""
    if prerelease is None and kept:
        print("  badge pre-release marker kept: %s" % kept)
    elif prerelease:
        print("  badge pre-release marker set: %s" % prerelease)
    elif a.no_prerelease and kept:
        print("  badge pre-release marker dropped: %s" % kept)

    for path, _old, _new in planned:
        print("  %s %s" % ("would write" if a.dry_run else "write",
                           os.path.relpath(path, root)))
    for note in notes_out:
        print("  note: %s" % note)

    if a.dry_run:
        print("dry run: nothing written.")
        return 0

    _commit_all(planned)

    after = vs.collect(root)
    if not vs.is_synced(after) or after["plugin"] != new_ver:
        print("ERROR: post-write verification failed: %s" % after)
        return 1
    print("all five sites now read %s." % new_ver)
    print("NOT committed and NOT pushed: cutting a release is yours to decide. Review the diff, then")
    print("  git add -- %s && git commit" % " ".join(
        sorted(os.path.relpath(p, root).replace(os.sep, "/") for p, _o, _n in planned)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
