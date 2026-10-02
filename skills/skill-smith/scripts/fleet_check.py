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
1. There is NO --fix and no auto-repair. Config locations may contain uncommitted state or
   secrets, so automatic convergence could destroy data. Inspect and report the current
   condition; a separate authorized workflow owns any migration or repair.
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

And on 2026-08-01 that was still not enough, because the fraction was at the END of the line. The
run read "VERDICT GREEN | pass 104 ... | coverage 56% (112 of 200 rows)" with 88 rows never
evaluated, and a reader scanning for the word after VERDICT gets GREEN and stops. So the coverage
clause is now glued to the verdict WORD, and it shouts when the sample is partial:

    VERDICT GREEN OVER 56% OF ROWS (112 of 200; 88 NOT EVALUATED) | pass 104 ...

The TOTAL line carries the same clause under its counts, because bare counts are the other thing a
reader rounds into an adjective. A disclosure the reader never reaches is not a disclosure.

WHY THIS FILE IS CONCURRENT, AND WHAT THAT IS NOT ALLOWED TO COST
------------------------------------------------------------------
Coverage grew on 2026-07-31 (live visibility per row, EVERY workflow on EVERY repo including the
private ones) and the run went from 63s to 130s, because each remote question blocked the next. For
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
Source state is read-only, including no `git fetch`; only the private report is written. Exits nonzero
if any row is FAIL. UNKNOWN and SKIP never affect the exit code, which is safe precisely because
UNKNOWN can no longer carry a finding. Prints a human-readable report to stdout and writes a
machine-readable status JSON in the verified PRIVATE versioned companion (override with
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
import contextlib
import contextvars
import concurrent.futures as futures
import fnmatch
import importlib.util
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

HERE = os.path.dirname(os.path.abspath(__file__))
CONFORMANCE = os.path.join(HERE, "check_conformance.py")
BUDGET = os.path.join(HERE, "budget_check.py")

DEFAULT_SKILLS_DIR = os.path.expanduser("~/.claude/skills")
DEFAULT_CODE_ROOT = os.path.expanduser("~/CodesClaude")
DEFAULT_VISIBILITY = os.path.expanduser("~/.pii-guard/visibility.json")
# Resolve at execution time, then verify PRIVATE versioned storage before any report write.
DEFAULT_STATUS = None

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


# --- concurrency, and why a report's wall clock is a correctness property -------------------------
# On 2026-08-01 this driver took 130s, up from 63s, because coverage grew: the visibility oracle
# started asking gh live per row, and check_ci started reading EVERY workflow on EVERY repo instead
# of two names on the public ones. Both of those were the right change. Doing them one blocking
# round trip at a time was not.
#
# Wall clock is not cosmetic for a report a human runs by hand. A two minute report gets started,
# abandoned, and then not read, which lands in exactly the same place as a gate nobody runs -- the
# failure mode the whole top of this file is written against. install.py --check had the identical
# disease and the identical cure in this same effort, going from 185s to 8s by moving its per-repo
# `git ls-remote` round trips onto a thread pool.
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
_GIT_ENVIRONMENT = contextvars.ContextVar("fleet_git_environment", default=None)


@contextlib.contextmanager
def physical_git_context(root):
    """Inspect repository configuration after the effective context authorized its owner."""
    env = {key: value for key, value in os.environ.items()
           if key.upper() not in _GIT_SELECTORS and not key.upper().startswith("GIT_CONFIG")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "safe.directory", "GIT_CONFIG_VALUE_0": root})
    token = _GIT_ENVIRONMENT.set(env)
    try:
        yield
    finally:
        _GIT_ENVIRONMENT.reset(token)


def run(args, cwd=None, timeout=60, env=None):
    """Run a command, never raise. Returns (rc, stdout, stderr); rc is None on timeout."""
    if args and os.path.basename(str(args[0])).lower() in ("git", "git.exe"):
        inherited = _GIT_ENVIRONMENT.get() if env is None else env
        inherited = os.environ if inherited is None else inherited
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
    except (OSError, UnicodeError, ValueError):
        return False
    return options.get("hostname") == "github.com" and options.get("port", "22") == "22"


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
                if host != "github.com" and not github_ssh_alias(host):
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
            if host.lower() != "github.com" and not github_ssh_alias(host.lower()):
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

    Memoized per DISTINCT (slug, path) when a memo is supplied. check_workflow already hands its
    listings to ci_targets by hand, so that is belt and braces rather than the main saving -- but it
    makes the reuse a property of the function instead of a discipline two call sites have to
    remember, so a third caller cannot reintroduce the duplicate fetch by forgetting.
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
def condition_state(value):
    """Recognize constant conditions without attempting to evaluate GitHub expressions."""
    if value is None or value is True:
        return "enabled"
    if value is False:
        return "disabled"
    expression = str(value).strip()
    if expression.startswith('${{') and expression.endswith('}}'):
        expression = expression[3:-2].strip()
    while expression.startswith('(') and expression.endswith(')'):
        expression = expression[1:-1].strip()
    if expression.lower() in ('false', '0', 'null', "''", '""'):
        return "disabled"
    return "enabled" if expression.lower() in ('true', '1') else "conditional"


def workflow_guards(text, conditions=None):
    """Read configured guard actions from workflow jobs, never from filenames or comments."""
    try:
        import yaml
    except ImportError as exc:
        raise ValueError("PyYAML is required to inspect workflow actions") from exc
    try:
        workflow = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError("workflow YAML is invalid") from exc
    if not isinstance(workflow, dict) or not isinstance(workflow.get("jobs"), dict):
        raise ValueError("workflow has no jobs object")
    found = set()
    for job in workflow["jobs"].values():
        if not isinstance(job, dict) or condition_state(job.get("if")) == "disabled":
            continue
        steps = job.get("steps", [])
        if not isinstance(steps, list):
            raise ValueError("workflow steps must be a list")
        for step in steps:
            if not isinstance(step, dict) or condition_state(step.get("if")) == "disabled":
                continue
            action = str(step.get("uses", "")).split("@", 1)[0].rstrip("/")
            for guard, kit in (("pii-guard", "guards"), ("dash-guard", "style")):
                if action in ("./ci/" + guard, "./%s/ci/%s" % (kit, guard)):
                    found.add(guard)
                    if conditions is not None and any(condition_state(item.get("if")) == "conditional"
                                                      for item in (job, step)):
                        conditions.add(guard)
    return [guard for guard in GUARD_WORKFLOWS if guard in found]


def required_guards(role):
    if role == "security-kit":
        return ["pii-guard"]
    if role in ("skill", "style-kit"):
        return list(GUARD_WORKFLOWS)
    raise ValueError("unknown repository role: %s" % role)


def remote_guard_coverage(slug, names, timeout, offline=False, branches=None):
    gh = shutil.which("gh")
    if offline or not gh:
        return None, "workflow action bodies not observed (offline or gh unavailable)"
    branch, rc, error = branch_probe(gh, slug, timeout, branches)
    if rc:
        return None, "gh could not reach %s: %s" % (slug, error or "exit %s" % rc)
    if not branch:
        return None, "gh returned no default branch for %s" % slug
    found = set()
    conditional = set()
    for filename in names:
        endpoint = "repos/%s/contents/.github/workflows/%s?ref=%s" % (slug, quote(filename, safe=""), quote(branch, safe=""))
        rc, so, se = run([gh, "api", endpoint, "-H", "Accept: application/vnd.github.raw+json"], timeout=timeout)
        if rc:
            return None, "workflow body unavailable: %s" % (first_line(se) or filename)
        try:
            found.update(workflow_guards(so, conditional))
        except ValueError as exc:
            return None, str(exc)
    note = "conditional execution unverified: " + ", ".join(sorted(conditional)) if conditional else ""
    return [g for g in GUARD_WORKFLOWS if g in found], note


def check_workflow(visibility_path, slugs, code_root, timeout=30, offline=False,
                    listings=None, branches=None, policies=None, oracle=None):
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
    c.visibility_oracle = oracle or VisibilityOracle(visibility_path, offline=offline, timeout=timeout)
    oracle = c.visibility_oracle
    c.note = ("the REMOTE is interrogated, never the working tree; entries with no clone under %s "
              "are skipped; cloned origins use current visibility" % code_root)
    if oracle.error:
        c.note += "; visibility map unreadable: %s" % oracle.error
        if not slugs:
            c.add(UNKNOWN, os.path.basename(visibility_path), oracle.error)
    oracle.prefetch(slugs)
    visibility = {slug: oracle.visibility(slug) for slug in sorted(slugs)}
    public = sorted(slug for slug, (value, _why) in visibility.items() if value == "PUBLIC")
    for slug, (value, why) in visibility.items():
        if value == "UNKNOWN":
            c.add(UNKNOWN, slug, "visibility not observed: %s" % why)
    for slug in sorted(oracle.map):
        if oracle._mapped(slug) == "PUBLIC" and slug not in slugs:
            c.add(SKIP, slug, "no local clone")
    # Fetch every listing CONCURRENTLY, then emit the rows in the same sorted order as before. Each
    # listing is two blocking gh round trips and there are ~17 of them with a clone here; serially
    # that alone was over half a minute of this report's wall clock.
    fetched = dict(zip(public, pmap(
        lambda s: remote_workflow_files(s, slugs[s], timeout, offline=offline,
                                         memo=listings, branches=branches), public)))
    coverage = dict(zip(public, pmap(
        lambda s: remote_guard_coverage(s, fetched[s][0], timeout, offline, branches)
        if fetched[s][0] is not None else (None, fetched[s][1]), public)))
    for slug in public:
        names, why = fetched[slug]
        if names is None:
            # Could not look. Say so; do not award a pass for a question never asked.
            c.add(UNKNOWN, slug, "remote not observed: %s" % why)
            continue
        c.all_remote_workflows[slug] = list(names)
        found, body_why = coverage[slug]
        if found is None:
            c.add(UNKNOWN, slug, "remote workflow actions not observed: %s" % body_why)
            continue
        c.remote_workflows[slug] = found
        policy = (policies or {}).get(slug, {"role": "skill"})
        try:
            role = policy["role"]
            if role != "skill" and not policy.get("reason"):
                raise ValueError("non-skill role requires a reviewed reason")
            required = required_guards(role)
        except (ValueError, TypeError, KeyError) as exc:
            c.add(FAIL, slug, "invalid role policy: %s" % exc)
            continue
        missing = [g for g in required if g not in found]
        if missing:
            c.add(FAIL, slug, "PUBLIC but the remote default branch has no %s configured action (remote workflows: %s)"
                  % (", ".join(missing), ", ".join(names) or "none"))
        else:
            c.add(PASS, slug, "remote actions: %s; role=%s%s%s" % (", ".join(found), role,
                  (" (%s)" % policy["reason"]) if policy.get("reason") else "",
                  ("; " + body_why) if body_why else ""))
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


def publication_routes(repo_path, timeout=20):
    """Resolve Git's default push remote and every effective URL for allowed push routes.

    The documented explicit origin route is checked as well as the default selected by
    branch.pushRemote, remote.pushDefault, branch.remote, then origin. Git expands URL
    rewrites in get-url; unsupported identities and ambiguous configuration fail closed.
    """
    def query(*args):
        return run(["git", "-C", repo_path, *args], timeout=timeout)

    def setting(key):
        rc, output, error = query("config", "--null", "--get-all", key)
        if rc == 1 and not output and not error:
            return None
        if rc != 0 or not output.endswith("\0"):
            raise ValueError("Cannot verify PRIVATE publication routing configuration")
        values = output[:-1].split("\0")
        if len(values) != 1 or not values[0] or values[0] != values[0].strip():
            raise ValueError("Ambiguous PRIVATE publication routing configuration")
        return values[0]

    rc, branch, error = query("symbolic-ref", "--quiet", "--short", "HEAD")
    if rc == 1 and not branch and not error:
        branch = None  # Detached HEAD still has an explicit origin push route.
    elif rc != 0 or not branch.strip() or any(c in branch.strip() for c in "\r\n\0"):
        raise ValueError("Cannot verify PRIVATE publication branch routing")
    else:
        branch = branch.strip()
    branch_push = setting("branch.%s.pushRemote" % branch) if branch else None
    push_default = setting("remote.pushDefault")
    branch_remote = setting("branch.%s.remote" % branch) if branch else None
    selected = branch_push or push_default or branch_remote or "origin"
    if selected == "." or selected.startswith("-") or any(c.isspace() for c in selected):
        raise ValueError("Unsupported PRIVATE publication push remote")
    routes = {}
    for remote in dict.fromkeys(("origin", selected)):
        rc, output, _error = query("remote", "get-url", "--push", "--all", remote)
        urls = output.splitlines()
        if rc != 0 or not urls:
            raise ValueError("Cannot verify PRIVATE publication push URLs")
        slugs = [slug_from_url(url) for url in urls]
        if any(slug is None for slug in slugs):
            raise ValueError("PRIVATE publication push destination has an unsupported identity")
        routes[remote] = sorted(set(slugs))
    return selected, routes


def publication_identity(repo_path, timeout=None):
    """Collect fetch/push identities; None preserves the helpers' default call shape."""
    options = {} if timeout is None else {"timeout": timeout}
    slug = origin_slug(repo_path, **options)
    if not slug:
        raise ValueError("DATA destination requires a verified PRIVATE GitHub origin identity")
    selected, routes = publication_routes(repo_path, **options)
    return slug, selected, routes


def private_publication_proof(identity, oracle):
    """Require PRIVATE visibility for every collected fetch and push destination."""
    slug, selected, routes = identity
    destinations = {slug, *(target for targets in routes.values() for target in targets)}
    for target in sorted(destinations):
        visibility, how = oracle.visibility(target)
        if visibility == "PUBLIC":
            raise ValueError("PUBLIC repo %s is not a PRIVATE DATA destination (%s); failing closed"
                             % (target, how))
        if visibility != "PRIVATE":
            raise ValueError("Publication destination %s must be verified PRIVATE; got %s (%s); failing closed"
                             % (target, visibility, how))
    push_proof = "; ".join("push[%s]=%s" % (remote, ",".join(targets)) for remote, targets in routes.items())
    return "PRIVATE fetch=%s; %s; default=%s" % (slug, push_proof, selected)




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
        # Memo, not a plain dict: this oracle is now asked from a thread pool (see prefetch), and a
        # cache that can be missed twice for the same slug would put the per-row gh cost straight
        # back. The token cache below is the bigger of the two savings -- `gh auth token --user X`
        # used to be re-shelled once per account PER SLUG, so the accounts loop cost up to two extra
        # child processes on every single row it touched.
        self.cache = Memo()
        self.tokens = Memo()
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

    def _token(self, gh, acct):
        """The stored token for one gh account, or "" if there is not one. Never logged."""
        rc, tok, _se = run([gh, "auth", "token", "--hostname", "github.com", "--user", acct], timeout=self.timeout)
        tok = first_line(tok)
        return tok if rc == 0 and tok else ""

    def _accounts(self, gh):
        """Every gh account logged in on this machine, discovered at run time.

        This used to be a hardcoded pair of logins. Two account names sitting next to a comment
        that explains one machine holds both tokens states, in effect, that those accounts are
        the same operator, and this repo is PUBLIC. A machine that runs several accounts keeps
        that mapping in ~/.pii-guard/identities.conf, deliberately outside every worktree so it
        is never vendored into a public repo; a literal list here walked straight around that.
        Asking gh at run time works for anyone, with one account or five, and says nothing at
        all about who is running it.
        """
        rc, so, se = run([gh, "auth", "status", "--hostname", "github.com"], timeout=self.timeout)
        found = []
        for line in ((so or "") + "\n" + (se or "")).splitlines():
            if " account " not in line:
                continue
            tail = line.split(" account ", 1)[1].strip()
            if not tail:
                continue
            name = tail.split()[0].split("(")[0].strip()
            if name and name not in found:
                found.append(name)
        return found

    def _ask_gh(self, slug):
        """(visibility, how) from a live query, or (None, why-it-could-not-answer)."""
        if self.offline:
            return None, "--offline forbids asking gh"
        gh = shutil.which("gh")
        if not gh:
            return None, "gh is not on PATH"
        # Every logged in identity: a private repo owned by one account is a 404 to another's
        # token, so asking with only one of them turns "private, and you cannot see it" into
        # "no answer". visibility_of.py handles this with `gh auth switch`, which rewrites the
        # machine's ACTIVE account. This tool is read-only, so it borrows each token for one
        # child process instead and leaves the active account exactly where it found it.
        def accounts():
            yield None
            yield from self._accounts(gh)

        for acct in accounts():
            env = None
            if acct:
                # Memoized per ACCOUNT, not per (account, slug): the token does not depend on which
                # repo is being asked about, and re-deriving it per row was pure repetition.
                tok = self.tokens.get(acct, lambda a=acct: self._token(gh, a))
                if not tok:
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

    def _resolve(self, slug):
        live, how = self._ask_gh(slug)
        if live:
            cached = self._mapped(slug)
            if cached in ("PUBLIC", "PRIVATE") and cached != live:
                how += "; the visibility map still says %s and is STALE" % cached
            return live, how
        return self._from_map(slug, how)

    def visibility(self, slug):
        if not slug:
            return "UNKNOWN", "no origin remote"
        return self.cache.get(slug, lambda: self._resolve(slug))

    def prefetch(self, slugs):
        """Warm the cache for a set of slugs concurrently. Answers are unchanged, only their timing.

        Callers still read every answer back through visibility(), one row at a time, in whatever
        order they print in. This exists so the WAITING happens once in parallel rather than
        strung out across a serial row loop; the memo is what makes the second read free, and
        makes calling this optional rather than load bearing.
        """
        want = sorted({s for s in slugs if s})
        if want:
            pmap(self.visibility, want)


def data_skill_identity(root):
    """Companion identity comes from plugin metadata, independently of the checkout name."""
    path = os.path.join(root, ".claude-plugin", "plugin.json")
    try:
        with open(path, encoding="utf-8") as stream:
            plugin = json.load(stream)
    except (OSError, ValueError) as error:
        raise ValueError("plugin identity metadata is missing or unreadable") from error
    name = plugin.get("name") if isinstance(plugin, dict) else None
    if not isinstance(name, str) or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) is None:
        raise ValueError("plugin identity metadata requires a valid name")
    return name


def check_data_boundary(visibility_path, repos, offline=False, timeout=30, oracle=None):
    """Assert no skill's real-run output resolves into a repo the world can read.

    Real-run output belongs in a versioned PRIVATE companion. Being inside a Git worktree
    is not itself a violation: the publication destinations determine whether DATA can leak.
    PUBLIC and UNKNOWN fail closed; PRIVATE passes and names the approved repository.
    An unversioned destination fails because it cannot supply the required private history.
    """
    c = Check("databoundary",
              "resolved real-run data dirs are never inside a PUBLIC or UNKNOWN repo")
    c.note = ("DATA belongs in the PRIVATE companion repo, versioned; a data dir inside a private "
              "repo PASSES and the repo is named. Unknown visibility FAILS CLOSED. An uninitialized "
              "skill has no data dir yet, which is the correct shipping state. Visibility comes from "
              "LIVE gh; the map only votes when gh cannot answer, and only while it is younger than "
              "%s" % human_age(VisibilityOracle.MAX_MAP_AGE_S))
    oracle = oracle or VisibilityOracle(visibility_path, offline=offline, timeout=timeout)
    if oracle.error:
        c.note += " | visibility map unreadable (%s): there is no fallback left" % oracle.error
    else:
        age, trouble = oracle.map_age()
        c.note += (" | the map %s" % trouble if trouble
                   else " | the map was refreshed %s ago" % human_age(age))
    # THREE PHASES, and the split is only about when the WAITING happens.
    #
    #   1. resolve, serially. Every step here is local, and load_datadir() exec's a module into
    #      sys.modules, which is not something to do from eight threads at once for the sake of a
    #      few milliseconds. Rows that need no remote answer are decided outright.
    #   2. prefetch, concurrently. The gh visibility lookups, which are the only network in this
    #      check and were previously one blocking round trip per row inside the loop.
    #   3. emit, serially, in the same sorted order as before, reading the memo.
    #
    # A deferred row carries everything phase 3 needs, so phase 3 makes no decision phase 1 did not
    # already make. The set of rows and their contents are identical to the single-loop version.
    plan = []  # Immediate rows or deferred (name, resolved, publication identity) records.
    for name, path in sorted(repos.items()):
        dd = os.path.join(path, "guards", "tools", "datadir.py")
        if not os.path.isfile(dd):
            plan.append(("row", UNKNOWN, name,
                         "pinned guards/tools/datadir.py missing; initialize the guards submodule. "
                         "No consumer tools/ fallback is permitted"))
            continue
        # Use the resolver THAT REPO would use: the question is where ITS resolver points, and
        # a re-implementation here would answer a subtly different question the moment one drifts.
        try:
            skill = data_skill_identity(path)
            mod = load_datadir(dd, "fleet_datadir_%s" % skill.replace("-", "_"))
            resolved = mod.resolve_data_dir(skill, create=False)
        except Exception as e:                                   # noqa: BLE001 (report, never crash)
            # The resolver's own refusal is a FINDING, not a gap. datadir.py raises
            # DataDirInsideOwnRepo when a data dir resolves inside the skill repo that ships it --
            # the in-repo fallback shape. Reporting that as UNKNOWN would file a caught violation
            # under "could not observe", which is the exact rounding this file exists to prevent.
            if type(e).__name__ == "DataDirInsideOwnRepo":
                plan.append(("row", FAIL, name, first_line(str(e)) or str(e)))
            else:
                plan.append(("row", UNKNOWN, name, "cannot resolve plugin identity or load guards/tools/datadir.py: %s" % e))
            continue
        if resolved is None:
            plan.append(("row", SKIP, name, "not initialized"))
            continue
        resolved = str(resolved)
        if not os.path.isdir(resolved):
            # resolve_data_dir() is supposed to return only existing dirs, so this means a vendored
            # copy has drifted. It matters because `git -C <missing>` exits nonzero, which the
            # worktree probe would otherwise read as a clean "outside any repo".
            plan.append(("row", UNKNOWN, name,
                         "resolver returned %s, which does not exist" % resolved))
            continue
        inside, top = in_git_worktree(resolved)
        if inside is None:
            plan.append(("row", UNKNOWN, name, "%s: %s" % (resolved, top)))
            continue
        if not inside:
            plan.append(("row", FAIL, name,
                         "%s is unversioned; DATA requires a verified PRIVATE companion repository" % resolved))
            continue
        try:
            identity = publication_identity(top, timeout=timeout)
        except ValueError as error:
            plan.append(("row", FAIL, name, "%s: %s" % (resolved, error)))
            continue
        plan.append(("vis", name, resolved, identity))

    # Phase 2. One concurrent burst instead of one blocking gh call per deferred row.
    destinations = set()
    for entry in plan:
        if entry[0] == "vis":
            slug, _selected, routes = entry[3]
            destinations.add(slug)
            destinations.update(target for targets in routes.values() for target in targets)
    oracle.prefetch(sorted(destinations))

    # Phase 3.
    for entry in plan:
        if entry[0] == "row":
            _k, status, name, detail = entry
            c.add(status, name, detail)
            continue
        _k, name, resolved, identity = entry
        try:
            proof = private_publication_proof(identity, oracle)
        except ValueError as error:
            c.add(FAIL, name, "data dir %s: %s" % (resolved, error))
        else:
            c.add(PASS, name, "%s [%s] versioned in the private companion repo" % (resolved, proof))
    return c


# --- check 6: is the authority green? --------------------------------------------------------------
GREEN = ("success",)
RED = ("failure", "timed_out", "cancelled", "startup_failure", "action_required")


def default_branch(gh, slug, timeout, cache=None):
    """(branch, why-not) for a slug's remote default branch.

    Backed by the SAME memo the workflow check fills, so a slug whose default branch was already
    established while listing its workflows costs nothing here. It also removes the possibility of
    the two checks resolving different branches for one repo mid-run.
    """
    b, rc, se = branch_probe(gh, slug, timeout, cache)
    return b, ("" if b else (se or "gh exit %s" % rc))


def ci_targets(wf_check, visibility_path, slugs, timeout, offline=False,
               listings=None, branches=None):
    """[(slug, names_or_None, why, visibility)] for EVERY repo of ours that has a clone here.

    check_workflow checks PUBLIC repos, because guard PRESENCE is a public-remote policy.
    CI greenness is not, and at least one PRIVATE repo here carries a real guard workflow that no
    fleet report has ever read. A private repo's CI going red is exactly as much a broken thing as a
    public one's, so the listing is fetched for the private repos too rather than reusing a set that
    was assembled to answer a different question.

    Listings already obtained by check_workflow are reused verbatim, so the public repos cost no
    extra API calls.
    """
    seen = getattr(wf_check, "all_remote_workflows", {}) or {}
    oracle = getattr(wf_check, "visibility_oracle", None)
    if oracle is None:
        oracle = VisibilityOracle(visibility_path, offline=offline, timeout=timeout)
    oracle.prefetch(set(slugs) | set(seen))
    out = [(s, n, "", oracle.visibility(s)[0]) for s, n in sorted(seen.items())]
    # The repos check_workflow never walked, chiefly the PRIVATE ones. Fetched CONCURRENTLY and
    # appended in the same sorted order; pmap preserves input order, so `out` is byte-identical to
    # what the serial loop produced.
    extra = [s for s in sorted(slugs) if s not in seen]
    #                             ^ no clone here: not ours to interrogate, and check_workflow
    #                               already records the SKIP for the public ones
    for slug, (names, why) in zip(extra, pmap(
            lambda s: remote_workflow_files(s, slugs[s], timeout, offline=offline,
                                            memo=listings, branches=branches), extra)):
        out.append((slug, names, why, oracle.visibility(slug)[0]))
    return out


def workflow_tier(filename):
    """"guard" if this workflow file is one of GUARD_WORKFLOWS, else "other". Never filters."""
    return "guard" if os.path.splitext(filename)[0].lower() in GUARD_WORKFLOWS else "other"


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
    c.execution = {}
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

    ordered = sorted(targets, key=lambda t: t[0])
    # A fresh memo when the caller supplies none reproduces the old per-call `branches = {}` cache
    # exactly: one lookup per repo, not one per workflow. main() passes the shared one so a branch
    # already resolved by the workflow check is not resolved a second time here.
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
    for slug, workflows, _why, _vis in ordered:
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

    for slug, workflows, listing_why, visibility in ordered:
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
    """Resolve a real-run destination through the consumer's pinned resolver."""
    repo = os.path.realpath(os.path.join(HERE, "..", "..", ".."))
    module = load_datadir(os.path.join(repo, "guards", "tools", "datadir.py"), "skill_smith_datadir")
    # Bind the consumer explicitly so linked worktrees retain sibling discovery.
    module._own_repo_root = lambda: repo
    directory = module.resolve_data_dir("skill-smith")
    if directory is None:
        raise ValueError("Initialize the private skill-smith companion or set SKILL_SMITH_CONFIG; no DATA fallback")
    return os.path.join(directory, name)


def resolve_status_path(path, visibility_path, offline=False, oracle=None, *,
                        default_name="fleet-check-status.json", directory=False):
    """Resolve status, worklist or backup DATA into a verified PRIVATE repository."""
    repo = os.path.realpath(os.path.join(HERE, "..", "..", ".."))
    path = reject_output_aliases(default_data_path(default_name) if path is None else path)
    if os.path.exists(path) and os.path.isdir(path) != directory:
        raise ValueError("DATA destination has the wrong file/directory type")
    try:
        inside_own = os.path.commonpath([os.path.normcase(repo), os.path.normcase(path)]) == os.path.normcase(repo)
    except ValueError:  # Different Windows volumes cannot contain one another.
        inside_own = False
    if inside_own:
        raise ValueError("Report DATA cannot be written inside the tool repository")
    parent = path if directory and os.path.isdir(path) else os.path.dirname(path)
    while not os.path.isdir(parent):
        higher = os.path.dirname(parent)
        if higher == parent:
            raise ValueError("Report requires an existing PRIVATE versioned companion")
        parent = higher
    inside, root = in_git_worktree(parent)
    if inside is not True:
        raise ValueError("Report requires a PRIVATE versioned companion, not an unversioned directory")
    identity = publication_identity(root)
    oracle = oracle or VisibilityOracle(visibility_path, offline=offline)
    effective_proof = private_publication_proof(identity, oracle)
    with physical_git_context(root):
        physical_inside, physical_root = in_git_worktree(parent)
        if (physical_inside is not True or
                os.path.normcase(os.path.abspath(physical_root)) != os.path.normcase(os.path.abspath(root))):
            raise ValueError("Physical and effective Git contexts disagree about PRIVATE DATA ownership")
        physical_proof = private_publication_proof(publication_identity(root), oracle)
    return path, effective_proof + "; physical: " + physical_proof


def write_status(path, checks, tot, started_utc, elapsed, exit_code):
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
    ap.add_argument("--visibility", default=DEFAULT_VISIBILITY)
    ap.add_argument("--listing", help="captured current skill listing for measured G3 visibility; absent evidence stays UNKNOWN")
    ap.add_argument("--capacity", type=int, help="explicit current G3 capacity policy; historical estimates are not enforced")
    ap.add_argument("--workflow-policy", help="reviewed JSON mapping repo slug to role and reason; public security is always required")
    ap.add_argument("--status-json", default=DEFAULT_STATUS,
                    help="machine-readable result; the caller checks its utc for freshness")
    ap.add_argument("--no-status", action="store_true", help="do not write the status file")
    ap.add_argument("--offline", action="store_true",
                    help="skip the CI check (no network, no gh)")
    ap.add_argument("--gh-timeout", type=int, default=30)
    ap.add_argument("--conformance-timeout", type=int, default=300)
    a = ap.parse_args(argv)
    policies = None
    if a.workflow_policy:
        try:
            with open(a.workflow_policy, encoding="utf-8") as f:
                policies = json.load(f)
            if not isinstance(policies, dict):
                raise ValueError("workflow policy must be an object")
        except (OSError, ValueError) as e:
            print("workflow policy rejected: %s" % e, file=sys.stderr)
            return 1

    oracle = VisibilityOracle(a.visibility, offline=a.offline, timeout=a.gh_timeout)
    if not a.no_status:
        try:
            a.status_json, storage_proof = resolve_status_path(a.status_json, a.visibility, a.offline, oracle)
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
    wf = check_workflow(os.path.abspath(os.path.expanduser(a.visibility)), slugs, code_root,
                        timeout=a.gh_timeout, offline=a.offline,
                        listings=listings, branches=branches, policies=policies, oracle=oracle)
    checks.append(wf)
    checks.append(check_conformance(repos, a.conformance_timeout))
    checks.append(check_budget(skills_dir, code_root, a.conformance_timeout, a.listing, a.capacity))
    checks.append(check_data_boundary(os.path.abspath(os.path.expanduser(a.visibility)),
                                      repos=repos, offline=a.offline, timeout=a.gh_timeout, oracle=oracle))

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
                             timeout=a.gh_timeout, offline=a.offline,
                             listings=listings, branches=branches)
        checks.append(check_ci(targets, a.gh_timeout, branches=branches))

    elapsed = time.time() - t0
    tot = print_report(checks, started_utc, elapsed)
    exit_code = 1 if tot["fail"] else 0

    if not a.no_status:
        try:
            write_status(a.status_json, checks, tot, started_utc, elapsed, exit_code)
            print("\nstatus: %s [%s]" % (a.status_json, storage_proof))
        except OSError as e:
            print("\nstatus write FAILED: %s" % e, file=sys.stderr)
            # A caller that cannot see a fresh artifact must not be told everything is fine.
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
