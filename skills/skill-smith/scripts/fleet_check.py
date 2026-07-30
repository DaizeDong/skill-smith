#!/usr/bin/env python3
"""fleet_check.py -- the nightly, READ-ONLY driver for the whole skill fleet.

WHY THIS EXISTS
---------------
check_conformance.py has been correct and complete for weeks and has surfaced exactly nothing,
because nothing ever ran it. A linter with no driver is a linter that does not exist. The missing
piece here was never more judgment, it was a driver and a schedule. So this file adds no new
opinions: it fans out the checkers that already exist, plus the two assertions nothing on this
machine performs at all (a data directory sitting inside a git worktree, and whether the CI that
the whole doctrine calls "the authority" is actually green).

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
1. There is NO --fix and no auto-repair, ever. Three of the per-skill config dotdirs it inspects
   have no companion repo on disk at all and two hold live secrets and uncommitted state.
   "Converge them" is a data-loss button wearing a helpful label. Check only, report, stop.
2. It does not check that a repo has upstream tracking configured. sync-skills.ps1 was rewritten to
   be branch-agnostic and nothing on this machine reads branch.<name>.remote any more, so that check
   would guard a property with no consumer and stay red forever.
3. It does not check that the per-skill config dotdirs are junctions. The plain-directory shape is
   the DESIGNED one, spelled out in tools/datadir.py's own docstring.
   The rule behind all three: a nightly check whose first run reports findings that are unfixable by
   design trains the operator to skip the digest line. That is precisely how check_conformance.py
   died the first time, and it would take this driver down with it.

THE FIVE CHECKS
---------------
  junctions   every junction/symlink under ~/.claude/skills resolves to a directory that exists.
              Failure mode: a repo gets moved (CodesSelf -> CodesClaude, 2026-07-22) and the skill
              silently vanishes from the agent's library with no error anywhere.
  workflow    visibility PUBLIC implies the repo carries .github/workflows/pii-guard.yml.
              Entries with no local clone under the fleet root are SKIPPED, not failed: the
              visibility map outlives the working copies it was built from and names repos that are
              not checked out here (and third-party forks, whose CI is not ours to install).
  conformance check_conformance.py over every repo carrying .claude-plugin/plugin.json.
  databoundary the INVERSE data-boundary assertion, which is the one check that would have caught
              the 2026-07 leak: data_boundary.py proves the REPO holds no real-run output, and this
              proves the reverse, that the resolved real-run output directory is not itself inside a
              git worktree. Both were true and the leak still happened, because nobody ever looked
              from this end. Not-initialized is not a failure: an uninitialized tool is the correct
              shipping state.
  ci          the pii-guard workflow is actually GREEN on the public repos. "CI is the authority"
              is the load-bearing sentence of the whole doctrine and nothing observes whether that
              authority is passing, so a red guard is invisible today. Degrades to UNKNOWN (never
              FAIL, never blocking) when gh is missing, unauthenticated, rate limited, or the
              workflow has simply never run.

OUTPUT CONTRACT
---------------
Read-only: there is nothing in here that writes to any repo. Exits nonzero if any row is FAIL.
UNKNOWN and SKIP never affect the exit code. Prints a human-readable report to stdout and writes a
machine-readable status JSON (default ~/.skill-smith-data/fleet-check-status.json, override with
--status-json) carrying a UTC timestamp, so the caller verifies FRESHNESS rather than trusting an
exit code it cannot reliably read: a scheduled caller runs this in a child shell where the exit code
is not a promise, and here exit 1 means "some check FAILED", not "the run happened". Those are
different questions and only the artifact answers the second one.

  python fleet_check.py                  # full run, including the gh-backed CI check
  python fleet_check.py --offline        # no network, no gh
  python fleet_check.py --no-status      # report only, write nothing at all

Stdlib only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CONFORMANCE = os.path.join(HERE, "check_conformance.py")

DEFAULT_SKILLS_DIR = os.path.expanduser("~/.claude/skills")
DEFAULT_CODE_ROOT = os.path.expanduser("~/CodesClaude")
DEFAULT_VISIBILITY = os.path.expanduser("~/.pii-guard/visibility.json")
# The status file is REAL-RUN OUTPUT: it carries repo names, resolved machine paths and failure
# text. By this repo's own rule that lands in the private store, never inside the repo and never
# hardcoded into another tool's internals, so the default is the standalone shape tools/datadir.py
# defines for this skill. A caller that wants it filed next to its other maintenance artifacts
# passes --status-json; that is the caller's layout decision to make, not this tool's.
DEFAULT_STATUS = os.path.expanduser("~/.skill-smith-data/fleet-check-status.json")

PASS, FAIL, SKIP, UNKNOWN = "PASS", "FAIL", "SKIP", "UNKNOWN"
STATUSES = (PASS, FAIL, SKIP, UNKNOWN)


# --- tiny helpers --------------------------------------------------------------------------------
def run(args, cwd=None, timeout=60):
    """Run a command, never raise. Returns (rc, stdout, stderr); rc is None on timeout."""
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        return None, "", "timed out after %ss" % timeout
    except OSError as e:
        return None, "", str(e)


def first_line(text):
    for ln in (text or "").splitlines():
        if ln.strip():
            return ln.strip()
    return ""


def is_link(path):
    """True for a POSIX symlink or a Windows junction.

    os.path.islink() returns False for junctions, which is how a dangling junction stays invisible
    to every naive scan. The reparse-point attribute is what actually distinguishes them.
    """
    if os.path.islink(path):
        return True
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return bool(getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def link_target(path):
    """The raw target of a link/junction, \\?\\ prefix stripped for display. None if unreadable."""
    try:
        t = os.readlink(path)
    except OSError:
        return None
    for pre in ("\\\\?\\", "\\??\\"):
        if t.startswith(pre):
            t = t[len(pre):]
    return t


def slug_from_url(url):
    """owner/repo, lowercased, from any remote URL shape this fleet uses.

    Covers https://github.com/Owner/repo.git, git@github.com:Owner/repo.git and the ssh host-alias
    form this machine actually uses, git@daizedong:Owner/repo.git.
    """
    u = (url or "").strip()
    if u.endswith(".git"):
        u = u[:-4]
    u = u.replace("\\", "/").rstrip("/")
    parts = [p for p in u.split("/") if p]
    if len(parts) < 2:
        return None
    repo, owner = parts[-1], parts[-2]
    if ":" in owner:
        owner = owner.rsplit(":", 1)[1]
    if not owner or not repo:
        return None
    return ("%s/%s" % (owner, repo)).lower()


def local_repos(code_root):
    """Every git working copy directly under code_root, as {name: path}."""
    out = {}
    if not os.path.isdir(code_root):
        return out
    for name in sorted(os.listdir(code_root)):
        p = os.path.join(code_root, name)
        if os.path.isdir(os.path.join(p, ".git")):
            out[name] = p
    return out


def repo_slugs(repos):
    """{slug: path} for every local repo that has an origin remote."""
    out = {}
    for name, path in repos.items():
        rc, so, _ = run(["git", "-C", path, "remote", "get-url", "origin"], timeout=20)
        if rc != 0:
            continue
        slug = slug_from_url(first_line(so))
        if slug:
            out.setdefault(slug, path)
    return out


def in_git_worktree(path):
    """(True, toplevel) if `git rev-parse --show-toplevel` succeeds inside path."""
    rc, so, _ = run(["git", "-C", path, "rev-parse", "--show-toplevel"], timeout=20)
    if rc == 0 and first_line(so):
        return True, first_line(so)
    return False, ""


# --- the report ----------------------------------------------------------------------------------
class Check:
    def __init__(self, cid, title):
        self.id = cid
        self.title = title
        self.rows = []          # (status, name, detail)
        self.note = ""          # one-line context for the whole check, printed under the title

    def add(self, status, name, detail=""):
        self.rows.append((status, name, detail))

    def count(self, status):
        return sum(1 for s, _n, _d in self.rows if s == status)

    def summary(self):
        return {s.lower(): self.count(s) for s in STATUSES}


# --- check 1: skill junctions --------------------------------------------------------------------
def check_junctions(skills_dir):
    c = Check("junctions", "skill junctions under %s resolve" % skills_dir)
    if not os.path.isdir(skills_dir):
        c.note = "skills dir does not exist; nothing declared"
        return c
    for name in sorted(os.listdir(skills_dir)):
        p = os.path.join(skills_dir, name)
        if not is_link(p):
            continue                     # a plain directory is a bundled skill, not a deployment
        tgt = link_target(p) or "(unreadable)"
        # isdir() on the link follows it, so this is exactly what a consumer of the skill sees.
        if os.path.isdir(p):
            c.add(PASS, name, tgt)
        else:
            c.add(FAIL, name, "DANGLING -> %s" % tgt)
    if not c.rows:
        c.note = "no junctions found (are the skills deployed as plain copies?)"
    return c


# --- check 2: PUBLIC implies a pii-guard workflow -------------------------------------------------
def check_workflow(visibility_path, slugs, code_root):
    c = Check("workflow", "visibility PUBLIC implies a pii-guard CI workflow")
    try:
        with open(visibility_path, encoding="utf-8") as f:
            vis = json.load(f)
    except (OSError, ValueError) as e:
        c.note = "visibility map unreadable: %s" % e
        c.add(UNKNOWN, os.path.basename(visibility_path), str(e))
        return c
    c.note = ("skipping entries with no clone under %s; a fork of someone else's repo is not ours "
              "to gate" % code_root)
    for slug in sorted(k for k, v in vis.items() if str(v).upper() == "PUBLIC"):
        path = slugs.get(slug)
        if path is None:
            c.add(SKIP, slug, "no local clone")
            continue
        wf = os.path.join(path, ".github", "workflows", "pii-guard.yml")
        if os.path.isfile(wf):
            c.add(PASS, slug, "")
        else:
            c.add(FAIL, slug, "PUBLIC but no .github/workflows/pii-guard.yml (%s)" % path)
    return c


# --- check 3: fan check_conformance.py ------------------------------------------------------------
def check_conformance(repos, timeout):
    c = Check("conformance", "Skill Repo Spec v1 conformance (check_conformance.py)")
    if not os.path.isfile(CONFORMANCE):
        c.note = "check_conformance.py not found next to this script"
        c.add(UNKNOWN, "check_conformance.py", CONFORMANCE)
        return c
    for name, path in sorted(repos.items()):
        if not os.path.isfile(os.path.join(path, ".claude-plugin", "plugin.json")):
            continue                     # not a plugin repo, Spec v1 does not apply
        rc, so, se = run([sys.executable, CONFORMANCE, path], timeout=timeout)
        tail = [ln.strip() for ln in so.splitlines() if "passed" in ln]
        score = tail[-1] if tail else ""
        if rc is None:
            c.add(UNKNOWN, name, se or "no result")
        elif rc == 0:
            c.add(PASS, name, score)
        else:
            fails = [ln.strip() for ln in so.splitlines() if ln.strip().startswith("[FAIL]")]
            detail = score or first_line(se) or "exit %s" % rc
            if fails:
                detail += " | " + "; ".join(f[len("[FAIL]"):].strip() for f in fails)
            c.add(FAIL, name, detail)
    return c


# --- check 4: the inverse data boundary -----------------------------------------------------------
def load_datadir(path, modname):
    spec = importlib.util.spec_from_file_location(modname, path)
    if spec is None or spec.loader is None:
        raise ImportError("no loader for %s" % path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_data_boundary(repos):
    c = Check("databoundary", "resolved real-run data dirs are OUTSIDE any git worktree")
    c.note = "an uninitialized skill has no data dir yet; that is the correct shipping state"
    for name, path in sorted(repos.items()):
        dd = os.path.join(path, "tools", "datadir.py")
        if not os.path.isfile(dd):
            continue                     # this skill does not use datadir.py
        # Use the repo's OWN vendored copy: the question is where THAT resolver points, and a
        # re-implementation here would answer a subtly different question the moment one drifts.
        try:
            mod = load_datadir(dd, "fleet_datadir_%s" % name.replace("-", "_"))
            resolved = mod.resolve_data_dir(name, create=False)
        except Exception as e:                                   # noqa: BLE001 (report, never crash)
            c.add(UNKNOWN, name, "cannot load tools/datadir.py: %s" % e)
            continue
        if resolved is None:
            c.add(SKIP, name, "not initialized")
            continue
        resolved = str(resolved)
        inside, top = in_git_worktree(resolved)
        if inside:
            c.add(FAIL, name, "data dir %s is inside git worktree %s" % (resolved, top))
        else:
            c.add(PASS, name, resolved)
    return c


# --- check 5: is the authority green? --------------------------------------------------------------
GREEN = ("success",)
RED = ("failure", "timed_out", "cancelled", "startup_failure", "action_required")


def check_ci(slugs_public, timeout):
    c = Check("ci", "pii-guard CI is green on the public repos")
    gh = shutil.which("gh")
    if not gh:
        c.note = "gh not on PATH; CI state unobserved"
        c.add(UNKNOWN, "gh", "not installed")
        return c
    c.note = "UNKNOWN here never fails the run: an unauthenticated or rate limited gh is not a leak"
    for slug in sorted(slugs_public):
        rc, so, se = run([gh, "run", "list", "-w", "pii-guard", "--limit", "1", "-R", slug,
                          "--json", "conclusion,status,createdAt"], timeout=timeout)
        if rc != 0:
            c.add(UNKNOWN, slug, first_line(se) or "gh exit %s" % rc)
            continue
        try:
            runs = json.loads(so or "[]")
        except ValueError as e:
            c.add(UNKNOWN, slug, "unparseable gh output: %s" % e)
            continue
        if not runs:
            c.add(UNKNOWN, slug, "no pii-guard run recorded (workflow never pushed or never fired)")
            continue
        r = runs[0]
        concl = (r.get("conclusion") or "").lower()
        state = (r.get("status") or "").lower()
        when = r.get("createdAt") or ""
        if state != "completed":
            c.add(UNKNOWN, slug, "run %s (%s)" % (state or "unknown state", when))
        elif concl in GREEN:
            c.add(PASS, slug, when)
        elif concl in RED:
            c.add(FAIL, slug, "last run %s (%s)" % (concl, when))
        else:
            c.add(UNKNOWN, slug, "last run %s (%s)" % (concl or "no conclusion", when))
    return c


# --- report + status -------------------------------------------------------------------------------
COLLAPSE_MIN = 6   # a SKIP reason repeated more than this many times is rolled up, see print_rows


def print_rows(rows):
    """Print the rows, rolling up any large run of identical SKIPs.

    The visibility map names 70+ repos and only ~17 are cloned here, so a literal listing buries
    four real failures under 56 identical "no local clone" lines. A report nobody scrolls through
    is the same failure as a check nobody runs, so the count and the names are kept and the
    56 lines are not.
    """
    bulk = {}
    for status, _n, detail in rows:
        if status == SKIP:
            bulk[detail] = bulk.get(detail, 0) + 1
    bulk = {d for d, n in bulk.items() if n > COLLAPSE_MIN}
    done = set()
    for status, name, detail in rows:
        if status == SKIP and detail in bulk:
            if detail in done:
                continue
            done.add(detail)
            names = [n for s, n, d in rows if s == SKIP and d == detail]
            print("  %-7s (%d) %s" % (SKIP, len(names), detail))
            for chunk in textwrap.wrap(", ".join(names), width=88):
                print("          %s" % chunk)
            continue
        line = "  %-7s %-34s" % (status, name)
        if detail:
            line += " %s" % detail
        print(line.rstrip())


def print_report(checks, started, elapsed):
    print("fleet check  %s  (%.1fs)" % (started, elapsed))
    print("=" * 78)
    for c in checks:
        s = c.summary()
        print("\n[%s] %s" % (c.id, c.title))
        if c.note:
            print("  note: %s" % c.note)
        print_rows(c.rows)
        print("  -> pass %d, fail %d, skip %d, unknown %d"
              % (s["pass"], s["fail"], s["skip"], s["unknown"]))
    print("\n" + "=" * 78)
    tot = {k: sum(c.summary()[k] for c in checks) for k in ("pass", "fail", "skip", "unknown")}
    print("TOTAL  pass %d  fail %d  skip %d  unknown %d"
          % (tot["pass"], tot["fail"], tot["skip"], tot["unknown"]))
    if tot["fail"]:
        print("\nFAILURES")
        for c in checks:
            for status, name, detail in c.rows:
                if status == FAIL:
                    print("  %s: %s -- %s" % (c.id, name, detail))
    return tot


def write_status(path, checks, tot, started_utc, elapsed, exit_code):
    payload = {
        "tool": "fleet_check",
        "schema": 1,
        "utc": started_utc,
        "duration_s": round(elapsed, 2),
        "exit": exit_code,
        "totals": tot,
        "checks": {c.id: dict(title=c.title, note=c.note, **c.summary()) for c in checks},
        "failures": ["%s: %s -- %s" % (c.id, n, d)
                     for c in checks for s, n, d in c.rows if s == FAIL],
    }
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)
    return payload


def main(argv=None):
    ap = argparse.ArgumentParser(description="Read-only health check across the skill fleet.")
    ap.add_argument("--skills-dir", default=DEFAULT_SKILLS_DIR)
    ap.add_argument("--code-root", default=DEFAULT_CODE_ROOT,
                    help="where the fleet's working copies live")
    ap.add_argument("--visibility", default=DEFAULT_VISIBILITY)
    ap.add_argument("--status-json", default=DEFAULT_STATUS,
                    help="machine-readable result; the caller checks its utc for freshness")
    ap.add_argument("--no-status", action="store_true", help="do not write the status file")
    ap.add_argument("--offline", action="store_true",
                    help="skip the CI check (no network, no gh)")
    ap.add_argument("--gh-timeout", type=int, default=30)
    ap.add_argument("--conformance-timeout", type=int, default=300)
    a = ap.parse_args(argv)

    t0 = time.time()
    started_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    code_root = os.path.abspath(os.path.expanduser(a.code_root))
    repos = local_repos(code_root)
    slugs = repo_slugs(repos)

    checks = [check_junctions(os.path.abspath(os.path.expanduser(a.skills_dir)))]
    wf = check_workflow(os.path.abspath(os.path.expanduser(a.visibility)), slugs, code_root)
    checks.append(wf)
    checks.append(check_conformance(repos, a.conformance_timeout))
    checks.append(check_data_boundary(repos))

    if a.offline:
        c = Check("ci", "pii-guard CI is green on the public repos")
        c.note = "skipped (--offline)"
        checks.append(c)
    else:
        # Only ask about repos we established are PUBLIC, cloned here, and actually carry the
        # workflow. Asking about the others would produce UNKNOWN noise with no information in it.
        public_with_wf = [n for s, n, _d in wf.rows if s == PASS]
        checks.append(check_ci(public_with_wf, a.gh_timeout))

    elapsed = time.time() - t0
    tot = print_report(checks, started_utc, elapsed)
    exit_code = 1 if tot["fail"] else 0

    if not a.no_status:
        try:
            write_status(a.status_json, checks, tot, started_utc, elapsed, exit_code)
            print("\nstatus: %s" % a.status_json)
        except OSError as e:
            print("\nstatus write FAILED: %s" % e, file=sys.stderr)
            # A caller that cannot see a fresh artifact must not be told everything is fine.
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
