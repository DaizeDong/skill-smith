#!/usr/bin/env python3
"""fleet_check.py -- the nightly, READ-ONLY driver for the whole skill fleet.

WHY THIS EXISTS
---------------
check_conformance.py has been correct and complete for weeks and has surfaced exactly nothing,
because nothing ever ran it. A linter with no driver is a linter that does not exist. The missing
piece here was never more judgment, it was a driver and a schedule. So this file adds no new
opinions: it fans out the checkers that already exist, plus the two assertions nothing on this
machine performs at all (a data directory resolving into a repo the world can read, and whether the
product CI is actually green).

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
1. There is NO --fix and no auto-repair. Config locations may contain uncommitted state or
   secrets, so automatic convergence could destroy data. Inspect and report the current
   condition; a separate authorized workflow owns any migration or repair.
2. It does not check that a repo has upstream tracking configured. sync-skills.ps1 was rewritten to
   be branch-agnostic and nothing on this machine reads branch.<name>.remote any more, so that check
   would guard a property with no consumer and stay red forever.
   The rule behind both: a nightly check whose first run reports findings that are unfixable by
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

And on 2026-08-01 that was still not enough, because the fraction was at the END of the line. The
run read "VERDICT GREEN | pass 104 ... | coverage 56% (112 of 200 rows)" with 88 rows never
evaluated, and a reader scanning for the word after VERDICT gets GREEN and stops. So the coverage
clause is now glued to the verdict WORD, and it shouts when the sample is partial:

    VERDICT GREEN OVER 56% OF ROWS (112 of 200; 88 NOT EVALUATED) | pass 104 ...

The TOTAL line carries the same clause under its counts, because bare counts are the other thing a
reader rounds into an adjective. A disclosure the reader never reaches is not a disclosure.

WHY THIS FILE IS CONCURRENT, AND WHAT THAT IS NOT ALLOWED TO COST
------------------------------------------------------------------
Coverage grew on 2026-07-31 (EVERY workflow on EVERY repo including the private ones) and the run went from 63s to 130s, because each remote question blocked the next. For
a report a human runs by hand that is a correctness problem, not a comfort one: a two minute report
gets started, abandoned and then not read, which is the same disease as a gate nobody runs.

So the independent remote queries fan out over a thread pool (pmap) and every answer is memoized per
distinct slug (Memo), which also killed ~25 duplicate `gh api repos/<slug>` calls per run where the
workflow check and the CI check each resolved the same default branch. A whole-fleet run is ~28s.

The two rules that make the speed honest, both enforced by test:
  1. NEVER buy time by asking fewer questions. Every row interrogated before is interrogated now,
     with the same query and the same arguments. Measured: the report body is byte-identical to the
     serial version, in the clean case and in the deliberately-failed case alike.
  2. ORDER IS PART OF THE ANSWER. pmap returns results in INPUT order and rows are emitted from the
     same sorts as before, because a report whose rows shuffle run to run cannot be diffed against
     yesterday's, and diffing against yesterday's is how a new offender gets noticed.

THE ONE INVARIANT THAT MAKES THE STATUSES MEAN ANYTHING
-------------------------------------------------------
    UNKNOWN means "this run could not OBSERVE the answer". It never means "the answer was bad."

UNKNOWN never fails, which is right for "gh is not installed" and wrong for a real finding, so
a finding must never be reported as UNKNOWN.

So the two are now separated by construction. Infrastructure that is unavailable (no gh, not
authenticated, rate limited, offline, remote HEAD not present locally) yields UNKNOWN, is printed
under UNOBSERVED with its reason, and never fails the run. A definitive negative answer from a
remote we did reach is a FAIL. Because UNKNOWN can only ever be produced by the first case, the old
sentence "UNKNOWN never affects the exit code" stays true without hiding anything.

THE CHECKS
----------
  junctions   every junction/symlink under ~/.claude/skills resolves to a directory that exists.
              Failure mode: a repo gets moved (CodesSelf -> CodesClaude, 2026-07-22) and the skill
              silently vanishes from the agent's library with no error anywhere. A skills dir that
              is missing or holds no junctions at all reports UNKNOWN rather than nothing: a check
              that emits zero rows reads as green, which is the same lie in a quieter voice.
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
  ci          EVERY workflow found on the remote is actually GREEN ON THE DEFAULT BRANCH, reported
              one row per (repo, workflow). Gates do not run in CI any more (they run from the
              .githooks shims against the local fleet-guards and fleet-style checkouts), so these
              are product workflows; a red run on the default branch FAILS the row unless
              CI_WARN_ONLY names it. Degrades to UNKNOWN (never FAIL) when gh is missing,
              unauthenticated, rate limited, or the workflow has no run on the default branch.
              Only runs whose head ref IS the remote default branch are counted.

OUTPUT CONTRACT
---------------
Source state is read-only, including no `git fetch`; only the private report is written. Exits nonzero
if any row is FAIL. UNKNOWN and SKIP never affect the exit code, which is safe precisely because
UNKNOWN can no longer carry a finding. Prints a human-readable report to stdout and writes a
machine-readable status JSON in the PRIVATE versioned companion (override with
--status-json, subject to the same storage check), carrying a UTC timestamp to verify FRESHNESS, not an
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
import concurrent.futures as futures
import fnmatch
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import textwrap
import threading
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

HERE = os.path.dirname(os.path.realpath(__file__))
CONFORMANCE = os.path.join(HERE, "check_conformance.py")
BUDGET = os.path.join(HERE, "budget_check.py")

DEFAULT_SKILLS_DIR = os.path.expanduser("~/.claude/skills")
DEFAULT_CODE_ROOT = os.path.expanduser("~/CodesClaude")
# Resolve at execution time; the report path must sit in a companion worktree (PRIVATE publication is enforced at commit time).
DEFAULT_STATUS = None

# WARN is "evaluated, not clean, and no edit available today makes it clean". It is deliberately
# NOT a pass (a pass would hide it) and deliberately NOT a fail (a nightly that is permanently red
# for something unfixable is a nightly the operator learns to ignore, which is the failure mode this
# whole file exists to avoid). It counts toward COVERAGE, because it was looked at.
PASS, FAIL, WARN, SKIP, UNKNOWN = "PASS", "FAIL", "WARN", "SKIP", "UNKNOWN"
STATUSES = (PASS, FAIL, WARN, SKIP, UNKNOWN)
# Statuses that mean "this row was actually evaluated". SKIP and UNKNOWN are the silence.
EVALUATED = (PASS, FAIL, WARN)

# check_ci reads EVERY workflow on every repo of ours and FAILS a red run on the default branch.
# The escape hatch is deliberately narrow, per workflow and per repo: an entry in CI_WARN_ONLY
# downgrades one named workflow on one named repo to WARN, and it has to carry a reason that gets
# printed in the row. Empty means no exemptions exist, which is the intended steady state.
CI_WARN_ONLY = {
    # ("owner/repo", "workflow-file.yml"): "why this job's redness is not actionable here",
}


# --- concurrency, and why a report's wall clock is a correctness property -------------------------
# check_ci reads EVERY workflow on EVERY repo, one gh round trip each. Wall clock is not cosmetic
# for a report a human runs by hand: a two minute report gets started, abandoned, and then not read.
#
# The rule this file follows: NEVER buy time by asking fewer questions. Every row that was
# interrogated before is interrogated now, with the same query and the same arguments, so the
# answers are identical. The only things removed are (a) waiting, and (b) asking the same question
# twice.
MAX_WORKERS = 8


def pmap(fn, items, workers=MAX_WORKERS):
    """Map fn over items concurrently, results in the ORIGINAL input order.

    Order is the whole reason this is `ex.map` and not `as_completed`. A report whose rows shuffle
    run to run cannot be diffed against yesterday's, and diffing against yesterday's is how a new
    offender gets noticed. Concurrency is allowed to change how long the report takes and nothing
    else about it.

    The work here is network-bound child processes (gh, git), so threads are the right tool: the
    GIL is released for the whole of subprocess.run.
    """
    items = list(items)
    if not items:
        return []
    if len(items) == 1:
        return [fn(items[0])]                # no pool for one item; keeps tracebacks readable
    with futures.ThreadPoolExecutor(max_workers=max(1, min(workers, len(items)))) as ex:
        return list(ex.map(fn, items))


class Memo:
    """Per-run answer cache keyed by anything hashable, safe to share across the pool.

    Two properties matter and the naive dict has neither.

    DEDUPLICATION IS THE POINT, NOT THE SPEEDUP. `gh api repos/<slug>` was issued once by the
    workflow check to learn a default branch and then AGAIN by the CI check to learn the same
    default branch for the same slug, roughly 25 duplicate round trips per run. `gh auth token
    --user <acct>` was re-shelled once per account PER SLUG. Asking a question twice in one run is
    not just slow, it is a way for one run to hold two different answers to the same question.

    THE PER-KEY LOCK. A plain check-then-set under one global lock would let eight threads all miss
    on the same key and all issue the same call. Each key gets its own lock, so concurrent askers of
    the same question block on one another and exactly one call is made, while askers of DIFFERENT
    questions never block on each other.
    """

    def __init__(self):
        self._guard = threading.Lock()
        self._vals = {}
        self._keylocks = {}

    def get(self, key, produce):
        """Return the memoized value for key, calling produce() at most once per run."""
        with self._guard:
            if key in self._vals:
                return self._vals[key]
            lock = self._keylocks.setdefault(key, threading.Lock())
        with lock:
            with self._guard:
                if key in self._vals:
                    return self._vals[key]
            val = produce()
            with self._guard:
                self._vals[key] = val
            return val


# --- tiny helpers --------------------------------------------------------------------------------
_GIT_SELECTORS = {
    "GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE", "GIT_IMPLICIT_WORK_TREE",
    "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_GRAFT_FILE", "GIT_SHALLOW_FILE", "GIT_PREFIX", "GIT_INTERNAL_SUPER_PREFIX",
    "GIT_CEILING_DIRECTORIES", "GIT_DISCOVERY_ACROSS_FILESYSTEM", "GIT_CONFIG",
    "GIT_REPLACE_REF_BASE",
}
def run(args, cwd=None, timeout=60, env=None):
    """Run a command, never raise. Returns (rc, stdout, stderr); rc is None on timeout."""
    if args and os.path.basename(str(args[0])).lower() in ("git", "git.exe"):
        inherited = os.environ if env is None else env
        env = {key: value for key, value in inherited.items() if key.upper() not in _GIT_SELECTORS}
        env["GIT_OPTIONAL_LOCKS"] = "0"
        env["GIT_NO_REPLACE_OBJECTS"] = "1"
    if args and os.path.basename(str(args[0])).lower() in ("gh", "gh.exe"):
        env = {key: value for key, value in (os.environ if env is None else env).items()
               if key.upper() != "GH_HOST"}
        env["GH_HOST"] = "github.com"
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


def github_ssh_alias(host):
    """Prove a static GitHub HostName from the user's SSH config without executing ssh.

    Include and Match configurations require fuller interpretation and remain unknown.
    Routing/canonicalization overrides are rejected. OpenSSH's first-value rule is
    preserved for matching Host patterns, including negated patterns.
    """
    path = os.path.expanduser("~/.ssh/config")
    options, active = {}, True
    try:
        with open(path, encoding="utf-8-sig") as stream:
            for line in stream:
                parts = shlex.split(line, comments=True)
                if not parts:
                    continue
                key = parts.pop(0).lower()
                if "=" in key:
                    key, value = key.split("=", 1)
                    parts.insert(0, value)
                if key in ("include", "match"):
                    return False
                if key == "host":
                    positive = any(fnmatch.fnmatchcase(host, p.lower()) for p in parts if not p.startswith("!"))
                    negative = any(fnmatch.fnmatchcase(host, p[1:].lower()) for p in parts if p.startswith("!"))
                    active = positive and not negative
                elif active:
                    if key in ("proxycommand", "proxyjump", "canonicalizehostname", "canonicaldomains"):
                        return False
                    if key in ("hostname", "port"):
                        if len(parts) != 1:
                            return False
                        options.setdefault(key, parts[0].lower())
    except FileNotFoundError:
        return host == "github.com"
    except (OSError, UnicodeError, ValueError):
        return False
    return options.get("hostname", host) == "github.com" and options.get("port", "22") == "22"


def slug_from_url(url):
    """A canonical GitHub slug only when the URL's provider identity is established."""
    if not isinstance(url, str) or not url or url != url.strip() or "\\" in url:
        return None
    try:
        if "://" in url:
            parsed = urlsplit(url)
            if parsed.query or parsed.fragment or parsed.password:
                return None
            host, path = (parsed.hostname or "").lower(), parsed.path
            if parsed.scheme == "https":
                if host != "github.com" or parsed.username or parsed.port not in (None, 443):
                    return None
            elif parsed.scheme == "ssh":
                if parsed.username != "git" or parsed.port not in (None, 22):
                    return None
                if not github_ssh_alias(host):
                    return None
            else:
                return None
            if not path.startswith("/"):
                return None
            path = path[1:]
        else:
            match = re.fullmatch(r"git@([A-Za-z0-9.-]+):(.+)", url)
            if not match:
                return None
            host, path = match.groups()
            if not github_ssh_alias(host.lower()):
                return None
        if path.endswith(".git"):
            path = path[:-4]
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_.-]+", path):
            return None
        if path.split("/")[1] in (".", ".."):
            return None
        return path.lower()
    except ValueError:
        return None


def local_repos(code_root, problems=None):
    """Every verified Git working copy directly under code_root, as {name: path}."""
    out = {}
    problems = problems if problems is not None else []
    if not os.path.isdir(code_root):
        problems.append((code_root, "code root is missing or inaccessible"))
        return out
    try:
        names = sorted(os.listdir(code_root))
    except OSError as exc:
        problems.append((code_root, "cannot list code root: %s" % exc))
        return out
    for name in names:
        p = os.path.join(code_root, name)
        try:
            os.lstat(os.path.join(p, ".git"))
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError as exc:
            problems.append((name, "cannot inspect Git marker: %s" % exc))
            continue
        inside, root = in_git_worktree(p)
        if inside is True and os.path.normcase(os.path.realpath(root)) == os.path.normcase(os.path.realpath(p)):
            out[name] = p
        elif inside is None:
            problems.append((name, root))
    return out


def repo_slugs(repos, problems=None):
    """{slug: path} for every local repo that has an origin remote.

    Concurrent, but the RESULT is assembled by walking the repos in their original order, because
    setdefault means the first path wins when two clones share a slug. Insertion order is part of
    the answer here, so it is not allowed to depend on which thread finished first.
    """
    items = sorted(repos.items())

    def ask(item):
        _name, path = item
        rc, so, se = run(["git", "-C", path, "remote", "get-url", "origin"], timeout=20)
        slug = slug_from_url(first_line(so)) if rc == 0 else None
        return slug, ("unsupported or unverified origin identity" if rc == 0 else
                      "origin inspection failed: %s" % (first_line(se) or "no result"))

    out = {}
    problems = problems if problems is not None else []
    for (name, path), (slug, reason) in zip(items, pmap(ask, items)):
        if slug:
            out.setdefault(slug, path)
        else:
            problems.append((name, reason))
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
        top = os.path.normcase(os.path.abspath(first_line(so)))
        current = os.path.normcase(os.path.abspath(path))
        while True:
            marker = os.path.join(current, ".git")
            if os.path.lexists(marker):
                if is_link(marker):
                    return None, "repository marker is an alias"
                try:
                    info = os.lstat(marker)
                except OSError:
                    return None, "repository marker is inaccessible"
                if not (stat.S_ISDIR(info.st_mode) or
                        (stat.S_ISREG(info.st_mode) and info.st_nlink == 1)):
                    return None, "repository marker is not an ordinary directory or file"
                if current != top:
                    return None, "Git toplevel does not own the nearest physical repository marker"
                return True, first_line(so)
            parent = os.path.dirname(current)
            if parent == current:
                return None, "Git toplevel has no matching physical repository marker"
            current = parent
    err = (se or "").lower()
    if err.strip() in ("fatal: not a git repository", "fatal: not a git repository (or any of the parent directories): .git"):
        return False, ""
    if rc == 0:
        return None, "git printed no toplevel and no error"
    return None, "git inspection failed: %s" % (first_line(se) or "exit %s" % rc)


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


# WHY THE MEMOS ARE PARAMETERS AND NOT MODULE GLOBALS
# ---------------------------------------------------
# The obvious shape is a module-level cache, and it is wrong. A memo's scope has to be ONE RUN. As a
# global it is one PROCESS, and the difference bit immediately: the suite runs many independent
# check_ci calls in a single interpreter, and a global memo served the first call's answers to the
# fifth. Five tests went green while asserting nothing -- including the two that exist to prove the
# branch filter is applied and that the branch is looked up once per repo. A speedup whose
# bookkeeping blinds the tests that guard the behaviour has taken back more than it gave.
#
# So each memo is passed in, main() creates one of each and hands the SAME pair to every check
# (which is what makes the cross-check deduplication real), and any caller that passes nothing gets
# a fresh one and therefore the original, un-memoized behaviour.
def branch_probe(gh, slug, timeout, memo=None):
    """(branch, rc, stderr) for a slug's remote default branch. One gh call per slug per memo.

    The raw rc and stderr are carried rather than a pre-baked sentence because the two callers
    report a failure differently, and both wordings predate this memo and are worth keeping: the
    workflow check distinguishes "could not reach" (rc nonzero) from "reached, but no default
    branch" (rc zero, empty answer), and check_ci prints gh's own error verbatim.
    """
    memo = Memo() if memo is None else memo

    def probe():
        rc, so, se = run([gh, "api", "repos/%s" % slug, "--jq", ".default_branch"], timeout=timeout)
        return (first_line(so) if rc == 0 else "", rc, first_line(se))

    return memo.get(slug, probe)


def _remote_workflows_via_gh(gh, slug, timeout, branches):
    """(names, reason). names is a list when OBSERVED (possibly empty), else None + why."""
    # Probe the repo first. A successful probe proves the remote is reachable AND that our token can
    # see this repo, which is what licenses reading a later 404 as "the directory is not there"
    # rather than "we were not allowed to look". GitHub returns 404 for both, so without this first
    # call the two are indistinguishable and a missing guard could be mistaken for a permission
    # problem (or, far worse, the other way around).
    branch, rc, se = branch_probe(gh, slug, timeout, branches)
    if rc != 0:
        return None, "gh could not reach %s: %s" % (slug, se or "exit %s" % rc)
    if not branch:
        return None, "gh returned no default branch for %s" % slug
    rc, so, se = run([gh, "api", "repos/%s/contents/.github/workflows?ref=%s" % (slug, quote(branch, safe="")),
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


def remote_workflow_files(slug, path, timeout, offline=False, memo=None, branches=None):
    """(names, reason) for .github/workflows on the REMOTE default branch.

    names is a list (possibly empty) when the remote answered, None when it could not be observed.
    Never consults the working tree: an unpushed file is not CI.

    Memoized per DISTINCT (slug, path) when a memo is supplied, so a second caller cannot
    reintroduce a duplicate fetch.
    """
    if offline:
        return None, "offline mode: the remote was not contacted"
    memo = Memo() if memo is None else memo
    branches = Memo() if branches is None else branches

    def ask():
        reasons = []
        gh = shutil.which("gh")
        if gh:
            names, why = _remote_workflows_via_gh(gh, slug, timeout, branches)
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

    names, why = memo.get((slug, path), ask)
    # Hand every caller its OWN list. The memo holds one object and these listings are passed
    # around and stored on Check objects; a shared mutable would let one caller's sort or append
    # rewrite another's evidence.
    return (list(names) if names is not None else None), why


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


# --- check 3: fan check_conformance.py ------------------------------------------------------------
def conformance_evidence(returncode, stdout, stderr):
    """Require measured rows and a matching summary before reporting a clean conformance run."""
    lines = [line.strip() for stream in (stdout, stderr) for line in stream.splitlines() if line.strip()]
    rows = [match.groups() for line in lines
            if (match := re.fullmatch(r"\[(PASS|WARN|FAIL)\]\s+(.+)", line))]
    summaries = [line for line in lines if re.match(r"^\d+/\d+\s+passed\b", line)]
    score = " | ".join(summaries)
    failures = [line for line in lines if line.startswith("[FAIL]")]
    warnings = [line for line in lines if re.match(r"^(?:\[WARN\]|WARN(?:ING)?\b)", line, re.I)]
    # Keep explicit findings from either stream, including a bare status tag.
    diagnostics = [score, *failures, *warnings, stderr.strip()]
    detail = " | ".join(part for part in diagnostics if part)
    if failures:
        return FAIL, detail
    if returncode is None:
        return UNKNOWN, detail or "no conformance result"
    if returncode != 0:
        return FAIL, detail or "exit %s" % returncode
    if warnings:
        return WARN, detail
    if stderr.strip():
        return UNKNOWN, detail + " | unexplained conformance diagnostics"
    if any(line.startswith("[") and re.fullmatch(r"\[(PASS|WARN|FAIL)\]\s+(.+)", line) is None
           for line in lines):
        return UNKNOWN, detail + " | malformed conformance row"
    if len(summaries) != 1:
        return UNKNOWN, detail or "missing or ambiguous conformance summary"
    summary = re.fullmatch(r"(\d+)/(\d+) passed", summaries[0])
    if summary is None:
        return UNKNOWN, detail + " | unsupported or contradictory conformance summary"
    passed, total = map(int, summary.groups())
    names = [name for _status, name in rows]
    if (not total or passed != total or len(rows) != total
            or len(set(names)) != total or any(status != PASS for status, _name in rows)):
        return UNKNOWN, detail + " | conformance rows are absent, unmeasured or inconsistent"
    return PASS, score


def check_conformance(repos, timeout):
    c = Check("conformance", "Skill Repo Spec v1 conformance (check_conformance.py)")
    if not os.path.isfile(CONFORMANCE):
        c.note = "check_conformance.py not found next to this script"
        c.add(UNKNOWN, "check_conformance.py", CONFORMANCE)
        return c
    items = sorted(repos.items())
    # Every invocation is an independent read-only subprocess over a different repo (verified: the
    # linter opens nothing for writing), so they run CONCURRENTLY and the rows are emitted in the
    # same sorted order afterwards. On this machine that is ~15 python interpreter startups plus
    # ~15 tree walks that no longer happen end to end.
    linted = [it for it in items
              if os.path.isfile(os.path.join(it[1], ".claude-plugin", "plugin.json"))]
    done = dict(zip([n for n, _p in linted],
                    pmap(lambda it: run([sys.executable, CONFORMANCE, it[1]], timeout=timeout),
                         linted)))
    for name, path in items:
        if not os.path.isfile(os.path.join(path, ".claude-plugin", "plugin.json")):
            # Spec v1 does not apply, but say so. Silently dropping the repo means a plugin.json
            # that gets deleted or renamed removes the repo from coverage with no trace anywhere.
            c.add(SKIP, name, "no .claude-plugin/plugin.json")
            continue
        status, detail = conformance_evidence(*done[name])
        c.add(status, name, detail)
    return c


# --- check 4: does the installed library still fit in the system prompt? --------------------------
def check_budget(skills_dir, code_root, timeout, listing=None, capacity=None):
    """Run budget_check.py (G3) once for the whole machine.

    Every other check here is per repo. This one is per LIBRARY, and it is the only check whose
    failure is invisible by construction: past the cutoff a skill's description is dropped from the
    prompt with no error anywhere, so the skill simply never fires and nothing says why.

    Exit-code contract of budget_check.py:
      0  OK       arithmetic fits; fleet PASS also requires measurement=complete
      1  FAIL     a finding closable tonight by editing: our description is over the cap, or the
                  overflow is small enough that trimming user-tier descriptions would clear it
      2  UNKNOWN  inventory or supplied listing evidence is incomplete
      3  BLOCKED  the library is over capacity and trimming cannot close the gap. Real, reported in
                  full every run, mapped to WARN and not FAIL.

    WHY BLOCKED IS NOT RED
    This row was red every night for a condition no edit could clear, which is how every gate in
    this codebase has historically come to be ignored. Two separate errors produced that: the tool
    named the wrong skills as victims, and it declared the tier those skills were in unfixable when
    they were the operator's own files. Both are gone. What is left is a genuine overflow of about
    32,000 chars that no amount of text editing can absorb, so the colour now follows the LEVER:
    red when keystrokes close it, amber when the only remaining move is deciding what to stop
    having. Amber is not a softer red. It is stated in full on every run, with the arithmetic and a
    ranked, priced list of which plugin removals would clear it.

    THE DIGEST LINE IS THE INTERFACE, AND ITS ABSENCE IS NOT A ZERO
    Everything this function needs comes off one `BUDGET:` line. The count used to be grepped out
    of prose and reported double the moment the same phrase appeared twice. A missing digest is
    UNKNOWN, never PASS: the previous version defaulted the count to 0, so a budget_check that
    printed nothing recognisable produced a clean green row.

    `fp` fingerprints the finding KEYS, not the numbers, so it is stable night to night and moves
    exactly when the finding SET moves: a new over-cap description, a newly installed plugin, an
    overflow appearing or clearing. It is carried into the row detail so that answering "is
    tonight's colour new?" needs no second tool and no memory of last night's char counts.
    """
    c = Check("budget", "installed skill descriptions still fit in the system prompt (G3)")
    if not os.path.isfile(BUDGET):
        c.note = "budget_check.py not found next to this script"
        c.add(UNKNOWN, "budget_check.py", BUDGET)
        return c
    c.note = ("colour follows the LEVER, not the severity: an overflow trimming can clear FAILS, an "
              "overflow only a removal decision can clear is BLOCKED and warns, so a real condition "
              "nobody can edit away stays visible without making the verdict red forever. The "
              "per-skill CAP is limited to our tier, the only tier authored to Spec-v1. Same fp "
              "means the same finding set as last night")
    command = [sys.executable, BUDGET, "--skills-dir", skills_dir, "--code-root", code_root]
    if listing:
        command += ["--listing", listing]
    if capacity is not None:
        command += ["--capacity", str(capacity)]
    rc, so, se = run(command, timeout=timeout)
    lines = [ln.strip() for ln in (so or "").splitlines() if ln.strip()]
    status_line = next((ln for ln in lines if ln.startswith("STATUS:")), "")
    digest = next((ln for ln in lines if ln.startswith("BUDGET:")), "")
    body = digest[len("BUDGET:"):].split()
    fields = {}
    for tok in body[1:] if body else []:
        k, _, v = tok.partition("=")
        if v:
            fields[k] = v
    state = body[0] if body else ""

    def num(key):
        try:
            return int(fields[key])
        except (KeyError, ValueError):
            return None

    loss_count, overflow = num("min_lost"), num("overflow")
    unresolved = num("unresolved")
    measurement = fields.get("measurement", "missing")
    lost = loss_count if measurement in ("complete", "incomplete") else None
    projected = num("projected_min_removals")
    if projected is None and measurement not in ("complete", "incomplete"):
        # Older digests used min_lost for projections when no listing was supplied.
        projected = loss_count
    detail = " | ".join(x for x in (
        status_line,
        "%s chars over capacity" % fields["overflow"] if overflow else "",
        ">=%d skill(s) have no description in the supplied listing" % lost if lost else "",
        "projected minimum removal: %d skill(s) under the capacity policy" % projected if projected else "",
        "current omissions unmeasured" if measurement in ("not_supplied", "missing") else "",
        "lever=%s" % fields.get("lever", "?"),
        "unresolved=%d" % unresolved if unresolved else "",
        "measurement=%s" % measurement,
        "fp=%s" % fields.get("fp", "?")) if x)

    if rc is None:
        c.add(UNKNOWN, "library", se or "no result")
    elif not digest:
        # Fail closed. A run whose digest cannot be found has not been evaluated, and the previous
        # version turned exactly that into a green row by defaulting the count to zero.
        c.add(UNKNOWN, "library", "budget_check printed no BUDGET: digest line, so nothing was read")
    elif (lost and (state == "OK" or measurement == "complete")) or rc == 1 or state == "FAIL":
        c.add(FAIL, "library", detail or first_line(se) or "reported FAIL")
    elif rc == 3 or state == "BLOCKED":
        # Real, and no edit closes it. Say so every run, in a colour that does not accuse the
        # operator of leaving something undone. rc and state are OR-ed so a drift between the two
        # lands here rather than being rounded to PASS.
        c.add(WARN, "library",
              "BLOCKED, no lever made of keystrokes: " + (detail or "see budget_check output")
              + " | remedy is a removal decision, run budget_check.py --plugins for the ranking")
    elif rc == 2 or state == "UNKNOWN" or unresolved:
        c.add(UNKNOWN, "library", detail or "incomplete library inventory")
    elif rc == 0:
        if (measurement != "complete" or state != "OK"
                or any(value is None or value < 0 for value in (lost, overflow, unresolved))):
            c.add(UNKNOWN, "library", detail + " | live visibility has not been established")
        else:
            c.add(WARN if overflow else PASS, "library", detail or "within budget")
    else:
        c.add(FAIL, "library", detail or first_line(se) or "exit %s" % rc)
    if unresolved and not c.count(UNKNOWN):
        c.add(UNKNOWN, "library coverage", "unresolved=%d; known findings above cover only measured skills" % unresolved)
    return c


def companion_resolver(source_root):
    try:
        from fleet_guards.runtime import companion_resolver as bind
    except ImportError as exc:
        raise ImportError(
            'fleet_guards is not installed; run: pip install -e "$(git config --get fleet.guards)"') from exc
    return bind(source_root=os.path.abspath(source_root))


# --- check 6: is the authority green? --------------------------------------------------------------
GREEN = ("success",)
RED = ("failure", "timed_out", "cancelled", "startup_failure", "action_required")


def default_branch(gh, slug, timeout, cache=None):
    """(branch, why-not) for a slug's remote default branch.

    Backed by the SAME memo the workflow listing fills, so a slug whose default branch was already
    established while listing its workflows costs nothing here.
    """
    b, rc, se = branch_probe(gh, slug, timeout, cache)
    return b, ("" if b else (se or "gh exit %s" % rc))


def ci_targets(slugs, timeout, offline=False, listings=None, branches=None):
    """[(slug, names_or_None, why)] for EVERY repo of ours that has a clone here.

    Listings are fetched concurrently; pmap preserves input order, so rows stay sorted.
    """
    ordered = sorted(slugs)
    return [(slug, names, why) for slug, (names, why) in zip(ordered, pmap(
        lambda s: remote_workflow_files(s, slugs[s], timeout, offline=offline,
                                        memo=listings, branches=branches), ordered))]


def valid_ci_step(step):
    """Require a complete, consistent status/conclusion pair before using step evidence."""
    if (not isinstance(step, dict) or type(step.get("number")) is not int
            or step["number"] <= 0 or "conclusion" not in step):
        return False
    state, conclusion = step.get("status"), step["conclusion"]
    if state == "completed":
        return isinstance(conclusion, str) and conclusion in (
            "success", "failure", "neutral", "cancelled", "skipped", "timed_out", "action_required")
    return state in ("queued", "in_progress") and conclusion is None


def ci_execution_detail(gh, slug, run_id, timeout):
    """Distinguish a run with executed steps from a run admitted to no runner.

    Zero steps do not identify a billing cause. That requires separate check annotations.
    An empty or unavailable job listing supplies no execution evidence.
    """
    rc, so, se = run([gh, "api", "repos/%s/actions/runs/%s/jobs?per_page=100" % (slug, run_id),
                      "--paginate", "--slurp"], timeout=timeout)
    if rc:
        return "unknown", first_line(se) or "job inspection failed"
    try:
        pages = json.loads(so)
        if isinstance(pages, dict):
            pages = [pages]
        jobs = [job for page in pages for job in page["jobs"]]
        if not jobs:
            return "unknown", "job listing empty"
        if not all(isinstance(job, dict) for job in jobs):
            return "unknown", "invalid job record"
        for job in jobs:
            steps = job.get("steps")
            if not isinstance(steps, list) or not all(valid_ci_step(step) for step in steps):
                return "unknown", "invalid or unavailable step records"
        if any(step["status"] in ("in_progress", "completed") and step.get("conclusion") != "skipped"
               for job in jobs for step in job["steps"]):
            return "executed", "at least one valid step was in progress or completed"
        if all(job.get("steps") == [] and not job.get("runner_name") and not job.get("runner_id") for job in jobs):
            return "not_started", "all jobs have zero steps and no runner; inspect annotations for admission cause"
        return "unknown", "no steps recorded; runner/admission evidence incomplete"
    except (ValueError, KeyError, TypeError):
        return "unknown", "unparseable job listing"


def check_ci(targets, timeout, branches=None):
    """targets: [(slug, names_or_None, why), ...] as built by ci_targets().

    names is the FULL workflow listing observed on that slug's remote default branch, or None when
    the listing could not be observed, in which case `why` says so and the repo gets an UNKNOWN row
    rather than vanishing.

    EVERY workflow in the listing is read, one row per (repo, workflow); see the CI_WARN_ONLY note
    at the top of this file. Gates do not run in CI, so these are product workflows.

    WHY THE BRANCH FILTER EXISTS (2026-07-31)
    -----------------------------------------
    The query was `gh run list -w <wf> --limit 1`, which is the newest run on ANY ref. Every other
    check in this file interrogates the remote DEFAULT branch, and the verdict this one prints is a
    claim about the branch the world clones. On 2026-07-31 two of its green rows were evidence from
    a topic branch, reported as if they described main, and a green topic-branch run can sit over a
    red default branch.

    "No run on the default branch" is UNKNOWN, not a silent fallback to whatever run exists. A
    workflow that has only ever fired on topic branches has not yet said anything about the branch
    being asked about, and inventing an answer from the wrong ref is how this started.
    """
    c = Check("ci", "EVERY workflow on EVERY repo of ours is GREEN ON THE DEFAULT BRANCH")
    c.execution = {}
    gh = shutil.which("gh")
    if not gh:
        c.note = "gh not on PATH; CI state unobserved (infrastructure, non-failing)"
        c.add(UNKNOWN, "gh", "not installed")
        return c
    c.note = ("every workflow file on every remote default branch is read, PRIVATE repos included, "
              "and a red run fails. Only runs whose head ref IS the remote default branch are counted; "
              "UNKNOWN means the answer could not be OBSERVED and never fails the run")
    if not targets:
        c.add(UNKNOWN, "(nothing to ask)", "no repo reported any workflow on its remote")
        return c

    ordered = sorted(targets, key=lambda t: t[0])
    # A fresh memo when the caller supplies none reproduces the old per-call `branches = {}` cache
    # exactly: one lookup per repo, not one per workflow. main() passes the shared one so a branch
    # already resolved while listing workflows is not resolved a second time here.
    branches = Memo() if branches is None else branches

    # --- the expensive part, and why it is shaped like this ---------------------------------------
    # This check is the bulk of the report's wall clock: ~57 `gh run list` round trips on this
    # machine, one per (repo, workflow), each one a second or so of pure waiting. Serially that is
    # the difference between a report you run and a report you mean to run.
    #
    # ON BATCHING, which was considered and deliberately NOT done. GitHub does expose
    # `repos/<slug>/actions/runs?branch=<b>&per_page=100`, which would collapse the ~57 calls into
    # ~25, one per repo. It also silently changes the ANSWER: that endpoint returns the newest runs
    # across all workflows, so on a repo where one chatty workflow fills the page, a quiet
    # workflow's latest run falls off the end and the row degrades to "no run on the default
    # branch" -- a red guard turning into a shrug because of someone else's commit volume. Paging
    # until every workflow is accounted for gives the calls straight back on exactly the repos
    # where it would have helped. The per-workflow query asks the precise question and cannot be
    # crowded out, so it stays, and concurrency is what pays for it. Fewer questions was never the
    # available trade.
    #
    # Both fan-outs preserve order (pmap does), and the emit loop below walks `ordered` and
    # sorted(workflows) exactly as the serial version did, so the rows land in the same sequence.
    branch_slugs = sorted({t[0] for t in ordered if t[1]})
    pmap(lambda s: default_branch(gh, s, timeout, branches), branch_slugs)  # warm the branch memo

    jobs = []
    for slug, workflows, _why in ordered:
        if not workflows:
            continue
        branch, _bwhy = default_branch(gh, slug, timeout, branches)
        if not branch:
            continue                       # emitted as UNKNOWN below; there is no query to make
        jobs += [(slug, wf, branch) for wf in sorted(workflows)]

    def ask_runs(job):
        slug, wf, branch = job
        return run([gh, "run", "list", "-w", wf, "-b", branch, "--limit", "1", "-R", slug,
                    "--json", "conclusion,status,createdAt,headBranch,databaseId,headSha"], timeout=timeout)

    runs_by_job = dict(zip([(s, w) for s, w, _b in jobs], pmap(ask_runs, jobs)))

    for slug, workflows, listing_why in ordered:
        if workflows is None:
            c.add(UNKNOWN, slug, "workflow listing not observed: %s" % (listing_why or "no reason given"))
            continue
        if not workflows:
            # An answered listing that is empty is a FACT, not a gap: the repo is NAMED.
            c.add(SKIP, slug, "repo with no workflows")
            continue
        branch, why = default_branch(gh, slug, timeout, branches)
        for wf in sorted(workflows):
            name = "%s [%s]" % (slug, wf)
            exempt = CI_WARN_ONLY.get((slug, wf))
            if not branch:
                # Without the default branch there is no question to ask. Reporting the newest run
                # on any ref instead is exactly the bug this arm replaced.
                c.add(UNKNOWN, name, "could not determine the default branch: %s" % why)
                continue
            rc, so, se = runs_by_job[(slug, wf)]
            if rc != 0:
                c.add(UNKNOWN, name, first_line(se) or "gh exit %s" % rc)
                continue
            try:
                runs = json.loads(so or "[]")
            except ValueError as e:
                c.add(UNKNOWN, name, "unparseable gh output: %s" % e)
                continue
            if not isinstance(runs, list) or any(not isinstance(item, dict) for item in runs):
                c.add(UNKNOWN, name, "invalid workflow run listing")
                continue
            if not runs:
                # The file IS on the remote default branch (that is why we are asking). GitHub
                # expires run history, so a dormant repo legitimately has none. Absence of runs is
                # not a red run -- and it is not permission to quote a topic branch's run either.
                c.add(UNKNOWN, name, "no run on the default branch %s (expired, never fired, or the "
                                     "workflow has only ever run on other refs)" % branch)
                continue
            r = runs[0]
            if any(r.get(key) is not None and not isinstance(r[key], str)
                   for key in ("conclusion", "status")):
                c.add(UNKNOWN, name, "invalid workflow run status")
                continue
            concl = (r.get("conclusion") or "").lower()
            state = (r.get("status") or "").lower()
            reported_branch = r.get("headBranch")
            branch_verified = isinstance(reported_branch, str) and reported_branch == branch
            branch_label = (reported_branch if isinstance(reported_branch, str) and reported_branch
                            else "<unobserved branch>")
            when = "%s on %s" % (r.get("createdAt") or "", branch_label)
            if state != "completed":
                c.add(UNKNOWN, name, "run %s (%s)" % (state or "unknown state", when))
            elif concl in GREEN + RED:
                detail = "last run %s (%s)" % (concl, when)
                execution, execution_detail = (ci_execution_detail(gh, slug, r["databaseId"], timeout)
                                               if r.get("databaseId") else ("unknown", "run ID absent"))
                c.execution[name] = {"state": execution, "detail": execution_detail,
                                     "run_id": r.get("databaseId"), "head_sha": r.get("headSha")}
                detail += "; execution=%s: %s" % (execution, execution_detail)
                if not branch_verified:
                    c.add(UNKNOWN, name, "%s; returned branch does not establish default branch %s"
                          % (detail, branch))
                elif concl in GREEN:
                    c.add(PASS if execution == "executed" else UNKNOWN, name, detail)
                elif exempt:
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

    A literal listing can bury a few real failures under dozens of identical SKIP lines. A report nobody scrolls through
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


# Below this fraction of rows evaluated, the verdict word is not allowed to stand on its own. 56%
# of rows evaluated is not a description of the fleet, it is a description of a sample, and a
# reader who stops after the first word must not come away with the wrong noun.
FULL_COVERAGE_PCT = 95


def coverage_of(tot):
    """(evaluated, not_evaluated, total, percent) over every row in the run.

    THE PERCENT IS FLOORED AND CAPPED, NEVER ROUNDED, and 100 is reachable only when every row was
    evaluated. Rounding put this line in the run's own digest, verbatim:

        VERDICT GREEN over 100% of rows (1993 of 2000) | ... | NOT EVALUATED 7 | coverage 100%

    which states full coverage and 1993 of 2000 in the same breath. Worse, `round(99.65)` is 100, so
    the branch that exists to SHOUT about unevaluated rows compared 100 against the 95 threshold and
    stayed quiet. The failure mode this whole line was written to prevent, arriving through its own
    arithmetic: a report where "checked everything" and "checked nearly everything" print the same.

    Floor, because 99.9% coverage is not 100% coverage. Cap at 99 while anything is unevaluated,
    because on a large enough run the floor of the true percentage is 100 too.
    """
    ev = tot["pass"] + tot["fail"] + tot["warn"]
    silent = tot["skip"] + tot["unknown"]
    total = ev + silent
    if not total:
        return ev, silent, total, 0
    pct = int(100 * ev // total)
    if silent and pct >= 100:
        pct = 99
    return ev, silent, total, pct


def coverage_phrase(tot):
    """The clause that has to travel WITH the verdict word, never further down the line."""
    ev, silent, total, pct = coverage_of(tot)
    # pct is already a floored, capped integer. round() here would re-introduce the bug one
    # layer up the moment coverage_of changed, so the caller stops rounding too.
    if silent and pct < FULL_COVERAGE_PCT:
        return "OVER %d%% OF ROWS (%d of %d; %d NOT EVALUATED)" % (pct, ev, total, silent)
    return "over %d%% of rows (%d of %d)" % (pct, ev, total)


def digest_line(tot):
    """The single line a caller is meant to quote verbatim.

    It exists because the caller used to build its own sentence out of the counts and chose the word
    "all green" for a run with 82 unevaluated rows. A verdict and a coverage fraction on one line
    leave no room for that: GREEN can only mean "nothing that was EVALUATED failed", and the same
    line says how much was evaluated.

    WHY THE COVERAGE MOVED TO THE FRONT (2026-08-01)
    ------------------------------------------------
    Putting it on the line was not enough. It sat at the END, four pipe-separated fields after the
    verdict, on a run where 88 of 200 rows -- nearly half the fleet -- were never evaluated. A
    reader scanning for the word after "VERDICT" got "GREEN" and stopped, which is the same defect
    as the old "all green", just with the correction printed further to the right where nobody
    reached it. The verdict TOKEN and its scope are now one grammatical unit: the report cannot say
    GREEN without saying what it is green over, in the same breath, and the clause shouts when the
    sample is partial. `verdict` is still returned as the bare word for machines to switch on.
    """
    ev, silent, total, pct = coverage_of(tot)
    verdict = "RED" if tot["fail"] else ("AMBER" if tot["warn"] else "GREEN")
    return ("VERDICT %s %s | pass %d fail %d warn %d | NOT EVALUATED %d (skip %d, unobserved %d) | "
            "coverage %d%% (%d of %d rows)"
            % (verdict, coverage_phrase(tot),
               tot["pass"], tot["fail"], tot["warn"], silent, tot["skip"], tot["unknown"],
               pct, ev, total)), verdict


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
    # The counts alone are the thing a reader rounds into an adjective, so the scope is stapled
    # directly underneath them rather than only appearing on the verdict line further down. "pass
    # 104 fail 0" reads as a healthy fleet; "pass 104 fail 0, and 88 rows were never looked at"
    # does not, and both sentences describe the same run.
    _ev, _silent, _total, _pct = coverage_of(tot)
    print("       these counts describe %d%% of the fleet: %d of %d rows evaluated, %d NOT "
          "evaluated (skip %d, unobserved %d)"
          % (round(_pct), _ev, _total, _silent, tot["skip"], tot["unknown"]))
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


def reject_output_aliases(path):
    """Reject ambiguous physical destinations before any DATA write or mkdir."""
    absolute = Path(os.path.abspath(os.path.expanduser(path)))
    for node in (*reversed(absolute.parents), absolute):
        try:
            info = node.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 1024:
            raise ValueError("DATA output contains a link or reparse alias")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise ValueError("DATA output contains a hardlink alias")
        if node != absolute and not stat.S_ISDIR(info.st_mode):
            raise ValueError("DATA output parent is not a directory")
    return str(absolute)


def default_data_path(name):
    """Resolve a real-run destination through the fleet_guards companion resolver."""
    repo = os.path.realpath(os.path.join(HERE, "..", "..", ".."))
    directory = companion_resolver(repo).resolve_data_dir("skill-smith")
    if directory is None:
        raise ValueError("Initialize the private skill-smith companion or set SKILL_SMITH_CONFIG; no DATA fallback")
    return os.path.join(directory, name)


def resolve_status_path(path, *, default_name="fleet-check-status.json", directory=False, source_root=None):
    """Check a DATA destination once, before writing: inside a versioned companion, outside the tool repo.

    The companion is the nearest Git worktree above the destination. Its PRIVATE publication is
    enforced by commit-time hooks, not here.
    """
    repo = os.path.realpath(source_root or os.path.join(HERE, "..", "..", ".."))
    path = reject_output_aliases(default_data_path(default_name) if path is None else path)
    if os.path.exists(path) and os.path.isdir(path) != directory:
        raise ValueError("DATA destination has the wrong file/directory type")
    try:
        inside_own = os.path.commonpath([os.path.normcase(repo), os.path.normcase(path)]) == os.path.normcase(repo)
    except ValueError:  # Different Windows volumes cannot contain one another.
        inside_own = False
    if inside_own:
        raise ValueError("Report DATA cannot be written inside the tool repository")
    nearest = next((node for node in (Path(path), *Path(path).parents) if os.path.lexists(node / ".git")), None)
    if nearest is None:
        raise ValueError("Report requires a versioned companion, not an unversioned directory")
    if Path(repo).is_relative_to(nearest):
        raise ValueError("Report DATA requires a separate companion worktree outside the tool repository")
    return path


def write_status(path, checks, tot, started_utc, elapsed, exit_code):
    """Write the report to a destination already checked by resolve_status_path."""
    path = reject_output_aliases(path)
    tmp = reject_output_aliases(path + ".tmp")
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
        "ci_execution": {name: value for c in checks for name, value in getattr(c, "execution", {}).items()},
    }
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
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
    ap.add_argument("--listing", help="captured current skill listing for measured G3 visibility; absent evidence stays UNKNOWN")
    ap.add_argument("--capacity", type=int, help="explicit current G3 capacity policy; historical estimates are not enforced")
    ap.add_argument("--status-json", default=DEFAULT_STATUS,
                    help="machine-readable result; the caller checks its utc for freshness")
    ap.add_argument("--no-status", action="store_true", help="do not write the status file")
    ap.add_argument("--print-status-path", action="store_true",
                    help="print the default resolved artifact path without inspecting or writing the fleet")
    ap.add_argument("--offline", action="store_true",
                    help="skip the CI check (no network, no gh)")
    ap.add_argument("--gh-timeout", type=int, default=30)
    ap.add_argument("--conformance-timeout", type=int, default=300)
    a = ap.parse_args(argv)
    if a.print_status_path:
        try:
            print(default_data_path("fleet-check-status.json"))
            return 0
        except (OSError, ValueError, RuntimeError, ImportError) as error:
            print("status path lookup rejected: %s" % error, file=sys.stderr)
            return 1
    if not a.no_status:
        try:
            a.status_json = resolve_status_path(a.status_json)
        except (OSError, ValueError, RuntimeError, ImportError) as e:
            print("status destination rejected: %s" % e, file=sys.stderr)
            return 1

    t0 = time.time()
    started_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    code_root = os.path.abspath(os.path.expanduser(a.code_root))
    inventory_problems = []
    repos = local_repos(code_root, problems=inventory_problems)
    slugs = repo_slugs(repos, problems=inventory_problems)

    # ONE pair of memos for the whole run, shared by every check that talks to a remote. This is
    # what makes the deduplication cross-check rather than merely intra-check: the default branch
    # the workflow listing needed is the same default branch the CI run filter needs, and before
    # this it was fetched twice for ~25 repos. Their lifetime is exactly this function, so a second
    # run in the same process (the test suite does this constantly) starts from nothing.
    branches, listings = Memo(), Memo()

    skills_dir = os.path.abspath(os.path.expanduser(a.skills_dir))
    checks = [check_junctions(skills_dir)]
    if inventory_problems:
        inventory = Check("inventory", "repository inventory inspection coverage")
        for name, reason in inventory_problems:
            inventory.add(UNKNOWN, name, reason)
        checks.append(inventory)
    checks.append(check_conformance(repos, a.conformance_timeout))
    checks.append(check_budget(skills_dir, code_root, a.conformance_timeout, a.listing, a.capacity))

    if a.offline:
        c = Check("ci", "EVERY workflow on EVERY repo of ours is GREEN ON THE DEFAULT BRANCH")
        c.note = "skipped (--offline)"
        c.add(UNKNOWN, "(all public repos)", "offline: CI state unobserved")
        checks.append(c)
    else:
        targets = ci_targets(slugs, timeout=a.gh_timeout, offline=a.offline,
                             listings=listings, branches=branches)
        checks.append(check_ci(targets, a.gh_timeout, branches=branches))

    elapsed = time.time() - t0
    tot = print_report(checks, started_utc, elapsed)
    exit_code = 1 if tot["fail"] else 0

    if not a.no_status:
        try:
            write_status(a.status_json, checks, tot, started_utc, elapsed, exit_code)
            print("\nstatus: %s" % a.status_json)
        except (OSError, ValueError, RuntimeError, ImportError) as e:
            print("\nstatus write FAILED: %s" % e, file=sys.stderr)
            # A caller that cannot see a fresh artifact must not be told everything is fine.
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
