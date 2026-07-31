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
              stops being visible to the agent. Only OUR tier can fail it; a third-party or plugin
              description over budget is real, is printed, and is not the operator's to edit.
  databoundary the INVERSE data-boundary assertion, which is the one check that would have caught
              the 2026-07 leak: data_boundary.py proves the REPO holds no real-run output, and this
              proves the reverse, that the resolved real-run output directory is not itself inside a
              git worktree. Both were true and the leak still happened, because nobody ever looked
              from this end. Not-initialized is not a failure: an uninitialized tool is the correct
              shipping state. If git cannot be run at all the answer is UNKNOWN, never PASS -- a
              missing git used to silently clear every repo in this check.
  ci          EVERY guard workflow found on the remote is actually GREEN, reported one row per
              (repo, workflow) so a red dash-guard cannot hide behind a green pii-guard. "CI is the
              authority" is the load-bearing sentence of the whole doctrine and nothing observed
              whether that authority was passing. Degrades to UNKNOWN (never FAIL, never blocking)
              when gh is missing, unauthenticated, rate limited, or the workflow has no run history
              -- GitHub expires run history, so "no runs" is an absence of evidence, not evidence of
              absence. The presence question is the workflow check's job, and there it can FAIL.

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
    """
    c = Check("workflow", "visibility PUBLIC implies %s on the REMOTE default branch"
              % " + ".join(GUARD_WORKFLOWS))
    c.remote_workflows = {}
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
      0  our tier is clean (the tier may still be over the cutoff; that part is not ours to edit)
      1  our tier has a finding
      2  nothing to measure, which is a state and not a failure
    """
    c = Check("budget", "installed skill descriptions still fit in the system prompt (G3)")
    if not os.path.isfile(BUDGET):
        c.note = "budget_check.py not found next to this script"
        c.add(UNKNOWN, "budget_check.py", BUDGET)
        return c
    c.note = ("only OUR tier can fail: a third-party or plugin description over budget is real, is "
              "printed by the tool, and is not the operator's to edit")
    rc, so, se = run([sys.executable, BUDGET, "--skills-dir", skills_dir, "--code-root", code_root],
                     timeout=timeout)
    lines = [ln.strip() for ln in (so or "").splitlines() if ln.strip()]
    status_line = next((ln for ln in lines if ln.startswith("STATUS:")), "")
    ends_at = next((ln for ln in lines if ln.startswith("user tier ends at")), "")
    past = [ln for ln in lines if "past the high bound" in ln or "inside the uncertain band" in ln]
    detail = " | ".join(x for x in (status_line, ends_at,
                                    "%d skill(s) past the cutoff" % len(past) if past else "") if x)
    if rc is None:
        c.add(UNKNOWN, "library", se or "no result")
    elif rc == 2:
        c.add(UNKNOWN, "library", detail or "nothing to measure")
    elif rc == 0:
        # Our tier is clean, but skills ARE being truncated right now. That is a real, observed,
        # currently-happening loss, and printing it as a plain PASS is the same rounding this file
        # was rewritten to stop.
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
        if not os.path.isdir(resolved):
            # resolve_data_dir() is supposed to return only existing dirs, so this means a vendored
            # copy has drifted. It matters because `git -C <missing>` exits nonzero, which the
            # worktree probe would otherwise read as a clean "outside any repo".
            c.add(UNKNOWN, name, "resolver returned %s, which does not exist" % resolved)
            continue
        inside, top = in_git_worktree(resolved)
        if inside is None:
            c.add(UNKNOWN, name, "%s: %s" % (resolved, top))
        elif inside:
            c.add(FAIL, name, "data dir %s is inside git worktree %s" % (resolved, top))
        else:
            c.add(PASS, name, resolved)
    return c


# --- check 6: is the authority green? --------------------------------------------------------------
GREEN = ("success",)
RED = ("failure", "timed_out", "cancelled", "startup_failure", "action_required")


def check_ci(targets, timeout):
    """targets: [(slug, [workflow names observed on that slug's remote]), ...].

    One row per (repo, workflow). The predecessor asked only about pii-guard and titled itself "the
    guard CI is green", so promotion-assistant printed a single confident PASS on 2026-07-30 while
    its dash-guard had been failing since 2026-07-24. A check that names one workflow and reports on
    the category is not a check, it is a headline.
    """
    c = Check("ci", "every guard workflow on the remote is GREEN (%s)" % ", ".join(GUARD_WORKFLOWS))
    gh = shutil.which("gh")
    if not gh:
        c.note = "gh not on PATH; CI state unobserved (infrastructure, non-failing)"
        c.add(UNKNOWN, "gh", "not installed")
        return c
    c.note = ("UNKNOWN here means the answer could not be OBSERVED and never fails the run; a red "
              "run that WAS observed is a FAIL, and a guard missing from the remote entirely is a "
              "FAIL in the workflow check above, not a shrug here")
    if not targets:
        c.add(UNKNOWN, "(nothing to ask)", "no public repo reported a guard workflow on its remote")
        return c
    for slug, workflows in sorted(targets):
        for wf in sorted(workflows):
            name = "%s [%s]" % (slug, wf)
            rc, so, se = run([gh, "run", "list", "-w", wf, "--limit", "1", "-R", slug,
                              "--json", "conclusion,status,createdAt"], timeout=timeout)
            if rc != 0:
                c.add(UNKNOWN, name, first_line(se) or "gh exit %s" % rc)
                continue
            try:
                runs = json.loads(so or "[]")
            except ValueError as e:
                c.add(UNKNOWN, name, "unparseable gh output: %s" % e)
                continue
            if not runs:
                # The file IS on the remote (that is why we are asking). GitHub expires run history,
                # so a dormant repo legitimately has none. Absence of runs is not a red run.
                c.add(UNKNOWN, name, "no run history (expired, or never fired)")
                continue
            r = runs[0]
            concl = (r.get("conclusion") or "").lower()
            state = (r.get("status") or "").lower()
            when = r.get("createdAt") or ""
            if state != "completed":
                c.add(UNKNOWN, name, "run %s (%s)" % (state or "unknown state", when))
            elif concl in GREEN:
                c.add(PASS, name, when)
            elif concl in RED:
                c.add(FAIL, name, "last run %s (%s)" % (concl, when))
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
    checks.append(check_data_boundary(repos))

    if a.offline:
        c = Check("ci", "every guard workflow on the remote is GREEN (%s)"
                  % ", ".join(GUARD_WORKFLOWS))
        c.note = "skipped (--offline)"
        c.add(UNKNOWN, "(all public repos)", "offline: CI state unobserved")
        checks.append(c)
    else:
        # Ask about exactly the guard workflows we OBSERVED on each remote. Note this includes repos
        # that FAILED above for missing one of the pair: a repo with pii-guard but no dash-guard
        # still gets its pii-guard run state read, because dropping it would let a red run hide
        # behind an unrelated failure.
        targets = [(slug, found) for slug, found in wf.remote_workflows.items() if found]
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
