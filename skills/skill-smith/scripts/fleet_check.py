#!/usr/bin/env python3
"""fleet_check.py -- the nightly, READ-ONLY driver for the whole skill fleet.

WHY THIS EXISTS
---------------
check_conformance.py has been correct and complete for weeks and has surfaced exactly nothing,
because nothing ever ran it. A linter with no driver is a linter that does not exist. The missing
piece here was never more judgment, it was a driver and a schedule. So this file adds no new
opinions: it fans out the checkers that already exist, plus the two assertions nothing on this
machine performs at all (a data directory resolving into a repo the world can read, and whether the
CI that the whole doctrine calls "the authority" is actually green).

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

THE SECOND THING THAT MAKES A GATE WORSE THAN NO GATE
-----------------------------------------------------
On 2026-07-30 this driver printed "pass 86, fail 0, skip 82" and the nightly digest rendered that as
the words "all green", while every defect the next day's audit found was already sitting in the
fleet. Nearly half the checked surface was not evaluated and the report still read as a clean sheet.

So a run now ends with an explicit VERDICT line carrying a COVERAGE fraction, and the caller is meant
to quote that line rather than compose its own adjective from the counts. GREEN is allowed to mean
only "nothing that was evaluated failed", and the same line says out loud how much was evaluated.
Wording that hides a skip inside a green headline is the bug, not a formatting preference.

THE ONE INVARIANT THAT MAKES THE STATUSES MEAN ANYTHING
-------------------------------------------------------
    UNKNOWN means "this run could not OBSERVE the answer". It never means "the answer was bad."

That distinction is the whole reason this file was rewritten on 2026-07-30. The workflow check used
to stat the LOCAL clone and print PASS, so a guard workflow that was committed but never pushed
scored green on a PUBLIC repo whose remote carried no guard at all (claude-codex-memory-sync was
exactly this, for as long as the check existed). The CI check asked only about pii-guard, so
promotion-assistant printed PASS while its dash-guard had been red since 2026-07-24. And UNKNOWN was
defined as never-failing, which was right for "gh is not installed" and catastrophically wrong for
"this public repo has no guard workflow at all" -- a real finding wearing an UNKNOWN costume.

So the two are now separated by construction. Infrastructure that is unavailable (no gh, not
authenticated, rate limited, offline, remote HEAD not present locally) yields UNKNOWN, is printed
under UNOBSERVED with its reason, and never fails the run. A definitive negative answer from a
remote we did reach is a FAIL. Because UNKNOWN can only ever be produced by the first case, the old
sentence "UNKNOWN never affects the exit code" stays true without hiding anything.

THE FIVE CHECKS
---------------
  junctions   every junction/symlink under ~/.claude/skills resolves to a directory that exists.
              Failure mode: a repo gets moved (CodesSelf -> CodesClaude, 2026-07-22) and the skill
              silently vanishes from the agent's library with no error anywhere. A skills dir that
              is missing or holds no junctions at all reports UNKNOWN rather than nothing: a check
              that emits zero rows reads as green, which is the same lie in a quieter voice.
  workflow    visibility PUBLIC implies the REMOTE default branch carries every guard workflow
              (pii-guard and dash-guard -- the same pair check_conformance.py already requires
              locally). The remote is interrogated over gh, falling back to `git ls-remote` plus a
              local `ls-tree` of the remote HEAD when that sha is already in the object store. The
              LOCAL working tree is never consulted, because the file being on this disk is not
              evidence that it is on GitHub, and GitHub is where CI runs.
              Entries with no local clone under the fleet root are SKIPPED, not failed: the
              visibility map outlives the working copies it was built from and names repos that are
              not checked out here (and third-party forks, whose CI is not ours to install).
  conformance check_conformance.py over every repo carrying .claude-plugin/plugin.json. Repos
              without one are SKIPPED out loud, so that a deleted plugin.json shows up as a repo
              dropping out of coverage instead of as one fewer line nobody counted. A repo whose
              linter exits 0 but printed warnings is reported WARN here, not PASS: the always-loaded
              SKILL.md size gate and the shard-pointer check both have findings no edit fixes today,
              and rolling those up into a PASS is how the last green total was manufactured.
  budget      budget_check.py, the one check that is about the LIBRARY rather than any repo: do the
              installed skill descriptions still fit in the system prompt. Past the cutoff they are
              truncated silently, so a skill keeps existing, keeps having a description, and simply
              stops being visible to the agent. A skill past that cutoff FAILS whatever tier it
              belongs to: invisibility is a capability loss no matter who wrote the description, and
              the lever (uninstall one, or trim ours, since the cutoff is a running total) is the
              operator's in both cases. Only the per-skill description CAP stays limited to our
              tier, because third-party wording is genuinely not ours to edit.
  databoundary the INVERSE data-boundary assertion, which is the one check that would have caught
              the 2026-07 leak: data_boundary.py proves the REPO holds no real-run output, and this
              proves the reverse, that the resolved real-run output directory is not somewhere the
              world can read. Both directions were nominally true and the leak still happened,
              because nobody ever looked from this end.
              The predicate is PUBLIC-or-UNKNOWN, not in-git. DATA lives in the PRIVATE companion
              repo, versioned; a data dir inside a private repo PASSES and the row names that repo,
              so a reader can tell an examined-and-approved row from a skipped one. Unknown
              visibility FAILS CLOSED, mirroring the PII gate's treatment of an unknown remote.
              Not-initialized is not a failure: an uninitialized tool is the correct shipping state.
              If git cannot be run at all the answer is UNKNOWN, never PASS -- a missing git used to
              silently clear every repo in this check.
              Visibility comes from LIVE gh, with the map as a bounded-age offline fallback: see
              VisibilityOracle for why the reverse order made the whole check defeatable by one
              stale line of JSON.
  ci          EVERY workflow found on the remote is actually GREEN ON THE DEFAULT BRANCH, reported
              one row per (repo, workflow) so a red dash-guard cannot hide behind a green pii-guard.
              "CI is the authority" is the load-bearing sentence of the whole doctrine and nothing
              observed whether that authority was passing.
              EVERY is literal, and it was not until 2026-07-31. This check used to interrogate the
              two names in GUARD_WORKFLOWS, so every other workflow the fleet authors (gate,
              heartbeat, test, memory health) was invisible to the fleet report, and repos that are
              PRIVATE were not interrogated at all. That is how a report can print "34 of 34 green"
              on a day when a repo's own gate workflow is concluding success over a log that reads
              "RESULT: BLOCK". Rows are now CLASSIFIED, not filtered: guard (mandated) or other
              (anything else we wrote), and a red run FAILS the row in both tiers. The only escape
              is CI_WARN_ONLY, one named workflow on one named repo, with a reason printed every
              run. See its note for why a severity tier would just rebuild the hiding place.
              Degrades to UNKNOWN (never FAIL,
              never blocking) when gh is missing, unauthenticated, rate limited, or the workflow has
              no run on the default branch -- GitHub expires run history, so "no runs" is an absence
              of evidence, not evidence of absence. The presence question is the workflow check's
              job, and there it can FAIL.
              The branch filter is not a detail. Without it the probe reported the newest run on ANY
              ref, so a green push to a topic branch was printed as the default branch's status: on
              2026-07-22 daily-hotspots would have shown PASS for pii-guard from a green run on
              feat/source-coverage-selfevolve while master's own newest run was a FAILURE. Every
              other check here interrogates the remote DEFAULT branch; this one silently did not.

OUTPUT CONTRACT
---------------
Read-only: there is nothing in here that writes to any repo, including no `git fetch`. Exits nonzero
if any row is FAIL. UNKNOWN and SKIP never affect the exit code, which is safe precisely because
UNKNOWN can no longer carry a finding. Prints a human-readable report to stdout and writes a
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
BUDGET = os.path.join(HERE, "budget_check.py")

DEFAULT_SKILLS_DIR = os.path.expanduser("~/.claude/skills")
DEFAULT_CODE_ROOT = os.path.expanduser("~/CodesClaude")
DEFAULT_VISIBILITY = os.path.expanduser("~/.pii-guard/visibility.json")
# The status file is REAL-RUN OUTPUT: it carries repo names, resolved machine paths and failure
# text. By this repo's own rule that lands in the private store, never inside the repo and never
# hardcoded into another tool's internals, so the default is the standalone shape tools/datadir.py
# defines for this skill. A caller that wants it filed next to its other maintenance artifacts
# passes --status-json; that is the caller's layout decision to make, not this tool's.
DEFAULT_STATUS = os.path.expanduser("~/.skill-smith-data/fleet-check-status.json")

# WARN is "evaluated, not clean, and no edit available today makes it clean". It is deliberately
# NOT a pass (a pass would hide it) and deliberately NOT a fail (a nightly that is permanently red
# for something unfixable is a nightly the operator learns to ignore, which is the failure mode this
# whole file exists to avoid). It counts toward COVERAGE, because it was looked at.
PASS, FAIL, WARN, SKIP, UNKNOWN = "PASS", "FAIL", "WARN", "SKIP", "UNKNOWN"
STATUSES = (PASS, FAIL, WARN, SKIP, UNKNOWN)
# Statuses that mean "this row was actually evaluated". SKIP and UNKNOWN are the silence.
EVALUATED = (PASS, FAIL, WARN)

# The guard workflows every PUBLIC repo must carry ON THE REMOTE. This is not a new policy invented
# here: check_conformance.py already requires .github/workflows/pii-guard.yml and dash-guard.yml in
# the local tree. This check asserts the same pair actually reached GitHub, which is the only place
# the assertion has teeth.
GUARD_WORKFLOWS = ("pii-guard", "dash-guard")

# GUARD_WORKFLOWS is a PRESENCE policy: these two must EXIST on every public remote. It is not, and
# must never again be, the list of workflows whose RESULT gets read. Until 2026-07-31 check_ci
# interrogated exactly this pair, so every other workflow the fleet authors was invisible to the
# fleet report: market-intel's `gate`, the `heartbeat` jobs, `Test`, `memory-health-guard`. On
# 2026-07-31 that printed "34 of 34 green" while market-intel's gate workflow was concluding success
# over a log that said "RESULT: BLOCK (3 blocking issue(s))". The name filter was the reason nobody
# could see it. check_ci now reads EVERY workflow on each public remote and CLASSIFIES it.
#
# The classification has two tiers and both of them FAIL on red. The tiers differ only in what the
# row is called, because the operator reading the report needs to know whether a red row breaches
# fleet policy or is just a broken job:
#
#   guard  a workflow named in GUARD_WORKFLOWS. Red = a mandated guard is down.
#   other  anything else this fleet wrote. Red = a workflow we authored, in a repo we own, is
#          failing.
#
# WHY "other" FAILS RATHER THAN WARNS. WARN in this file means "evaluated, not clean, and no edit
# available today makes it clean" (see the PASS/FAIL/WARN note above). That does not describe a red
# workflow in a repo we control: there is always an edit available, namely fix it or delete it. If
# a non-guard red only warned, then the exact defect this change exists to close, a real gate going
# red without anything going red, would be rebuilt one layer down: instead of hiding behind a name
# filter it would hide behind a severity tier. So redness fails, whoever wrote the workflow.
#
# The escape hatch is deliberately narrow, per workflow and per repo, never per tier: an entry in
# CI_WARN_ONLY downgrades one named workflow on one named repo to WARN, and it has to carry a
# reason that gets printed in the row. Empty means no exemptions exist, which is the intended
# steady state. Anyone adding one is stating in writing which specific job they have chosen to stop
# believing, and the report keeps saying so on every run.
CI_WARN_ONLY = {
    # ("owner/repo", "workflow-file.yml"): "why this job's redness is not actionable here",
}


# --- tiny helpers --------------------------------------------------------------------------------
def run(args, cwd=None, timeout=60, env=None):
    """Run a command, never raise. Returns (rc, stdout, stderr); rc is None on timeout."""
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, env=env,
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
    """Tri-state: (True, toplevel) inside a worktree, (False, "") outside, (None, reason) unknown.

    The None arm is load-bearing. This used to collapse "git said no" and "git could not run at all"
    into the same False, so a machine with no git on PATH silently reported every data dir as
    OUTSIDE a worktree -- a clean green sheet produced by never asking the question. Only an answer
    git actually gave is allowed to clear a path.
    """
    rc, so, se = run(["git", "-C", path, "rev-parse", "--show-toplevel"], timeout=20)
    if rc is None:
        return None, "could not run git: %s" % (first_line(se) or "no result")
    if rc == 0 and first_line(so):
        return True, first_line(so)
    err = (se or "").lower()
    if "not a git repository" in err or "no such file" in err or "cannot change to" in err:
        return False, ""
    if rc == 0:
        return None, "git printed no toplevel and no error"
    return False, ""


# --- observing the REMOTE, without writing to any repo --------------------------------------------
def _infra_error(text):
    """True when a gh/git failure is about the plumbing rather than about the repo's contents."""
    e = (text or "").lower()
    return any(k in e for k in (
        "auth", "login", "token", "rate limit", "could not resolve", "network", "timeout",
        "timed out", "dial tcp", "offline", "connection", "tls", "proxy", "503", "502", "500"))


def _is_404(text):
    e = (text or "").lower()
    return "404" in e or "not found" in e


def _remote_workflows_via_gh(gh, slug, timeout):
    """(names, reason). names is a list when OBSERVED (possibly empty), else None + why."""
    # Probe the repo first. A successful probe proves the remote is reachable AND that our token can
    # see this repo, which is what licenses reading a later 404 as "the directory is not there"
    # rather than "we were not allowed to look". GitHub returns 404 for both, so without this first
    # call the two are indistinguishable and a missing guard could be mistaken for a permission
    # problem (or, far worse, the other way around).
    rc, so, se = run([gh, "api", "repos/%s" % slug, "--jq", ".default_branch"], timeout=timeout)
    if rc != 0:
        return None, "gh could not reach %s: %s" % (slug, first_line(se) or "exit %s" % rc)
    branch = first_line(so)
    if not branch:
        return None, "gh returned no default branch for %s" % slug
    rc, so, se = run([gh, "api", "repos/%s/contents/.github/workflows?ref=%s" % (slug, branch),
                      "--jq", ".[].name"], timeout=timeout)
    if rc == 0:
        return sorted(ln.strip() for ln in so.splitlines() if ln.strip()), ""
    err = first_line(se) or "exit %s" % rc
    if _infra_error(err):
        return None, "gh failed on %s@%s: %s" % (slug, branch, err)
    if _is_404(err):
        # Reachable repo, reachable branch, no such directory. That is an ANSWER, not a gap.
        return [], ""
    return None, "gh failed on %s@%s: %s" % (slug, branch, err)


def _remote_workflows_via_git(path, timeout):
    """Same contract, over git alone, still without fetching anything.

    `git ls-remote` asks the server for its current HEAD sha. If that exact commit is already in the
    local object store then the tree hanging off it IS the remote's tree, byte for byte, and reading
    it locally is a genuine observation of the remote rather than of the working copy. If the object
    is absent we would have to fetch to find out, and this tool does not write to repos, so the
    honest answer there is UNKNOWN.
    """
    if not path:
        return None, "no local clone to ask about the remote"
    rc, so, se = run(["git", "-C", path, "ls-remote", "--symref", "origin", "HEAD"], timeout=timeout)
    if rc != 0:
        return None, "git ls-remote failed: %s" % (first_line(se) or "exit %s" % rc)
    sha = ""
    for ln in (so or "").splitlines():
        parts = ln.split()
        if len(parts) >= 2 and parts[-1] == "HEAD" and not ln.startswith("ref:"):
            sha = parts[0]
            break
    if not sha:
        return None, "git ls-remote returned no HEAD sha"
    rc, _so, _se = run(["git", "-C", path, "cat-file", "-e", "%s^{commit}" % sha], timeout=timeout)
    if rc != 0:
        return None, ("remote HEAD %s is not in the local object store; reading it would require a "
                      "fetch and this tool never writes to a repo" % sha[:12])
    rc, so, se = run(["git", "-C", path, "ls-tree", "--name-only", sha, ".github/workflows/"],
                     timeout=timeout)
    if rc != 0:
        return None, "git ls-tree failed: %s" % (first_line(se) or "exit %s" % rc)
    return sorted(os.path.basename(ln.strip()) for ln in so.splitlines() if ln.strip()), ""


def remote_workflow_files(slug, path, timeout, offline=False):
    """(names, reason) for .github/workflows on the REMOTE default branch.

    names is a list (possibly empty) when the remote answered, None when it could not be observed.
    Never consults the working tree: an unpushed file is not CI.
    """
    if offline:
        return None, "offline mode: the remote was not contacted"
    reasons = []
    gh = shutil.which("gh")
    if gh:
        names, why = _remote_workflows_via_gh(gh, slug, timeout)
        if names is not None:
            return names, ""
        reasons.append(why)
    else:
        reasons.append("gh not on PATH")
    names, why = _remote_workflows_via_git(path, timeout)
    if names is not None:
        return names, ""
    reasons.append(why)
    return None, "; ".join(r for r in reasons if r)


def guards_present(names):
    """Which GUARD_WORKFLOWS a remote file listing contains, by bare name."""
    stems = {os.path.splitext(n)[0].lower() for n in names or []}
    return [g for g in GUARD_WORKFLOWS if g in stems]


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
        # A check that returns zero rows prints "pass 0, fail 0" and reads exactly like a clean
        # sheet. It is not one: nothing was looked at. Say that out loud instead.
        c.note = "skills dir does not exist; nothing was inspected"
        c.add(UNKNOWN, skills_dir, "no such directory; deployment state unobserved")
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
        c.add(UNKNOWN, skills_dir, "contains no junctions; nothing to resolve")
    return c


# --- check 2: PUBLIC implies the guard workflows are ON THE REMOTE --------------------------------
def check_workflow(visibility_path, slugs, code_root, timeout=30, offline=False):
    """Assert the guard workflows exist on the REMOTE default branch of every PUBLIC repo.

    The predecessor stat()ed the local clone, which answers a question nobody asked. A workflow file
    is only CI once GitHub has it: committed-but-unpushed, or sitting dirty in the worktree, both
    scored PASS while the public remote was completely ungated.

    The result is hung on the Check as .remote_workflows so the CI check can ask about exactly the
    workflows that were observed to exist, instead of guessing a name and reading the resulting
    "no such workflow" error as a shrug.

    Two listings are hung on the Check, and they answer different questions:
      .remote_workflows      the GUARD subset, which is what this check's own PASS/FAIL is about.
      .all_remote_workflows  every workflow file observed on the remote default branch, which is
                             what check_ci reads. The full listing was always fetched here and then
                             thrown away; keeping it is what lets the CI check stop being a
                             hardcoded pair of names.
    """
    c = Check("workflow", "visibility PUBLIC implies %s on the REMOTE default branch"
              % " + ".join(GUARD_WORKFLOWS))
    c.remote_workflows = {}
    c.all_remote_workflows = {}
    try:
        with open(visibility_path, encoding="utf-8") as f:
            vis = json.load(f)
    except (OSError, ValueError) as e:
        c.note = "visibility map unreadable: %s" % e
        c.add(UNKNOWN, os.path.basename(visibility_path), str(e))
        return c
    c.note = ("the REMOTE is interrogated, never the working tree; entries with no clone under %s "
              "are skipped, a fork of someone else's repo is not ours to gate" % code_root)
    for slug in sorted(k for k, v in vis.items() if str(v).upper() == "PUBLIC"):
        path = slugs.get(slug)
        if path is None:
            c.add(SKIP, slug, "no local clone")
            continue
        names, why = remote_workflow_files(slug, path, timeout, offline=offline)
        if names is None:
            # Could not look. Say so; do not award a pass for a question never asked.
            c.add(UNKNOWN, slug, "remote not observed: %s" % why)
            continue
        found = guards_present(names)
        c.remote_workflows[slug] = found
        c.all_remote_workflows[slug] = list(names)
        missing = [g for g in GUARD_WORKFLOWS if g not in found]
        if missing:
            c.add(FAIL, slug, "PUBLIC but the remote default branch has no %s (remote workflows: %s)"
                  % (", ".join(missing), ", ".join(names) or "none"))
        else:
            c.add(PASS, slug, "remote carries %s" % ", ".join(found))
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
            # Spec v1 does not apply, but say so. Silently dropping the repo means a plugin.json
            # that gets deleted or renamed removes the repo from coverage with no trace anywhere.
            c.add(SKIP, name, "no .claude-plugin/plugin.json")
            continue
        rc, so, se = run([sys.executable, CONFORMANCE, path], timeout=timeout)
        tail = [ln.strip() for ln in so.splitlines() if "passed" in ln]
        score = tail[-1] if tail else ""
        warns = [ln.strip() for ln in so.splitlines() if ln.strip().startswith("[WARN]")]
        if rc is None:
            c.add(UNKNOWN, name, se or "no result")
        elif rc == 0 and warns:
            # Exit 0 with warnings is not a clean sheet, and the linter's own summary line already
            # carries the count. Surfacing it as PASS is exactly the rounding that produced a green
            # total over a fleet full of findings.
            c.add(WARN, name, score + " | " + "; ".join(w[len("[WARN]"):].strip().split("  -> ")[0]
                                                        for w in warns))
        elif rc == 0:
            c.add(PASS, name, score)
        else:
            fails = [ln.strip() for ln in so.splitlines() if ln.strip().startswith("[FAIL]")]
            detail = score or first_line(se) or "exit %s" % rc
            if fails:
                detail += " | " + "; ".join(f[len("[FAIL]"):].strip() for f in fails)
            c.add(FAIL, name, detail)
    return c


# --- check 4: does the installed library still fit in the system prompt? --------------------------
def check_budget(skills_dir, code_root, timeout):
    """Run budget_check.py (G3) once for the whole machine.

    Every other check here is per repo. This one is per LIBRARY, and it is the only check whose
    failure is invisible by construction: past the cutoff a skill's description is dropped from the
    prompt with no error anywhere, so the skill simply never fires and nothing says why.

    Exit-code contract of budget_check.py:
      0  nothing is past the cutoff and no description of ours is over the per-skill cap
      1  a finding: either one of OUR descriptions is too long, or SOME skill (any tier) is past
         the truncation cutoff and therefore invisible to the agent
      2  nothing to measure, which is a state and not a failure

    WHY THE TIER NO LONGER DECIDES THE VERDICT
    Until 2026-07-31 only OUR tier could fail this, which meant the one harm the check exists to
    find could not turn it red: four third-party skills were past the cutoff and invisible, and the
    tool exited 1 only because two of our own descriptions were long. Trimming those two would have
    turned the check green with four skills still missing from the prompt. Being invisible is a
    capability loss whoever authored the description, so the CONDITION fails now regardless of tier.
    The operator still never edits a third-party description; the lever is uninstalling one or
    trimming ours, and budget_check.py prints exactly that.
    """
    c = Check("budget", "installed skill descriptions still fit in the system prompt (G3)")
    if not os.path.isfile(BUDGET):
        c.note = "budget_check.py not found next to this script"
        c.add(UNKNOWN, "budget_check.py", BUDGET)
        return c
    c.note = ("a skill past the truncation cutoff FAILS whatever tier it is in, because it is "
              "invisible to the agent; only the per-skill description CAP is limited to our tier, "
              "since third-party wording is not the operator's to edit")
    rc, so, se = run([sys.executable, BUDGET, "--skills-dir", skills_dir, "--code-root", code_root],
                     timeout=timeout)
    lines = [ln.strip() for ln in (so or "").splitlines() if ln.strip()]
    status_line = next((ln for ln in lines if ln.startswith("STATUS:")), "")
    ends_at = next((ln for ln in lines if ln.startswith("user tier ends at")), "")
    # Read the COUNT off budget_check.py's own machine-readable line. Deriving it by grepping for
    # the phrases that name a victim double-counted the moment those phrases also appeared in the
    # FAIL list, and reported "8 skill(s) past the cutoff" over four skills. A caller that infers a
    # number from prose is a caller that will eventually infer the wrong one.
    n_past = 0
    for ln in lines:
        if ln.startswith("TRUNCATED:"):
            try:
                n_past = int(ln.split(":", 1)[1].strip().split()[0])
            except (IndexError, ValueError):
                n_past = 0
            break
    past = n_past > 0
    detail = " | ".join(x for x in (status_line, ends_at,
                                    "%d skill(s) past the cutoff" % n_past if n_past else "") if x)
    if rc is None:
        c.add(UNKNOWN, "library", se or "no result")
    elif rc == 2:
        c.add(UNKNOWN, "library", detail or "nothing to measure")
    elif rc == 0:
        # rc==0 is now supposed to imply nothing is past the cutoff. The WARN arm stays as a
        # disagreement detector: if the tool ever exits 0 while its own output names a truncated
        # skill, the two have drifted and this must not round up to PASS.
        c.add(WARN if past else PASS, "library", detail or "within budget")
    else:
        c.add(FAIL, "library", detail or first_line(se) or "exit %s" % rc)
    return c


# --- check 5: the inverse data boundary -----------------------------------------------------------
def load_datadir(path, modname):
    spec = importlib.util.spec_from_file_location(modname, path)
    if spec is None or spec.loader is None:
        raise ImportError("no loader for %s" % path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def origin_slug(repo_path, timeout=20):
    """owner/repo for a worktree's origin, or None when it has no origin at all."""
    rc, so, _se = run(["git", "-C", repo_path, "remote", "get-url", "origin"], timeout=timeout)
    if rc != 0:
        return None
    return slug_from_url(first_line(so))


def parse_stamp(text):
    """Epoch seconds from an ISO-8601 timestamp, or None if it is absent or unparseable."""
    s = str(text or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def human_age(seconds):
    if seconds is None:
        return "unknown"
    s = abs(float(seconds))
    if s < 3600:
        return "%.0f min" % (s / 60.0)
    if s < 2 * 86400:
        return "%.1f h" % (s / 3600.0)
    return "%.1f days" % (s / 86400.0)


class VisibilityOracle:
    """PUBLIC / PRIVATE / UNKNOWN for a slug. LIVE gh first, the map only as an aged fallback.

    WHY THE ORDER FLIPPED (2026-07-31)
    ----------------------------------
    This used to read ~/.pii-guard/visibility.json FIRST and ask gh only on a miss. That made one
    line of cached JSON able to outvote GitHub forever. Poisoning a copy of the map with
    `{"daizedong/skill-smith": "PRIVATE"}` -- a genuinely PUBLIC repo -- made check_data_boundary
    print `PASS ... [PRIVATE per visibility map]` over a data dir sitting in a public repo. Nothing
    on this machine refreshes that file, so the entry would have said PRIVATE until someone
    remembered to rerun refresh_visibility.py, and the event this whole control exists to survive is
    precisely a repo being flipped from private to PUBLIC on GitHub. A cache that can never be wrong
    is not a cache, it is an assertion.

    THE TRADE THAT WAS MADE
    -----------------------
    Three fixes were on the table. A TTL alone is the cheapest, but it does not close the hole: a
    freshly written map entry is inside any window, so the poisoned-copy demonstration above still
    passes. Scheduling refresh_visibility.py narrows the drift but leaves a window of exactly the
    refresh interval, and it makes correctness depend on a scheduled task nobody watches -- the same
    "remember to run the script" design that visibility_of.py already learned not to trust. So the
    order is inverted instead: gh is asked live, and the map is consulted ONLY when gh cannot answer
    (--offline, gh missing, unauthenticated, rate limited).

    The cost is real and was accepted deliberately: one `gh repo view` per DISTINCT slug that this
    check actually reaches, which is the handful of skills that have both tools/datadir.py and an
    initialized data dir, not the 119 keys in the map. Answers are cached per run. That is small
    beside the two gh calls per public repo the workflow check already makes.

    The fallback is bounded so the property survives even offline: the map may only vote while it is
    younger than MAX_MAP_AGE_S, measured from the `_refreshed` stamp refresh_visibility.py writes
    into it. An unstamped map, a stamp in the future, or a stamp past the window all behave as
    UNKNOWN, which already fails closed. So a map entry cannot indefinitely outvote reality by any
    path: online it never gets to vote at all, offline its vote expires.

    When gh and the map DISAGREE the live answer wins and the row says the map is stale, because a
    disagreement is itself the finding.

    Never WRITES the map back: fleet_check's contract is read-only, and a checker that mutates
    machine state to answer its own question is a checker whose second run tests something different
    from its first.
    """

    # How long a cached visibility answer may still vote once gh has gone silent. Visibility changes
    # are rare and deliberate, so this is not tuned to how fast the fact changes -- it is tuned to
    # how long a machine may sit offline before "I cannot see GitHub" should stop being papered over
    # with an old answer. A week is long enough that a normal disconnection never turns the check
    # red, and short enough that an abandoned map cannot keep clearing a repo indefinitely.
    MAX_MAP_AGE_S = 7 * 24 * 3600
    STAMP_KEY = "_refreshed"        # reserved: a slug always contains "/", so it cannot collide

    def __init__(self, path, offline=False, timeout=30, max_age=None, now=None):
        self.offline = offline
        self.timeout = timeout
        self.max_age = self.MAX_MAP_AGE_S if max_age is None else max_age
        self.now = now              # epoch seconds; injectable so age is testable without sleeping
        self.error = ""
        self.cache = {}
        self.map = {}
        self.stamp = None
        try:
            with open(path, encoding="utf-8") as f:
                m = json.load(f)
        except (OSError, ValueError) as e:
            self.error = str(e)
            m = {}
        if isinstance(m, dict):
            self.stamp = parse_stamp(m.get(self.STAMP_KEY))
            self.map = {str(k).lower(): str(v).upper()
                        for k, v in m.items() if k != self.STAMP_KEY}

    def map_age(self):
        """(age_seconds, trouble). trouble is "" only when the map is fresh enough to vote."""
        if self.stamp is None:
            return None, ("it carries no %s stamp, so its age cannot be established; run "
                          "refresh_visibility.py" % self.STAMP_KEY)
        age = (time.time() if self.now is None else self.now) - self.stamp
        if age < 0:
            return age, "its %s stamp is in the future" % self.STAMP_KEY
        if age > self.max_age:
            return age, ("it was last refreshed %s ago, past the %s trust window; run "
                         "refresh_visibility.py" % (human_age(age), human_age(self.max_age)))
        return age, ""

    def _mapped(self, slug):
        v = self.map.get(slug)
        return "PRIVATE" if v == "INTERNAL" else v

    def _ask_gh(self, slug):
        """(visibility, how) from a live query, or (None, why-it-could-not-answer)."""
        if self.offline:
            return None, "--offline forbids asking gh"
        gh = shutil.which("gh")
        if not gh:
            return None, "gh is not on PATH"
        # Both identities: a private repo owned by one account is a 404 to the other's token, so
        # asking with only one of them turns "private, and you cannot see it" into "no answer".
        # visibility_of.py handles this with `gh auth switch`, which rewrites the machine's ACTIVE
        # account. This tool is read-only, so it borrows each token for one child process instead
        # and leaves the active account exactly where it found it.
        for acct in (None,):
            env = None
            if acct:
                rc, tok, _se = run([gh, "auth", "token", "--user", acct], timeout=self.timeout)
                tok = first_line(tok)
                if rc != 0 or not tok:
                    continue
                env = dict(os.environ, GH_TOKEN=tok)
            rc, so, _se = run([gh, "repo", "view", slug, "--json", "visibility",
                               "-q", ".visibility"], timeout=self.timeout, env=env)
            if rc != 0:
                continue
            got = first_line(so).upper()
            if got in ("PUBLIC", "PRIVATE", "INTERNAL"):
                return ("PRIVATE" if got == "INTERNAL" else got,
                        "gh" + (" as %s" % acct if acct else ""))
        return None, "gh could not answer for %s" % slug

    def _from_map(self, slug, gh_why):
        cached = self._mapped(slug)
        if cached not in ("PUBLIC", "PRIVATE"):
            return "UNKNOWN", "%s, and %s is not in the visibility map" % (gh_why, slug)
        age, trouble = self.map_age()
        if trouble:
            return "UNKNOWN", ("%s, and the map's cached %s cannot be trusted because %s"
                               % (gh_why, cached, trouble))
        return cached, "the visibility map, refreshed %s ago (%s)" % (human_age(age), gh_why)

    def visibility(self, slug):
        if not slug:
            return "UNKNOWN", "no origin remote"
        if slug in self.cache:
            return self.cache[slug]
        live, how = self._ask_gh(slug)
        if live:
            cached = self._mapped(slug)
            if cached in ("PUBLIC", "PRIVATE") and cached != live:
                how += "; the visibility map still says %s and is STALE" % cached
            ans = (live, how)
        else:
            ans = self._from_map(slug, how)
        self.cache[slug] = ans
        return ans


def check_data_boundary(visibility_path, repos, offline=False, timeout=30):
    """Assert no skill's real-run output resolves into a repo the world can read.

    WHY THE PREDICATE CHANGED (2026-07-31)
    --------------------------------------
    This used to assert "the resolved data dir is not inside a git worktree". That is the wrong
    question, and it condemned the correct answer. Real-run output LIVES IN the private companion
    repo, versioned and backed up -- that is what the doctrine has always said and what the operator
    has now confirmed explicitly. Implementing "must not reach a public repo" as "must not be in
    git" turned the fleet's intended shape into a red row: market-intel FAILED here for keeping its
    ledger in its private companion repo, an agent then moved that ledger OUT to a loose unversioned
    directory to satisfy the check, and all the while daily-hotspots kept a tracked ledger in ITS
    private companion repo and nothing objected, because this check could not even see it. Two
    contradictory shapes in one fleet, and the checker endorsing neither consistently.

    The predicate is now the one that matches the harm: PUBLIC or UNKNOWN fails, PRIVATE passes and
    SAYS SO, naming the repo, so a reader can tell "the control looked and approved this" apart from
    "the control skipped it". UNKNOWN fails closed, matching how the PII gate treats an unknown
    remote: marking a remote private is a deliberate visible act, silently clearing a public one is
    invisible and permanent.
    """
    c = Check("databoundary",
              "resolved real-run data dirs are never inside a PUBLIC or UNKNOWN repo")
    c.note = ("DATA belongs in the PRIVATE companion repo, versioned; a data dir inside a private "
              "repo PASSES and the repo is named. Unknown visibility FAILS CLOSED. An uninitialized "
              "skill has no data dir yet, which is the correct shipping state. Visibility comes from "
              "LIVE gh; the map only votes when gh cannot answer, and only while it is younger than "
              "%s" % human_age(VisibilityOracle.MAX_MAP_AGE_S))
    oracle = VisibilityOracle(visibility_path, offline=offline, timeout=timeout)
    if oracle.error:
        c.note += " | visibility map unreadable (%s): there is no fallback left" % oracle.error
    else:
        age, trouble = oracle.map_age()
        c.note += (" | the map %s" % trouble if trouble
                   else " | the map was refreshed %s ago" % human_age(age))
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
            # The resolver's own refusal is a FINDING, not a gap. datadir.py raises
            # DataDirInsideOwnRepo when a data dir resolves inside the skill repo that ships it --
            # the in-repo fallback shape. Reporting that as UNKNOWN would file a caught violation
            # under "could not observe", which is the exact rounding this file exists to prevent.
            if type(e).__name__ == "DataDirInsideOwnRepo":
                c.add(FAIL, name, first_line(str(e)) or str(e))
            else:
                c.add(UNKNOWN, name, "cannot load tools/datadir.py: %s" % e)
            continue
        if resolved is None:
            c.add(SKIP, name, "not initialized")
            continue
        resolved = str(resolved)
        if not os.path.isdir(resolved):
            # resolve_data_dir() is supposed to return only existing dirs, so this means a vendored
            # copy has drifted. It matters because `git -C <missing>` exits nonzero, which the
            # worktree probe would otherwise read as a clean "outside any repo".
            c.add(UNKNOWN, name, "resolver returned %s, which does not exist" % resolved)
            continue
        inside, top = in_git_worktree(resolved)
        if inside is None:
            c.add(UNKNOWN, name, "%s: %s" % (resolved, top))
            continue
        if not inside:
            # A plain directory outside every worktree. Nothing can publish it, so it clears this
            # check -- but it is NOT the preferred shape: unversioned means no history and no
            # backup for the one artifact that records real runs.
            c.add(PASS, name, "%s (outside any git worktree; unversioned)" % resolved)
            continue
        slug = origin_slug(top, timeout=timeout)
        vis, why = oracle.visibility(slug)
        where = "%s -> %s" % (resolved, slug or top)
        if vis == "PRIVATE":
            c.add(PASS, name, "%s [PRIVATE per %s] versioned in the private companion repo"
                  % (where, why))
        elif vis == "PUBLIC":
            c.add(FAIL, name, "data dir %s is inside PUBLIC repo %s (per %s) -- real-run output "
                              "must never reach a public repo" % (resolved, slug, why))
        else:
            c.add(FAIL, name, "data dir %s is inside repo %s whose visibility could not be "
                              "established (%s) -- failing closed" % (resolved, slug or top, why))
    return c


# --- check 6: is the authority green? --------------------------------------------------------------
GREEN = ("success",)
RED = ("failure", "timed_out", "cancelled", "startup_failure", "action_required")


def default_branch(gh, slug, timeout, cache):
    """(branch, why-not) for a slug's remote default branch, cached per run."""
    if slug not in cache:
        rc, so, se = run([gh, "api", "repos/%s" % slug, "--jq", ".default_branch"], timeout=timeout)
        b = first_line(so) if rc == 0 else ""
        cache[slug] = (b, "" if b else (first_line(se) or "gh exit %s" % rc))
    return cache[slug]


def ci_targets(wf_check, visibility_path, slugs, timeout, offline=False):
    """[(slug, names_or_None, why, visibility)] for EVERY repo of ours that has a clone here.

    check_workflow only walks the PUBLIC entries, because guard PRESENCE is a public-remote policy.
    CI greenness is not, and at least one PRIVATE repo here carries a real guard workflow that no
    fleet report has ever read. A private repo's CI going red is exactly as much a broken thing as a
    public one's, so the listing is fetched for the private repos too rather than reusing a set that
    was assembled to answer a different question.

    Listings already obtained by check_workflow are reused verbatim, so the public repos cost no
    extra API calls.
    """
    seen = getattr(wf_check, "all_remote_workflows", {}) or {}
    try:
        with open(visibility_path, encoding="utf-8") as f:
            vis = {k: str(v).upper() for k, v in json.load(f).items()}
    except (OSError, ValueError) as e:
        out = [(s, n, "", "PUBLIC") for s, n in sorted(seen.items())]
        out.append(("(visibility map)", None,
                    "unreadable: %s; only PUBLIC repos were enumerated" % e, "UNKNOWN"))
        return out
    out = [(s, n, "", vis.get(s, "UNKNOWN")) for s, n in sorted(seen.items())]
    for slug in sorted(vis):
        if slug in seen:
            continue
        path = slugs.get(slug)
        if path is None:
            continue                      # no clone here: not ours to interrogate, and check_workflow
                                          # already records the SKIP for the public ones
        names, why = remote_workflow_files(slug, path, timeout, offline=offline)
        out.append((slug, names, why, vis.get(slug, "UNKNOWN")))
    return out


def workflow_tier(filename):
    """"guard" if this workflow file is one of GUARD_WORKFLOWS, else "other". Never filters."""
    return "guard" if os.path.splitext(filename)[0].lower() in GUARD_WORKFLOWS else "other"


def check_ci(targets, timeout):
    """targets: [(slug, names_or_None, why, visibility), ...] as built by ci_targets().

    names is the FULL workflow listing observed on that slug's remote default branch, or None when
    the listing could not be observed, in which case `why` says so and the repo gets an UNKNOWN row
    rather than vanishing.

    EVERY workflow in the listing is read; see the CI_WARN_ONLY note at the top of this file for
    why a red non-guard workflow fails the row exactly like a red guard does.

    One row per (repo, workflow). The predecessor asked only about pii-guard and titled itself "the
    guard CI is green", so promotion-assistant printed a single confident PASS on 2026-07-30 while
    its dash-guard had been failing since 2026-07-24. A check that names one workflow and reports on
    the category is not a check, it is a headline.

    WHY THE BRANCH FILTER EXISTS (2026-07-31)
    -----------------------------------------
    The query was `gh run list -w <wf> --limit 1`, which is the newest run on ANY ref. Every other
    check in this file interrogates the remote DEFAULT branch, and the sentence this one prints --
    "the guard CI is green" -- is a claim about the branch the world clones. On 2026-07-31 two of
    its 34 green rows were evidence from the topic branch feat/login-handoff-and-depth-gate on
    shopping-aggregator, reported as if they described main. That is survivable only by luck: on
    2026-07-22 daily-hotspots had a GREEN pii-guard run on feat/source-coverage-selfevolve while
    master's own newest pii-guard run was a FAILURE, so this check would have printed PASS over a
    red default branch. A gate that answers a question nobody asked, in the voice of the question
    they did ask, is the defect class this whole file was written against.

    "No run on the default branch" is UNKNOWN, not a silent fallback to whatever run exists. A
    workflow that has only ever fired on topic branches has not yet said anything about the branch
    being asked about, and inventing an answer from the wrong ref is how this started.
    """
    c = Check("ci", "EVERY workflow on EVERY repo of ours is GREEN ON THE DEFAULT BRANCH")
    gh = shutil.which("gh")
    if not gh:
        c.note = "gh not on PATH; CI state unobserved (infrastructure, non-failing)"
        c.add(UNKNOWN, "gh", "not installed")
        return c
    c.note = ("every workflow file on every remote default branch is read, not a hardcoded list, and "
              "PRIVATE repos are read too (a private repo here carries a guard workflow no report "
              "ever saw); rows are tagged guard (%s, mandated) or other (any workflow this fleet wrote), and BOTH "
              "fail on red. Only runs whose head ref IS the remote default branch are counted; "
              "UNKNOWN means the answer could not be OBSERVED and never fails the run; a guard "
              "MISSING from a remote is a FAIL in the workflow check above, not a shrug here"
              % ", ".join(GUARD_WORKFLOWS))
    if not targets:
        c.add(UNKNOWN, "(nothing to ask)", "no repo reported any workflow on its remote")
        return c
    branches = {}
    for slug, workflows, listing_why, visibility in sorted(targets, key=lambda t: t[0]):
        if workflows is None:
            c.add(UNKNOWN, slug, "workflow listing not observed: %s" % (listing_why or "no reason given"))
            continue
        if not workflows:
            # An answered listing that is empty is a FACT, not a gap. Which fact depends on who owns
            # the repo: a PRIVATE companion data repo is supposed to have no CI (guard presence is a
            # public-remote policy), so it is a SKIP that names itself rather than eight permanent
            # WARN rows an operator learns to scroll past. A PUBLIC repo with no workflows at all is
            # a different animal and stays a WARN here; check_workflow above is already FAILing it
            # for the missing mandated guards, so this row is the corroborating detail, not the
            # verdict. Either way the repo is NAMED, which is the part the old name filter got
            # wrong.
            if visibility == "PRIVATE":
                c.add(SKIP, slug, "PRIVATE companion repo with no workflows; CI is not mandated here")
            else:
                c.add(WARN, slug, "%s repo has NO workflow files on its remote default branch"
                      % visibility)
            continue
        branch, why = default_branch(gh, slug, timeout, branches)
        for wf in sorted(workflows):
            tier = workflow_tier(wf)
            name = "%s [%s:%s]" % (slug, tier, wf)
            exempt = CI_WARN_ONLY.get((slug, wf))
            if not branch:
                # Without the default branch there is no question to ask. Reporting the newest run
                # on any ref instead is exactly the bug this arm replaced.
                c.add(UNKNOWN, name, "could not determine the default branch: %s" % why)
                continue
            rc, so, se = run([gh, "run", "list", "-w", wf, "-b", branch, "--limit", "1", "-R", slug,
                              "--json", "conclusion,status,createdAt,headBranch"], timeout=timeout)
            if rc != 0:
                c.add(UNKNOWN, name, first_line(se) or "gh exit %s" % rc)
                continue
            try:
                runs = json.loads(so or "[]")
            except ValueError as e:
                c.add(UNKNOWN, name, "unparseable gh output: %s" % e)
                continue
            if not runs:
                # The file IS on the remote default branch (that is why we are asking). GitHub
                # expires run history, so a dormant repo legitimately has none. Absence of runs is
                # not a red run -- and it is not permission to quote a topic branch's run either.
                c.add(UNKNOWN, name, "no run on the default branch %s (expired, never fired, or the "
                                     "workflow has only ever run on other refs)" % branch)
                continue
            r = runs[0]
            concl = (r.get("conclusion") or "").lower()
            state = (r.get("status") or "").lower()
            when = "%s on %s" % (r.get("createdAt") or "", r.get("headBranch") or branch)
            if state != "completed":
                c.add(UNKNOWN, name, "run %s (%s)" % (state or "unknown state", when))
            elif concl in GREEN:
                c.add(PASS, name, when)
            elif concl in RED:
                detail = "last run %s (%s)" % (concl, when)
                if exempt:
                    # Named, per workflow, per repo, and the reason is printed every single run so
                    # the exemption cannot quietly become the norm.
                    c.add(WARN, name, "%s [CI_WARN_ONLY: %s]" % (detail, exempt))
                else:
                    c.add(FAIL, name, detail)
            else:
                c.add(UNKNOWN, name, "last run %s (%s)" % (concl or "no conclusion", when))
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


def digest_line(tot):
    """The single line a caller is meant to quote verbatim.

    It exists because the caller used to build its own sentence out of the counts and chose the word
    "all green" for a run with 82 unevaluated rows. A verdict and a coverage fraction on one line
    leave no room for that: GREEN can only mean "nothing that was EVALUATED failed", and the same
    line says how much was evaluated.
    """
    ev = tot["pass"] + tot["fail"] + tot["warn"]
    silent = tot["skip"] + tot["unknown"]
    total = ev + silent
    pct = (100.0 * ev / total) if total else 0.0
    verdict = "RED" if tot["fail"] else ("AMBER" if tot["warn"] else "GREEN")
    return ("VERDICT %s | pass %d fail %d warn %d | NOT EVALUATED %d (skip %d, unobserved %d) | "
            "coverage %d%% (%d of %d rows)"
            % (verdict, tot["pass"], tot["fail"], tot["warn"], silent, tot["skip"], tot["unknown"],
               round(pct), ev, total)), verdict


def print_report(checks, started, elapsed):
    print("fleet check  %s  (%.1fs)" % (started, elapsed))
    print("=" * 78)
    for c in checks:
        s = c.summary()
        print("\n[%s] %s" % (c.id, c.title))
        if c.note:
            print("  note: %s" % c.note)
        print_rows(c.rows)
        print("  -> pass %d, fail %d, warn %d, skip %d, unknown %d"
              % (s["pass"], s["fail"], s["warn"], s["skip"], s["unknown"]))
    print("\n" + "=" * 78)
    tot = {k: sum(c.summary()[k] for c in checks)
           for k in ("pass", "fail", "warn", "skip", "unknown")}
    print("TOTAL  pass %d  fail %d  warn %d  skip %d  unknown %d"
          % (tot["pass"], tot["fail"], tot["warn"], tot["skip"], tot["unknown"]))
    if tot["warn"]:
        print("\nWARNINGS (evaluated, not clean, not blocking)")
        for c in checks:
            for status, name, detail in c.rows:
                if status == WARN:
                    print("  %s: %s -- %s" % (c.id, name, detail))
    if tot["fail"]:
        print("\nFAILURES")
        for c in checks:
            for status, name, detail in c.rows:
                if status == FAIL:
                    print("  %s: %s -- %s" % (c.id, name, detail))
    if tot["unknown"]:
        # Printed on purpose and separately. UNKNOWN is now defined as "could not observe", which
        # makes it harmless to the exit code and therefore invisible unless it is listed. An
        # unobserved check is not a passing check, and the operator has to be able to see the
        # difference between a fleet that is clean and a fleet nobody could look at.
        print("\nUNOBSERVED (infrastructure, does not affect exit code)")
        for c in checks:
            for status, name, detail in c.rows:
                if status == UNKNOWN:
                    print("  %s: %s -- %s" % (c.id, name, detail))
    line, _verdict = digest_line(tot)
    print("\n" + line)
    return tot


def write_status(path, checks, tot, started_utc, elapsed, exit_code):
    line, verdict = digest_line(tot)
    payload = {
        "tool": "fleet_check",
        # Bumped from 1: `totals` gained a `warn` key, and `verdict`/`digest`/`coverage` are new.
        # A caller that composes its own adjective out of the counts is how "all green" got printed
        # over a fleet with 82 unevaluated rows, so the wording now ships WITH the numbers.
        "schema": 2,
        "utc": started_utc,
        "duration_s": round(elapsed, 2),
        "exit": exit_code,
        "verdict": verdict,
        "digest": line,
        "coverage": {
            "evaluated": tot["pass"] + tot["fail"] + tot["warn"],
            "not_evaluated": tot["skip"] + tot["unknown"],
        },
        "totals": tot,
        "checks": {c.id: dict(title=c.title, note=c.note, **c.summary()) for c in checks},
        "failures": ["%s: %s -- %s" % (c.id, n, d)
                     for c in checks for s, n, d in c.rows if s == FAIL],
        # Machine-readable twin of the UNOBSERVED block. A caller that only ever reads `failures`
        # cannot tell a clean fleet from an unlooked-at one.
        "unobserved": ["%s: %s -- %s" % (c.id, n, d)
                       for c in checks for s, n, d in c.rows if s == UNKNOWN],
        "warnings": ["%s: %s -- %s" % (c.id, n, d)
                     for c in checks for s, n, d in c.rows if s == WARN],
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

    skills_dir = os.path.abspath(os.path.expanduser(a.skills_dir))
    checks = [check_junctions(skills_dir)]
    wf = check_workflow(os.path.abspath(os.path.expanduser(a.visibility)), slugs, code_root,
                        timeout=a.gh_timeout, offline=a.offline)
    checks.append(wf)
    checks.append(check_conformance(repos, a.conformance_timeout))
    checks.append(check_budget(skills_dir, code_root, a.conformance_timeout))
    checks.append(check_data_boundary(os.path.abspath(os.path.expanduser(a.visibility)),
                                      repos=repos, offline=a.offline, timeout=a.gh_timeout))

    if a.offline:
        c = Check("ci", "EVERY workflow on EVERY repo of ours is GREEN ON THE DEFAULT BRANCH")
        c.note = "skipped (--offline)"
        c.add(UNKNOWN, "(all public repos)", "offline: CI state unobserved")
        checks.append(c)
    else:
        # Ask about EVERY workflow on EVERY repo of ours, not the guard subset of the public ones.
        # Note this includes repos that FAILED above for missing one of the mandated pair: a repo
        # with pii-guard but no dash-guard still gets everything it does have read, because dropping
        # it would let a red run hide behind an unrelated failure.
        targets = ci_targets(wf, os.path.abspath(os.path.expanduser(a.visibility)), slugs,
                             timeout=a.gh_timeout, offline=a.offline)
        checks.append(check_ci(targets, a.gh_timeout))

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
