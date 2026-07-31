#!/usr/bin/env python3
"""Skill Repo Spec v1 linter. Checks a skill repo dir for conformance.

Usage:  python check_conformance.py <repo_dir>
Exits 0 if no check FAILS, 1 otherwise. Stdlib only. (Skill Repo Spec v1.)

THREE STATUSES, AND THE LINE BETWEEN THEM
    PASS   the property holds.
    WARN   the property does not hold, and no edit available today makes it hold cleanly, OR the
           finding is real but the detector's measured precision does not justify blocking on it.
           Printed, counted, never blocks.
    FAIL   the property does not hold and an edit fixes it.

    A gate that reassures is worse than no gate, so nothing here is allowed to be silent. But a gate
    that goes red for something no edit can fix trains the operator to skip the report, which is how
    this very linter died the first time. WARN is the seam between those two failure modes, and
    every check below states which side it sits on and why.
"""
import datetime
import glob
import json
import os
import subprocess
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import version_sites  # noqa: E402  (sibling module: the one definition of where a version lives)

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
results = []


def check(name, ok, detail=""):
    """ok is True (PASS), False (FAIL), or the string WARN."""
    results.append((name, ok, detail))


def read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


# =====================================================================================
# SKILL.md always-loaded size (Spec v1 s11)
# =====================================================================================
# WHY A NUMBER AND NOT A WORD
#     reference/triggering.md said "keep SKILL.md thin". Thin is unmeasurable, so nothing measured
#     it, and the fleet drifted to a 41,959-char always-loaded file that is paid for on every single
#     invocation of that skill. A rule with no number is a preference.
#
# THE THRESHOLDS, AND THE HONEST PART
#     WARN above 12,000 chars, FAIL above 16,000. These were NOT picked so the fleet passes today.
#     Measured 2026-07-31 across the 15 plugin repos, 5 of 30 SKILL.md files are over the FAIL line
#     and 4 more sit in the WARN band. Pretending otherwise is the exact dishonesty this gate exists
#     to catch, so the debt is carried in the open, below.
#
# THE RATCHET
#     Each grandfathered entry records the size MEASURED on the date named. The file may shrink
#     freely; it may not grow by a single character. So the allowlist can only ever get shorter, an
#     entry that drops back under the FAIL line is reported as retirable, and a repo cannot quietly
#     keep expanding an already-oversized always-loaded file. Growth on a grandfathered file is a
#     FAIL, not a WARN: the whole point of a ratchet is that it does not turn.
#
# WHY THE ALLOWLIST ALSO CARRIES A DATED TARGET
#     The allowlist as first shipped held exactly the five files over the FAIL line, which meant the
#     gate's first run over the fleet produced zero FAIL rows: 5 of 30 always-loaded files (17% of
#     the files, 40% of the always-loaded characters) were simply exempt, and a run with no FAIL rows
#     reads as "the fleet is within budget". It is not. It is 59,007 characters over, paid on every
#     invocation.
#     The threshold is not the thing to move. The honesty is. So each entry now names a SHRINK TARGET
#     and a DATE by which it must be met; the entries WARN on every single run with the arithmetic
#     spelled out rather than passing quietly; the per-repo summary line carries "N grandfathered,
#     M chars over target" so no run can present itself as clean; and once the target date passes
#     with the file still over target, the entry FAILS. A grandfather clause with no expiry is not a
#     plan to fix anything, it is a permanent exemption with a reassuring name.
SKILL_MD_WARN = 12000
SKILL_MD_FAIL = 16000

# key: "<repo-dir-name>/<path relative to the repo root, forward slashes>"
# value: (ceiling chars, date measured, target chars, target date)
#   ceiling  the size measured on that date. The file may never exceed it: that is the ratchet.
#   target   what it must come down to, and by when. Targets are all SKILL_MD_FAIL, because the
#            allowlist exists to buy time to reach the line everyone else already meets, not to
#            install a second, softer line. The dates are staged by how far each file has to travel.
SKILL_MD_GRANDFATHERED = {
    "buy-me-a-car/skills/orchestrator/SKILL.md":                  (41959, "2026-07-31", 16000, "2026-10-31"),
    "shopping-aggregator/skills/shopping-aggregator/SKILL.md":    (29955, "2026-07-31", 16000, "2026-10-31"),
    "small-cap-deepdive/SKILL.md":                                (25288, "2026-07-31", 16000, "2026-09-30"),
    "market-intel/skills/market-intel/SKILL.md":                  (24653, "2026-07-31", 16000, "2026-09-30"),
    "buy-me-a-car/skills/close-day-checklist/SKILL.md":           (17078, "2026-07-31", 16000, "2026-08-31"),
}

# Filled in by check_skill_md_size() so the summary line can state the debt instead of a bare pass.
GRANDFATHER_DEBT = {"entries": 0, "over_target": 0, "overdue": 0, "rows": []}


def skill_md_paths(root):
    """Every SKILL.md this repo ships: skills/<name>/SKILL.md, plus the root-skill layout."""
    out = sorted(glob.glob(os.path.join(root, "skills", "*", "SKILL.md")))
    r = os.path.join(root, "SKILL.md")
    if os.path.isfile(r):
        out.append(r)
    return out


def grandfather_key(root, path):
    rel = os.path.relpath(path, root).replace(os.sep, "/")
    return "%s/%s" % (os.path.basename(os.path.abspath(root)), rel)


def _days_until(datestr):
    """Whole days from today to datestr (negative once the date has passed). None if unparseable."""
    try:
        d = datetime.datetime.strptime(datestr, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    return (d - datetime.date.today()).days


def check_skill_md_size(root):
    for p in skill_md_paths(root):
        text = read(p) or ""
        n = len(text)
        key = grandfather_key(root, p)
        label = "SKILL.md size (%d chars): %s" % (n, os.path.relpath(p, root).replace(os.sep, "/"))
        gf = SKILL_MD_GRANDFATHERED.get(key)
        if gf:
            ceiling, when, target, by = gf
            over_target = max(0, n - target)
            left = _days_until(by)
            overdue = left is not None and left < 0 and over_target > 0
            # Record the debt whatever the verdict below turns out to be. The summary line has to be
            # able to say how much is being carried even in the run where every row happens to be a
            # WARN, because that is exactly the run a reader would otherwise call clean.
            GRANDFATHER_DEBT["entries"] += 1
            GRANDFATHER_DEBT["over_target"] += over_target
            GRANDFATHER_DEBT["overdue"] += 1 if overdue else 0
            GRANDFATHER_DEBT["rows"].append(
                "%s: %d chars, target %d by %s (%s), over target by %d"
                % (os.path.relpath(p, root).replace(os.sep, "/"), n, target, by,
                   "OVERDUE" if overdue else ("%d days left" % left if left is not None
                                              else "unparseable date"),
                   over_target))
            if n > ceiling:
                check(label, False,
                      "%d chars, above its %s grandfathered ceiling of %d. Grandfathered files may "
                      "shrink, never grow." % (n, when, ceiling))
            elif overdue:
                # The date was the whole point. An allowlist entry that sails past its own deadline
                # and keeps warning is the permanent exemption this design exists to prevent.
                check(label, False,
                      "%d chars, still %d over its %d target, which was due %s. The grandfather "
                      "clause has EXPIRED: cut the file or argue for a new dated target in the "
                      "allowlist." % (n, over_target, target, by))
            elif n > SKILL_MD_FAIL:
                check(label, WARN,
                      "GRANDFATHERED DEBT: %d chars, %d over the %d target due %s (%s). Ceiling %d "
                      "set %s. Paid on every single invocation of this skill."
                      % (n, over_target, target, by,
                         "%d days left" % left if left is not None else "unparseable date",
                         ceiling, when))
            else:
                check(label, True,
                      "%d chars, now under the %d line. Retire its allowlist entry."
                      % (n, SKILL_MD_FAIL))
        elif n > SKILL_MD_FAIL:
            check(label, False, "%d chars, over the %d limit. Move on-demand material into "
                                "reference/<shard>.md." % (n, SKILL_MD_FAIL))
        elif n > SKILL_MD_WARN:
            check(label, WARN, "%d chars, over the %d warn line (limit %d)."
                  % (n, SKILL_MD_WARN, SKILL_MD_FAIL))
        else:
            check(label, True, "%d chars" % n)


# =====================================================================================
# Shard pointers resolve (Spec v1 s11)
# =====================================================================================
# WHAT BREAKS WITHOUT IT
#     Progressive disclosure is the whole SKILL.md design: the always-loaded file names shards and
#     the agent loads them on demand. A shard pointer that does not resolve is therefore not a typo,
#     it is an instruction the agent cannot carry out, and it is invisible until a run needs it.
#
# THE ROOT MODEL (the thing a naive checker gets wrong)
#     A pointer written inside skills/<name>/SKILL.md is by convention relative to the SKILL
#     DIRECTORY, which is how `reference/foo.md` works everywhere. Repo-root-relative pointers also
#     occur, so resolution tries the skill directory first and then the repo root. In the root-skill
#     layout (SKILL.md at the repo root) the two are the same directory and nothing changes.
#
# FAIL VERSUS WARN, DECIDED BY CORROBORATION, NOT BY TASTE
#     Plenty of legitimate paths do not resolve in this repo: an output file a run creates, a path
#     inside the user's private companion repo, a shard named in a sibling skill's repo. A checker
#     that fails those cries wolf. So an unresolved pointer only FAILS when something corroborates
#     that it meant a file HERE:
#       (a) its parent directory exists under the SKILL's own root (you named a directory we ship
#           and a file in it that is missing), or
#       (b) its basename exists exactly once elsewhere in this repo (it moved, the pointer did not).
#     Everything else is WARN.
#     Measured on the fleet 2026-07-31: 225 pointers resolved, 3 FAIL, 3 WARN, and each of the 3
#     FAILs was hand-verified as a genuinely dangling shard while each of the 3 WARNs was verified
#     correct by design. Corroboration by REPO root instead of skill root was tried first and
#     produced 3 false FAILs, because a companion-config repo mirrors the main repo's directory
#     names.
POINTER_EXTS = (".md", ".py", ".ps1", ".sh", ".yml", ".yaml", ".tmpl", ".json", ".txt",
                ".vbs", ".js", ".ts")
# Files every repo carries, so "it exists exactly once elsewhere" says nothing about a pointer.
POINTER_GENERIC = {"skill.md", "readme.md", "readme_cn.md", "changelog.md", "roadmap.md", "license"}
_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
_MD_CODE = re.compile(r"`([^`\n]+)`")
# A placeholder is not a path: <name>, {slug}, $VAR, *.md, 50%.
_PLACEHOLDER = re.compile(r"[*<>{}$%?|\"']")


def pointer_candidates(text):
    """Markdown link targets and inline code spans, in source order."""
    out = [m.group(1) for m in _MD_LINK.finditer(text)]
    out += [m.group(1) for m in _MD_CODE.finditer(text)]
    return out


def as_relpath(tok):
    """The token as a repo-relative file path, or None if it is not one.

    Deliberately narrow. A code span holding a whole command ("python scripts/x.py --flag") is
    rejected on the space: splitting commands into tokens was measured on the fleet and added two
    false positives and no true ones, because a companion repo's scripts/ has the same names.
    """
    t = (tok or "").strip()
    if not t or " " in t:
        return None
    if "://" in t or t.startswith(("#", "mailto:", "http", "www.")):
        return None
    if t.startswith(("/", "~", "\\")) or re.match(r"^[A-Za-z]:[\\/]", t):
        return None
    if _PLACEHOLDER.search(t):
        return None
    t = t.split("#", 1)[0].rstrip(":,.;")
    if "/" not in t or not t.lower().endswith(POINTER_EXTS):
        return None
    return t


def basename_index(root):
    idx = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "__pycache__", "node_modules", ".pytest_cache")]
        for fn in filenames:
            idx.setdefault(fn.lower(), []).append(os.path.join(dirpath, fn))
    return idx


def check_shard_pointers(root):
    paths = skill_md_paths(root)
    if not paths:
        return
    idx = basename_index(root)
    for p in paths:
        base = os.path.dirname(p)
        text = read(p) or ""
        rel_skill = os.path.relpath(p, root).replace(os.sep, "/")
        seen, dangling, unresolved = set(), [], []
        n_ok = 0
        for tok in pointer_candidates(text):
            rp = as_relpath(tok)
            if not rp or rp in seen:
                continue
            seen.add(rp)
            if any(os.path.exists(os.path.normpath(os.path.join(r, rp))) for r in (base, root)):
                n_ok += 1
                continue
            parent = os.path.dirname(rp)
            if parent and os.path.isdir(os.path.normpath(os.path.join(base, parent))):
                dangling.append("%s (its %s/ is right there, the file is not)" % (rp, parent))
                continue
            bn = os.path.basename(rp).lower()
            elsewhere = [] if bn in POINTER_GENERIC else idx.get(bn, [])
            if len(elsewhere) == 1:
                dangling.append("%s (moved? the one %s in this repo is %s)"
                                % (rp, bn, os.path.relpath(elsewhere[0], root).replace(os.sep, "/")))
            else:
                unresolved.append(rp)
        # The count goes in the LABEL, not the detail, because details are only printed for rows
        # that are not PASS. A pointer check that found zero candidates and a pointer check that
        # verified twenty-one both print "[PASS] shard pointers resolve" otherwise, and those are
        # very different sentences.
        label = "shard pointers resolve (%d): %s" % (len(seen), rel_skill)
        if dangling:
            check(label, False, "%d of %d dangling -> %s" % (len(dangling), len(seen),
                                                             "; ".join(dangling)))
        elif unresolved:
            check(label, WARN,
                  "%d of %d do not resolve here (fine if they name a runtime output or another "
                  "repo) -> %s" % (len(unresolved), len(seen), ", ".join(unresolved)))
        else:
            check(label, True, "%d resolved" % n_ok)


# =====================================================================================
# Retrofit markers in instruction text (Spec v1 s11)
# =====================================================================================
# THE DEFECT
#     "Phase 5 adds a catalyst modifier" tells a reader what CHANGED. It does not tell them what the
#     rule IS, and it silently assumes they know which phase they are in. Instruction text should
#     state the rule; the history belongs in CHANGELOG.md.
#
# WHY THIS ONE IS DELIBERATELY SMALL
#     The first version of this lint matched seven patterns and hit 261 times across 48 files, with
#     the largest violator being a designated source of truth, and three patterns were ordinary
#     English ("pending" is a state name, "TODO" appears in prose about an output field, a version
#     pin is correct in install instructions). A lint needing a 20 entry allowlist on day one is a
#     lint that gets muted. So this matches only the RETROFIT SYNTAX: an iteration marker adjacent to
#     a rule verb.
#
# WHAT WAS MEASURED BEFORE SHIPPING (2026-07-31, whole fleet)
#     Including bare version numbers (v1.2, 0.15): 16 hits, of which 6 were false (a price per kWh,
#     a third party API version, a config spec's own version history). Dropped.
#     Iteration markers only: 8 hits in 5 files, all in one repo, all hand-verified genuine. That is
#     what ships. Scope is SKILL.md plus reference/, the instruction surface. README, ROADMAP,
#     CHANGELOG and PHILOSOPHY are excluded by design: a changelog's job IS to say "v0.2 adds X",
#     and including them added 4 hits, all legitimate narrative.
#     It reports WARN, never FAIL: 8 of 8 precision on one fleet on one day is good enough to
#     surface prose, not good enough to block a commit on it.
_FENCE = re.compile(r"^\s*```")
_RETROFIT = re.compile(
    r"(?:\b(?:iteration|round|revision|rev|pass|phase)\s*#?\d+\b|#\d+\b)"   # the marker
    r"[^.\n]{0,40}?\s"                                                      # a short span
    r"(?:adds|now|introduces|changes|refines|removes|replaces|is\s+removed|no\s+longer)\b",
    re.I)


def retrofit_hits(path):
    """(line number, matched fragment) for every retrofit marker OUTSIDE a fenced code block."""
    hits, in_fence = [], False
    text = read(path)
    if text is None:
        return hits
    for i, line in enumerate(text.splitlines(), 1):
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _RETROFIT.search(line)
        if m:
            hits.append((i, m.group(0).strip()))
    return hits


def check_retrofit_markers(root):
    targets = []
    for p in skill_md_paths(root):
        targets.append(p)
        targets += sorted(glob.glob(os.path.join(os.path.dirname(p), "reference", "**", "*.md"),
                                    recursive=True))
    hits = []
    hit_files = set()
    for t in targets:
        for ln, frag in retrofit_hits(t):
            hits.append("%s:%d %r" % (os.path.relpath(t, root).replace(os.sep, "/"), ln, frag))
            hit_files.add(t)
    if not targets:
        return
    if hits:
        shown = "; ".join(hits[:4])
        more = "" if len(hits) <= 4 else " (+%d more)" % (len(hits) - 4)
        # "across %d file(s)" used to be handed len(targets), the number of files SCANNED, so
        # small-cap-deepdive's 8 markers in 5 files read as "8 markers across 10 files". Both
        # numbers are worth having and they answer different questions, so both are named: how many
        # files CARRY a marker, and how many were looked at.
        check("instruction text states rules, not version deltas", WARN,
              "%d retrofit marker(s) in %d of %d file(s) scanned -> %s%s. State the rule; the "
              "history belongs in CHANGELOG.md."
              % (len(hits), len(hit_files), len(targets), shown, more))
    else:
        check("instruction text states rules, not version deltas (%d files scanned)" % len(targets),
              True)


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

    # 1d) the DASH gate (Spec v1 section 10): published prose carries no en/em dash. Style, not
    # security, so it scans the current tree only. The tool de-dashes Markdown + Python comments and
    # leaves every string literal (data) alone.
    for rel in ["tools/dash_guard.py", ".github/workflows/dash-guard.yml"]:
        check("dash gate: %s" % rel, os.path.isfile(os.path.join(root, *rel.split("/"))))
    dguard = os.path.join(root, "tools", "dash_guard.py")
    if os.path.isfile(dguard):
        p = subprocess.run([sys.executable, dguard, "--tree"], cwd=root, capture_output=True, text=True)
        check("dash gate: prose is dash-clean (tree)", p.returncode == 0,
              (p.stderr or "").strip().splitlines()[0] if p.returncode else "")

    # at least one skills/*/SKILL.md
    skill_mds = skill_md_paths(root)
    check("skills/*/SKILL.md present", len(skill_mds) > 0, "%d found" % len(skill_mds))

    # 1e) what the SKILL.md itself costs and whether it keeps its promises (Spec v1 section 11).
    # Everything above asks whether a FILE exists. These three ask whether the always-loaded file is
    # affordable, whether the shards it points at are actually there, and whether it states rules
    # rather than a version history. All three were unmeasured until 2026-07-31, and the fleet had
    # drifted accordingly: a 41,959-char always-loaded file, three dangling shard pointers, and
    # instruction text that told the reader which phase added a rule instead of what the rule is.
    check_skill_md_size(root)
    check_shard_pointers(root)
    check_retrofit_markers(root)

    # 2) plugin.json fingerprint
    pj_raw = read(os.path.join(root, ".claude-plugin", "plugin.json"))
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
        except Exception as e:
            check("plugin.json valid JSON", False, str(e))
    else:
        check("plugin.json readable", False)

    # 3) version four-source sync
    readme = read(os.path.join(root, "README.md")) or ""
    readme_cn = read(os.path.join(root, "README_CN.md")) or ""

    # The five site patterns live in version_sites.py, shared with scaffold_skill.py (which stamps
    # them) and bump_version.py (which rewrites them). They used to be re-typed here, and the copy
    # had drifted: it demanded a bare "Roadmap-vX.Y.Z-purple" badge, so a repo whose badge carries a
    # deliberate pre-release marker ("Roadmap-v0.2.2%20alpha-purple") read as having NO version and
    # was reported drifted while all five of its sites agreed. A linter that cries wolf gets muted,
    # which is worse than no linter.
    versions = version_sites.collect(root)
    check("version four-source synced", version_sites.is_synced(versions), str(versions))

    # 4) README philosophy-first + badge block
    check("README badge: Claude Code Skill (orange)",
          "Claude%20Code-Skill-orange" in readme)
    check("README badge: License MIT (blue)", "License-MIT-blue" in readme)
    # EN + CN is the floor, not the ceiling: a repo that also ships ES writes
    # "Languages-EN%20%2F%20CN%20%2F%20ES-blue", which is a superset of the requirement. The old
    # substring test read that as a MISSING badge, i.e. it penalized a repo for translating more.
    check("README badge: Languages (blue)",
          bool(re.search(r"Languages-EN%20%2F%20CN(?:%20%2F%20[A-Z]{2})*-blue", readme)))
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
    n_fail = n_warn = 0
    for nm, ok, detail in results:
        if ok is True:
            tag = PASS
        elif ok == WARN:
            tag = WARN
            n_warn += 1
        else:
            tag = FAIL
            n_fail += 1
        line = "  [%s] %s" % (tag, nm)
        if detail and tag != PASS:
            line += "  -> %s" % detail
        print(line)
    # The grandfathered always-loaded debt, restated on its own, every run, whatever the verdict.
    # It is printed here and not only as WARN rows because the rows scroll and this is the number
    # that decides whether "the fleet is within budget" is a true sentence.
    if GRANDFATHER_DEBT["entries"]:
        print("-" * 60)
        print("  GRANDFATHERED ALWAYS-LOADED DEBT (carried, not fixed):")
        for r in GRANDFATHER_DEBT["rows"]:
            print("    %s" % r)
    print("-" * 60)
    total = len(results)
    # This summary line is what fleet_check.py lifts into the nightly digest, so the WARN count has
    # to be ON it. A warning that only exists in the full log is a warning nobody reads.
    #
    # The grandfather clause has to be on it for the same reason and a stronger one: the allowlist
    # was seeded with exactly the files over the fail line, so without this the very first fleet run
    # printed "N/N passed" over 59,007 characters of exempted always-loaded debt. A summary that can
    # say "passed" while carrying an exemption it does not mention is the gate reassuring its reader,
    # which is the one thing this file is not allowed to do.
    tail = []
    if n_fail:
        tail.append("%d FAIL" % n_fail)
    if n_warn:
        tail.append("%d WARN" % n_warn)
    if GRANDFATHER_DEBT["entries"]:
        tail.append("%d grandfathered, %d chars over target%s"
                    % (GRANDFATHER_DEBT["entries"], GRANDFATHER_DEBT["over_target"],
                       ", %d OVERDUE" % GRANDFATHER_DEBT["overdue"]
                       if GRANDFATHER_DEBT["overdue"] else ""))
    print("%d/%d passed%s" % (total - n_fail - n_warn, total,
                              "" if not tail else "  (%s)" % ", ".join(tail)))
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python check_conformance.py <repo_dir>")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
