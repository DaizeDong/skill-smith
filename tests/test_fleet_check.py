#!/usr/bin/env python3
"""Tests for scripts/fleet_check.py, the read-only fleet driver.

The point of this file is the two properties that decide whether the driver is worth having:

  1. It is READ-ONLY and has no --fix. A driver that quietly repairs things is a driver that can
     destroy live secrets and uncommitted state in the config dirs it inspects.
  2. A check that cannot observe something reports SKIP or UNKNOWN, never FAIL. A nightly check that
     goes red for a reason no edit can fix trains the operator to skip the digest line, which is the
     exact way check_conformance.py died the first time.

Everything below runs against synthetic trees in tmp_path. No network, no gh, no real repos.

Run:  python -m pytest -q   (from repo root)
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_REPO, "skills", "skill-smith", "scripts")
FLEET = os.path.join(_SCRIPTS, "fleet_check.py")

_spec = importlib.util.spec_from_file_location("fleet_check_under_test", FLEET)
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)


def git(*args, cwd):
    return subprocess.run(["git"] + list(args), cwd=str(cwd),
                          capture_output=True, text=True, timeout=60)


def make_repo(root, name, plugin=False, workflow=False, datadir=False, origin=None):
    """A minimal fake fleet repo. Only the files the driver actually looks at."""
    d = root / name
    (d / ".git").mkdir(parents=True)            # enough for local_repos(); no real git needed
    if plugin:
        (d / ".claude-plugin").mkdir()
        (d / ".claude-plugin" / "plugin.json").write_text('{"name": "%s"}' % name, encoding="utf-8")
    if workflow:
        (d / ".github" / "workflows").mkdir(parents=True)
        (d / ".github" / "workflows" / "pii-guard.yml").write_text("name: pii-guard\n",
                                                                   encoding="utf-8")
    if datadir:
        (d / "tools").mkdir(exist_ok=True)
        # A stand-in with the same contract as the vendored tools/datadir.py.
        (d / "tools" / "datadir.py").write_text(
            "import os\n"
            "from pathlib import Path\n"
            "def resolve_data_dir(skill, create=False):\n"
            "    v = os.environ.get(skill.upper().replace('-', '_') + '_DATA_DIR')\n"
            "    if v and Path(v).is_dir():\n"
            "        return Path(v)\n"
            "    return None\n",
            encoding="utf-8")
    if origin:
        (d / "origin.txt").write_text(origin, encoding="utf-8")
    return d


# --- slug parsing ----------------------------------------------------------------------------
@pytest.mark.parametrize("url,want", [
    ("https://github.com/DaizeDong/skill-smith.git", "daizedong/skill-smith"),
    ("https://github.com/DaizeDong/skill-smith", "daizedong/skill-smith"),
    ("git@github.com:DaizeDong/skill-smith.git", "daizedong/skill-smith"),
    # the ssh host-alias form this fleet actually uses; the old naive parser got this one wrong
    ("git@daizedong:DaizeDong/skill-smith.git", "daizedong/skill-smith"),
    ("ssh://git@github.com/DaizeDong/skill-smith.git", "daizedong/skill-smith"),
])
def test_slug_from_url(url, want):
    assert fc.slug_from_url(url) == want


def test_slug_from_url_garbage():
    assert fc.slug_from_url("") is None
    assert fc.slug_from_url("not-a-url") is None


# --- check 2: PUBLIC implies the guards are ON THE REMOTE ---------------------------------------
def _vis(tmp_path, mapping):
    p = tmp_path / "visibility.json"
    p.write_text(json.dumps(mapping), encoding="utf-8")
    return str(p)


def _fake_remote(monkeypatch, table):
    """Stub the remote observation. table maps slug -> list of filenames, or None for unobservable."""
    # **_kw absorbs the per-run memo handles the real signature grew when the remote queries were
    # moved onto a thread pool. The stub answers from `table` either way, so every assertion below
    # is testing the same thing it was before.
    def fake(slug, path, timeout, offline=False, **_kw):
        names = table.get(slug, [])
        if names is None:
            return None, "stubbed outage"
        return names, ""
    monkeypatch.setattr(fc, "remote_workflow_files", fake)


BOTH = ["dash-guard.yml", "pii-guard.yml"]


def test_workflow_reads_the_remote_not_the_working_tree(tmp_path, monkeypatch):
    """THE regression that motivated the rewrite (claude-codex-memory-sync, 2026-07-30).

    The local clone carries pii-guard.yml -- committed, even. The REMOTE default branch does not.
    The old check stat()ed the working tree and printed PASS for a public repo whose CI was
    completely ungated. A file on this disk is not CI.
    """
    root = tmp_path / "code"
    root.mkdir()
    make_repo(root, "unpushed", workflow=True)          # the file IS here locally
    assert (root / "unpushed" / ".github" / "workflows" / "pii-guard.yml").is_file()
    _fake_remote(monkeypatch, {"owner/unpushed": ["test.yml"]})   # ...and NOT on the remote

    c = fc.check_workflow(_vis(tmp_path, {"owner/unpushed": "PUBLIC"}),
                          {"owner/unpushed": str(root / "unpushed")}, str(root))
    assert [s for s, _n, _d in c.rows] == [fc.FAIL]
    assert "pii-guard" in c.rows[0][2] and "dash-guard" in c.rows[0][2]


def test_workflow_passes_only_when_the_remote_carries_every_guard(tmp_path, monkeypatch):
    _fake_remote(monkeypatch, {"owner/full": BOTH, "owner/half": ["pii-guard.yml"]})
    c = fc.check_workflow(_vis(tmp_path, {"owner/full": "PUBLIC", "owner/half": "PUBLIC"}),
                          {"owner/full": "/x", "owner/half": "/y"}, "/code")
    got = {n: s for s, n, _d in c.rows}
    assert got == {"owner/full": fc.PASS, "owner/half": fc.FAIL}
    # the half repo must name the guard that is missing, not just say "something is wrong"
    assert "dash-guard" in dict((n, d) for _s, n, d in c.rows)["owner/half"]


def test_workflow_unreachable_remote_is_unknown_never_pass(tmp_path, monkeypatch):
    """A question that could not be asked must never be recorded as a satisfied answer."""
    _fake_remote(monkeypatch, {"owner/dark": None})
    c = fc.check_workflow(_vis(tmp_path, {"owner/dark": "PUBLIC"}), {"owner/dark": "/x"}, "/code")
    assert [s for s, _n, _d in c.rows] == [fc.UNKNOWN]
    assert c.count(fc.PASS) == 0 and c.count(fc.FAIL) == 0


def test_workflow_offline_does_not_manufacture_a_pass(tmp_path):
    """--offline must not quietly restore the local-stat fail-open by another route."""
    root = tmp_path / "code"
    root.mkdir()
    make_repo(root, "unpushed", workflow=True)
    c = fc.check_workflow(_vis(tmp_path, {"owner/unpushed": "PUBLIC"}),
                          {"owner/unpushed": str(root / "unpushed")}, str(root), offline=True)
    assert [s for s, _n, _d in c.rows] == [fc.UNKNOWN]


def test_workflow_records_what_the_remote_carries_for_the_ci_check(tmp_path, monkeypatch):
    _fake_remote(monkeypatch, {"owner/full": BOTH, "owner/dark": None})
    c = fc.check_workflow(_vis(tmp_path, {"owner/full": "PUBLIC", "owner/dark": "PUBLIC"}),
                          {"owner/full": "/x", "owner/dark": "/y"}, "/code")
    assert c.remote_workflows == {"owner/full": ["pii-guard", "dash-guard"]}


def test_workflow_phantom_entry_skips_not_fails(tmp_path):
    """The visibility map outlives its working copies and names repos not checked out here.

    Failing on one would make the check permanently red for a reason no edit in any repo can fix.
    """
    c = fc.check_workflow(_vis(tmp_path, {"owner/never-cloned": "PUBLIC"}), {}, str(tmp_path))
    assert [s for s, _n, _d in c.rows] == [fc.SKIP]
    assert c.count(fc.FAIL) == 0


def test_workflow_private_entries_are_not_checked(tmp_path):
    c = fc.check_workflow(_vis(tmp_path, {"owner/secret": "PRIVATE", "owner/dunno": "UNKNOWN"}),
                          {}, str(tmp_path))
    assert c.rows == []


def test_workflow_unreadable_map_is_unknown_not_fail(tmp_path):
    c = fc.check_workflow(str(tmp_path / "nope.json"), {}, str(tmp_path))
    assert c.count(fc.FAIL) == 0
    assert c.count(fc.UNKNOWN) == 1


# --- the remote observer itself -----------------------------------------------------------------
def test_remote_reachable_repo_with_no_workflows_dir_is_an_answer(monkeypatch):
    """gh 404 on the contents path, AFTER the repo probe succeeded, means "not there" -- a finding.

    Reading it as an outage instead is exactly how a missing guard hid inside an UNKNOWN.
    """
    calls = []

    def fake_run(args, **_k):
        calls.append(args)
        if args[2].startswith("repos/") and args[2].count("/") == 2:
            return 0, "main\n", ""
        return 1, "", "gh: Not Found (HTTP 404)"

    monkeypatch.setattr(fc.shutil, "which", lambda _n: "gh")
    monkeypatch.setattr(fc, "run", fake_run)
    names, why = fc.remote_workflow_files("owner/repo", "/x", 5)
    assert names == [] and why == ""


def test_remote_unreachable_repo_is_unobservable(monkeypatch):
    monkeypatch.setattr(fc.shutil, "which", lambda _n: "gh")
    monkeypatch.setattr(fc, "run", lambda *_a, **_k: (1, "", "gh: could not resolve host"))
    names, why = fc.remote_workflow_files("owner/repo", "/x", 5)
    assert names is None and why


def test_remote_offline_is_unobservable():
    names, why = fc.remote_workflow_files("owner/repo", "/x", 5, offline=True)
    assert names is None and "offline" in why


def test_guards_present_matches_by_stem():
    assert fc.guards_present(["pii-guard.yml", "dash-guard.yaml", "test.yml"]) == \
        ["pii-guard", "dash-guard"]
    assert fc.guards_present(["test.yml"]) == []
    assert fc.guards_present([]) == []


# --- check 4: the inverse data boundary ---------------------------------------------------------
#
# THE PREDICATE THIS BLOCK PINS DOWN (changed 2026-07-31)
# ------------------------------------------------------
# The old assertion was "the resolved data dir is not inside a git worktree", and it condemned the
# shape the fleet is supposed to have. Real-run output LIVES IN the private companion repo,
# versioned. Implementing "must not reach a public repo" as "must not be in git" made the correct
# answer red, which is how a live ledger got moved out to a loose unversioned directory to appease
# a checker. What follows pins the RIGHT predicate: PUBLIC fails, UNKNOWN fails closed, PRIVATE
# passes and the row names the repo so an approving row cannot be mistaken for a skipped one.
def _vis_map(tmp_path, mapping, stamp="now", name="visibility.json"):
    """A visibility map on disk.

    Stamped FRESH by default. The stamp is what tells a consumer how old the cached answers are;
    an unstamped map is of unknown age and is deliberately not trusted (see the freshness block
    further down), so the tests that are about PUBLIC/PRIVATE semantics rather than about staleness
    have to hand over a map that is entitled to answer at all.
    """
    m = dict(mapping)
    if stamp == "now":
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if stamp is not None:
        m[fc.VisibilityOracle.STAMP_KEY] = stamp
    p = tmp_path / name
    p.write_text(json.dumps(m), encoding="utf-8")
    return str(p)


def _companion(tmp_path, name, origin):
    """A real git worktree standing in for a companion config repo."""
    d = tmp_path / name
    (d / "data").mkdir(parents=True)
    assert git("init", "-q", cwd=d).returncode == 0
    if origin:
        assert git("remote", "add", "origin", origin, cwd=d).returncode == 0
    return d


def test_data_dir_inside_a_public_repo_fails(tmp_path, monkeypatch):
    """The harm the check exists for: real-run output resolving somewhere the world can read."""
    root = tmp_path / "code"
    root.mkdir()
    make_repo(root, "leaky", datadir=True)
    comp = _companion(tmp_path, "pub-repo", "git@github.com:Owner/pub-repo.git")
    monkeypatch.setenv("LEAKY_DATA_DIR", str(comp / "data"))

    vis = _vis_map(tmp_path, {"owner/pub-repo": "PUBLIC"})
    c = fc.check_data_boundary(vis, repos={"leaky": str(root / "leaky")}, offline=True)
    assert [s for s, _n, _d in c.rows] == [fc.FAIL]
    assert "PUBLIC repo owner/pub-repo" in c.rows[0][2]


def test_data_dir_inside_a_private_repo_passes_and_names_it(tmp_path, monkeypatch):
    """A PASS must be legible as "examined and approved", not indistinguishable from a skip."""
    root = tmp_path / "code"
    root.mkdir()
    make_repo(root, "tidy", datadir=True)
    comp = _companion(tmp_path, "priv-repo", "git@github.com:Owner/priv-repo.git")
    monkeypatch.setenv("TIDY_DATA_DIR", str(comp / "data"))

    vis = _vis_map(tmp_path, {"owner/priv-repo": "PRIVATE"})
    c = fc.check_data_boundary(vis, repos={"tidy": str(root / "tidy")}, offline=True)
    assert [s for s, _n, _d in c.rows] == [fc.PASS]
    detail = c.rows[0][2]
    assert "owner/priv-repo" in detail and "PRIVATE" in detail


def test_data_dir_in_repo_of_unknown_visibility_fails_closed(tmp_path, monkeypatch):
    """Same rule the PII gate uses: an unanswerable question is gated, never waved through."""
    root = tmp_path / "code"
    root.mkdir()
    make_repo(root, "murky", datadir=True)
    comp = _companion(tmp_path, "who-knows", "git@github.com:Owner/who-knows.git")
    monkeypatch.setenv("MURKY_DATA_DIR", str(comp / "data"))

    vis = _vis_map(tmp_path, {})               # empty map, offline: nothing can answer
    c = fc.check_data_boundary(vis, repos={"murky": str(root / "murky")}, offline=True)
    assert [s for s, _n, _d in c.rows] == [fc.FAIL]
    assert "failing closed" in c.rows[0][2]


def test_data_dir_in_repo_with_no_origin_fails_closed(tmp_path, monkeypatch):
    """No remote is not "safe by default": it is a repo whose destination nobody has stated."""
    root = tmp_path / "code"
    root.mkdir()
    make_repo(root, "orphan", datadir=True)
    comp = _companion(tmp_path, "no-origin", None)
    monkeypatch.setenv("ORPHAN_DATA_DIR", str(comp / "data"))

    c = fc.check_data_boundary(_vis_map(tmp_path, {}),
                               repos={"orphan": str(root / "orphan")}, offline=True)
    assert [s for s, _n, _d in c.rows] == [fc.FAIL]


def test_data_dir_outside_git_passes(tmp_path, monkeypatch):
    """A plain directory clears the check, and the row says out loud that it is unversioned."""
    root = tmp_path / "code"
    root.mkdir()
    make_repo(root, "clean", datadir=True)
    store = tmp_path / "private-store"
    store.mkdir()
    monkeypatch.setenv("CLEAN_DATA_DIR", str(store))

    c = fc.check_data_boundary(_vis_map(tmp_path, {}),
                               repos={"clean": str(root / "clean")}, offline=True)
    assert [s for s, _n, _d in c.rows] == [fc.PASS]
    assert "unversioned" in c.rows[0][2]


def test_resolver_refusal_is_a_failure_not_an_unknown(tmp_path, monkeypatch):
    """datadir.py refuses a data dir inside its OWN repo. That is a finding, not a blind spot.

    Filing a caught violation under "could not observe" is the exact rounding that lets a red fleet
    print a clean sheet, so the refusal has to survive the trip through the driver as a FAIL.
    """
    root = tmp_path / "code"
    root.mkdir()
    d = make_repo(root, "selfref")
    (d / "tools").mkdir(exist_ok=True)
    (d / "tools" / "datadir.py").write_text(
        "class DataDirInsideOwnRepo(RuntimeError):\n    pass\n"
        "def resolve_data_dir(skill, create=False):\n"
        "    raise DataDirInsideOwnRepo('data dir is INSIDE its own repo')\n", encoding="utf-8")

    c = fc.check_data_boundary(_vis_map(tmp_path, {}),
                               repos={"selfref": str(d)}, offline=True)
    assert [s for s, _n, _d in c.rows] == [fc.FAIL]
    assert "INSIDE its own repo" in c.rows[0][2]


def test_uninitialized_data_dir_skips(tmp_path, monkeypatch):
    """An uninitialized tool is the CORRECT shipping state, so this must never be a failure."""
    root = tmp_path / "code"
    root.mkdir()
    make_repo(root, "fresh", datadir=True)
    monkeypatch.delenv("FRESH_DATA_DIR", raising=False)

    c = fc.check_data_boundary(_vis_map(tmp_path, {}),
                               repos={"fresh": str(root / "fresh")}, offline=True)
    assert [s for s, _n, _d in c.rows] == [fc.SKIP]
    assert c.count(fc.FAIL) == 0


def test_repo_without_datadir_is_not_reported(tmp_path):
    root = tmp_path / "code"
    root.mkdir()
    make_repo(root, "plain")
    assert fc.check_data_boundary(_vis_map(tmp_path, {}),
                                  repos={"plain": str(root / "plain")}, offline=True).rows == []


def test_data_boundary_is_unknown_when_git_cannot_run(tmp_path, monkeypatch):
    """The fail-open: `git -C` failing for ANY reason used to read as "outside a worktree".

    With no git on PATH every data dir on the machine was cleared by a probe that never ran. Force
    the failure condition and require that the row is not a PASS.
    """
    root = tmp_path / "code"
    root.mkdir()
    make_repo(root, "clean", datadir=True)
    store = tmp_path / "private-store"
    store.mkdir()
    monkeypatch.setenv("CLEAN_DATA_DIR", str(store))
    monkeypatch.setattr(fc, "run", lambda *_a, **_k: (None, "", "git: command not found"))

    c = fc.check_data_boundary(_vis_map(tmp_path, {}),
                               repos={"clean": str(root / "clean")}, offline=True)
    assert [s for s, _n, _d in c.rows] == [fc.UNKNOWN]
    assert c.count(fc.PASS) == 0


def test_visibility_map_is_never_written_back(tmp_path, monkeypatch):
    """Read-only contract. A checker that mutates the map to answer its own question is a checker
    whose second run tests something different from its first."""
    root = tmp_path / "code"
    root.mkdir()
    make_repo(root, "tidy", datadir=True)
    comp = _companion(tmp_path, "priv-repo", "git@github.com:Owner/priv-repo.git")
    monkeypatch.setenv("TIDY_DATA_DIR", str(comp / "data"))
    vis = _vis_map(tmp_path, {"owner/priv-repo": "PRIVATE"})
    before = open(vis, encoding="utf-8").read()

    fc.check_data_boundary(vis, repos={"tidy": str(root / "tidy")}, offline=True)
    assert open(vis, encoding="utf-8").read() == before


# --- the visibility oracle: a cache must not be able to outvote GitHub ---------------------------
#
# THE HOLE THIS BLOCK CLOSES (2026-07-31)
# ---------------------------------------
# The oracle read the map FIRST and asked gh only on a miss, so one stale line of JSON silently
# defeated the entire data-boundary control. A copy of the real map poisoned with
# {"daizedong/skill-smith": "PRIVATE"} -- a genuinely PUBLIC repo -- produced
# `PASS ... [PRIVATE per visibility map]` over a data dir inside a public repo. Nothing on this
# machine rewrites that file on its own, so the entry would have said PRIVATE forever, and a repo
# flipped from private to public on GitHub is exactly the event the control exists to survive.
#
# The property pinned below: a map entry cannot indefinitely outvote reality. Online it never gets
# to vote at all; offline its vote expires and an expired entry behaves like UNKNOWN, which already
# fails closed.
def _oracle(tmp_path, mapping, stamp="now", **kw):
    return fc.VisibilityOracle(_vis_map(tmp_path, mapping, stamp=stamp), **kw)


def _gh_says(monkeypatch, answer):
    """Pretend gh is installed and reports `answer` for any repo."""
    monkeypatch.setattr(fc.shutil, "which", lambda _n: "gh")
    monkeypatch.setattr(fc, "run", lambda *_a, **_k: (0, answer + "\n", ""))


def test_live_gh_overrules_a_map_entry_that_disagrees(tmp_path, monkeypatch):
    """The poisoning demonstration, as a unit: the map says PRIVATE, GitHub says PUBLIC."""
    _gh_says(monkeypatch, "PUBLIC")
    o = _oracle(tmp_path, {"owner/repo": "PRIVATE"})
    vis, why = o.visibility("owner/repo")
    assert vis == "PUBLIC"
    assert "STALE" in why


def test_live_gh_is_asked_even_when_the_map_has_an_entry(tmp_path, monkeypatch):
    """Map-first was the bug. A cache hit must not short-circuit the question."""
    calls = []
    monkeypatch.setattr(fc.shutil, "which", lambda _n: "gh")

    def spy(args, **_k):
        calls.append(args)
        return 0, "PUBLIC\n", ""

    monkeypatch.setattr(fc, "run", spy)
    _oracle(tmp_path, {"owner/repo": "PRIVATE"}).visibility("owner/repo")
    assert any("repo" in a and "view" in a for a in calls)


def test_gh_answer_is_asked_once_per_slug(tmp_path, monkeypatch):
    """The cost of asking live is bounded: one query per DISTINCT slug per run."""
    calls = []
    monkeypatch.setattr(fc.shutil, "which", lambda _n: "gh")

    def spy(args, **_k):
        calls.append(args)
        return 0, "PRIVATE\n", ""

    monkeypatch.setattr(fc, "run", spy)
    o = _oracle(tmp_path, {})
    for _ in range(5):
        assert o.visibility("owner/repo")[0] == "PRIVATE"
    assert len(calls) == 1


def test_map_may_answer_only_when_gh_cannot(tmp_path, monkeypatch):
    """Offline, a FRESH map is the best evidence available and is allowed to vote."""
    monkeypatch.setattr(fc.shutil, "which", lambda _n: None)
    vis, why = _oracle(tmp_path, {"owner/repo": "PRIVATE"}).visibility("owner/repo")
    assert vis == "PRIVATE"
    assert "visibility map" in why and "gh is not on PATH" in why


def test_a_map_too_old_to_trust_is_unknown(tmp_path, monkeypatch):
    """An entry that can never expire is an entry that outvotes reality forever."""
    monkeypatch.setattr(fc.shutil, "which", lambda _n: None)
    old = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    vis, why = _oracle(tmp_path, {"owner/repo": "PRIVATE"}, stamp=old).visibility("owner/repo")
    assert vis == "UNKNOWN"
    assert "trust window" in why


def test_an_unstamped_map_is_of_unknown_age_and_is_not_trusted(tmp_path, monkeypatch):
    """The map as it existed before this fix: no way to tell an hour old from a year old."""
    monkeypatch.setattr(fc.shutil, "which", lambda _n: None)
    vis, why = _oracle(tmp_path, {"owner/repo": "PRIVATE"}, stamp=None).visibility("owner/repo")
    assert vis == "UNKNOWN"
    assert "no %s stamp" % fc.VisibilityOracle.STAMP_KEY in why


def test_a_stamp_in_the_future_is_not_trusted(tmp_path, monkeypatch):
    monkeypatch.setattr(fc.shutil, "which", lambda _n: None)
    ahead = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    vis, _why = _oracle(tmp_path, {"owner/repo": "PRIVATE"}, stamp=ahead).visibility("owner/repo")
    assert vis == "UNKNOWN"


def test_the_stamp_is_not_mistaken_for_a_repo(tmp_path, monkeypatch):
    """The reserved key must never leak into the answers as if it were a slug."""
    monkeypatch.setattr(fc.shutil, "which", lambda _n: None)
    o = _oracle(tmp_path, {"owner/repo": "PUBLIC"})
    assert fc.VisibilityOracle.STAMP_KEY not in o.map
    assert o.visibility(fc.VisibilityOracle.STAMP_KEY)[0] == "UNKNOWN"


def test_expired_map_fails_the_data_boundary_check_closed(tmp_path, monkeypatch):
    """End to end: a stale PRIVATE marking stops clearing a data dir, it does not keep clearing it."""
    root = tmp_path / "code"
    root.mkdir()
    make_repo(root, "tidy", datadir=True)
    comp = _companion(tmp_path, "priv-repo", "git@github.com:Owner/priv-repo.git")
    monkeypatch.setenv("TIDY_DATA_DIR", str(comp / "data"))
    old = (datetime.now(timezone.utc) - timedelta(days=99)).strftime("%Y-%m-%dT%H:%M:%SZ")
    vis = _vis_map(tmp_path, {"owner/priv-repo": "PRIVATE"}, stamp=old)

    c = fc.check_data_boundary(vis, repos={"tidy": str(root / "tidy")}, offline=True)
    assert [s for s, _n, _d in c.rows] == [fc.FAIL]
    assert "failing closed" in c.rows[0][2]


def test_parse_stamp_and_age():
    assert fc.parse_stamp("") is None
    assert fc.parse_stamp("not a date") is None
    assert fc.parse_stamp("2026-07-31T00:00:00Z") == fc.parse_stamp("2026-07-31T00:00:00+00:00")
    # naive timestamps are read as UTC rather than as local time, which would shift the age
    assert fc.parse_stamp("2026-07-31T00:00:00") == fc.parse_stamp("2026-07-31T00:00:00Z")


def test_in_git_worktree_tristate(tmp_path, monkeypatch):
    outside = tmp_path / "plain"
    outside.mkdir()
    assert fc.in_git_worktree(str(outside))[0] is False
    inside = tmp_path / "repo"
    inside.mkdir()
    assert git("init", "-q", cwd=inside).returncode == 0
    assert fc.in_git_worktree(str(inside))[0] is True
    monkeypatch.setattr(fc, "run", lambda *_a, **_k: (None, "", "no git"))
    assert fc.in_git_worktree(str(outside))[0] is None


def test_data_boundary_nonexistent_resolved_dir_is_unknown(tmp_path, monkeypatch):
    """`git -C <missing>` exits nonzero, which the probe would otherwise read as a clean pass."""
    root = tmp_path / "code"
    root.mkdir()
    d = make_repo(root, "drifted")
    (d / "tools").mkdir(exist_ok=True)
    ghost = tmp_path / "ghost-dir"
    (d / "tools" / "datadir.py").write_text(
        "from pathlib import Path\n"
        "def resolve_data_dir(skill, create=False):\n"
        "    return Path(r'%s')\n" % str(ghost), encoding="utf-8")

    c = fc.check_data_boundary(_vis_map(tmp_path, {}),
                               repos={"drifted": str(d)}, offline=True)
    assert [s for s, _n, _d in c.rows] == [fc.UNKNOWN]


# --- check 5: the CI probe covers EVERY guard, and degrades without blocking ---------------------
def _ci_with_gh(monkeypatch, rc, stdout, stderr="", targets=None, default="main"):
    """gh that answers the default-branch probe, then `rc/stdout/stderr` for the run query."""
    monkeypatch.setattr(fc.shutil, "which", lambda _n: "gh")

    def fake(args, **_k):
        if "api" in args:
            return (0, default + "\n", "") if default else (1, "", "no such repo")
        return rc, stdout, stderr

    monkeypatch.setattr(fc, "run", fake)
    return fc.check_ci(targets or [("owner/repo", ["pii-guard.yml"], "", "PUBLIC")], 5)


def _runs(conclusion, status="completed", branch="main"):
    return json.dumps([{"conclusion": conclusion, "status": status,
                        "createdAt": "2026-01-01T00:00:00Z", "headBranch": branch}])


def test_ci_success_passes(monkeypatch):
    c = _ci_with_gh(monkeypatch, 0, _runs("success"))
    assert [s for s, _n, _d in c.rows] == [fc.PASS]


def test_ci_failure_fails(monkeypatch):
    c = _ci_with_gh(monkeypatch, 0, _runs("failure"))
    assert [s for s, _n, _d in c.rows] == [fc.FAIL]


def test_ci_checks_every_guard_and_names_each_one(monkeypatch):
    """The promotion-assistant regression: green pii-guard, red dash-guard, one confident PASS.

    Both workflows must get their own row, and the red one must fail the run.
    """
    monkeypatch.setattr(fc.shutil, "which", lambda _n: "gh")

    def fake_run(args, **_k):
        if "api" in args:
            return 0, "main\n", ""
        wf = args[args.index("-w") + 1]
        return 0, _runs("success" if wf == "pii-guard.yml" else "failure"), ""

    monkeypatch.setattr(fc, "run", fake_run)
    c = fc.check_ci([("owner/repo", ["pii-guard.yml", "dash-guard.yml"], "", "PUBLIC")], 5)
    got = {n: s for s, n, _d in c.rows}
    assert got == {"owner/repo [guard:pii-guard.yml]": fc.PASS,
                   "owner/repo [guard:dash-guard.yml]": fc.FAIL}


# --- the CI probe must judge the DEFAULT BRANCH, not whatever ref ran last -----------------------
#
# WHY (2026-07-31): the query was `gh run list -w <wf> --limit 1`, the newest run on ANY ref. Two of
# 34 green rows on 2026-07-31 were runs from the topic branch feat/login-handoff-and-depth-gate on
# shopping-aggregator, printed as if they described main. The same shape had teeth on 2026-07-22,
# when daily-hotspots had a GREEN pii-guard run on feat/source-coverage-selfevolve while master's own
# newest pii-guard run was a FAILURE: this check would have said PASS over a red default branch.
def test_ci_asks_only_about_the_default_branch(monkeypatch):
    seen = {}
    monkeypatch.setattr(fc.shutil, "which", lambda _n: "gh")

    def fake_run(args, **_k):
        if "api" in args:
            return 0, "master\n", ""
        seen["args"] = args
        return 0, _runs("success", branch="master"), ""

    monkeypatch.setattr(fc, "run", fake_run)
    fc.check_ci([("owner/repo", ["pii-guard.yml"], "", "PUBLIC")], 5)
    a = seen["args"]
    assert "-b" in a and a[a.index("-b") + 1] == "master"


def test_ci_does_not_report_a_topic_branch_run_as_the_default_branch(monkeypatch):
    """The exact 2026-07-22 shape: topic branch green, default branch red."""
    monkeypatch.setattr(fc.shutil, "which", lambda _n: "gh")

    def fake_run(args, **_k):
        if "api" in args:
            return 0, "master\n", ""
        on_default = "-b" in args and args[args.index("-b") + 1] == "master"
        if on_default:
            return 0, _runs("failure", branch="master"), ""
        return 0, _runs("success", branch="feat/topic"), ""

    monkeypatch.setattr(fc, "run", fake_run)
    c = fc.check_ci([("owner/repo", ["pii-guard.yml"], "", "PUBLIC")], 5)
    assert [s for s, _n, _d in c.rows] == [fc.FAIL]
    assert "master" in c.rows[0][2]


def test_ci_no_run_on_the_default_branch_is_unknown_not_a_topic_branch_run(monkeypatch):
    """A workflow that has only ever fired on topic branches has said nothing about main yet."""
    monkeypatch.setattr(fc.shutil, "which", lambda _n: "gh")

    def fake_run(args, **_k):
        if "api" in args:
            return 0, "main\n", ""
        if "-b" in args:
            return 0, "[]", ""
        return 0, _runs("success", branch="feat/topic"), ""

    monkeypatch.setattr(fc, "run", fake_run)
    c = fc.check_ci([("owner/repo", ["pii-guard.yml"], "", "PUBLIC")], 5)
    assert [s for s, _n, _d in c.rows] == [fc.UNKNOWN]
    assert "default branch main" in c.rows[0][2]


def test_ci_without_a_default_branch_is_unknown_never_a_fallback(monkeypatch):
    """No default branch means no question to ask; answering from another ref is the bug."""
    c = _ci_with_gh(monkeypatch, 0, _runs("success", branch="feat/topic"), default="")
    assert [s for s, _n, _d in c.rows] == [fc.UNKNOWN]
    assert "default branch" in c.rows[0][2]


def test_ci_default_branch_is_looked_up_once_per_repo(monkeypatch):
    """One extra gh call per REPO, not per workflow."""
    api_calls = []
    monkeypatch.setattr(fc.shutil, "which", lambda _n: "gh")

    def fake_run(args, **_k):
        if "api" in args:
            api_calls.append(args)
            return 0, "main\n", ""
        return 0, _runs("success"), ""

    monkeypatch.setattr(fc, "run", fake_run)
    fc.check_ci([("owner/repo", ["pii-guard.yml", "dash-guard.yml"], "", "PUBLIC")], 5)
    assert len(api_calls) == 1


def test_ci_row_names_the_branch_it_judged(monkeypatch):
    """A green row must say which ref the evidence came from, or it is the old lie again."""
    c = _ci_with_gh(monkeypatch, 0, _runs("success", branch="main"))
    assert "main" in c.rows[0][2]


@pytest.mark.parametrize("rc,out,err", [
    (1, "", "gh: not authenticated"),          # unauthenticated
    (1, "", "API rate limit exceeded"),        # rate limited
    (0, "[]", ""),                             # no run history (GitHub expires it)
    (0, "not json", ""),                       # garbage
])
def test_ci_unobservable_is_unknown_never_fail(monkeypatch, rc, out, err):
    c = _ci_with_gh(monkeypatch, rc, out, err)
    assert c.count(fc.FAIL) == 0
    assert c.count(fc.UNKNOWN) == 1


def test_ci_in_progress_is_unknown(monkeypatch):
    c = _ci_with_gh(monkeypatch, 0, _runs(None, status="in_progress"))
    assert [s for s, _n, _d in c.rows] == [fc.UNKNOWN]


def test_ci_without_gh_is_unknown(monkeypatch):
    monkeypatch.setattr(fc.shutil, "which", lambda _n: None)
    c = fc.check_ci([("owner/repo", ["pii-guard.yml"], "", "PUBLIC")], 5)
    assert c.count(fc.FAIL) == 0
    assert c.count(fc.UNKNOWN) == 1


def test_ci_with_no_targets_says_so_instead_of_printing_nothing(monkeypatch):
    """Zero rows renders as "pass 0, fail 0", which reads like a clean fleet."""
    monkeypatch.setattr(fc.shutil, "which", lambda _n: "gh")
    c = fc.check_ci([], 5)
    assert c.count(fc.UNKNOWN) == 1


# --- the CI probe reads EVERY workflow, not a hardcoded pair of names ----------------------------
#
# WHY (2026-07-31): check_ci interrogated GUARD_WORKFLOWS only, so a repo's own gate workflow was
# invisible to the fleet report. That is how "34 of 34 green" was printed on a day when a real gate
# workflow was concluding success over a log reading "RESULT: BLOCK (3 blocking issue(s))". The
# workflow was not red at the time, but nothing in the report could ever have said so if it were.
def test_ci_reads_a_non_guard_workflow_at_all(monkeypatch):
    c = _ci_with_gh(monkeypatch, 0, _runs("success"),
                    targets=[("owner/repo", ["gate.yml"], "", "PUBLIC")])
    assert [n for _s, n, _d in c.rows] == ["owner/repo [other:gate.yml]"]


def test_ci_red_non_guard_workflow_fails_the_row(monkeypatch):
    """A red workflow we authored is a failure whoever wrote it. See CI_WARN_ONLY's note."""
    c = _ci_with_gh(monkeypatch, 0, _runs("failure"),
                    targets=[("owner/repo", ["gate.yml"], "", "PUBLIC")])
    assert [s for s, _n, _d in c.rows] == [fc.FAIL]


def test_ci_rows_are_tagged_by_tier_so_a_reader_can_tell_them_apart(monkeypatch):
    c = _ci_with_gh(monkeypatch, 0, _runs("success"),
                    targets=[("owner/repo", ["gate.yml", "pii-guard.yml"], "", "PUBLIC")])
    assert {n for _s, n, _d in c.rows} == {"owner/repo [other:gate.yml]",
                                           "owner/repo [guard:pii-guard.yml]"}


def test_ci_warn_only_downgrades_exactly_one_named_workflow_and_prints_the_reason(monkeypatch):
    monkeypatch.setitem(fc.CI_WARN_ONLY, ("owner/repo", "gate.yml"), "upstream API is flaky")
    c = _ci_with_gh(monkeypatch, 0, _runs("failure"),
                    targets=[("owner/repo", ["gate.yml", "pii-guard.yml"], "", "PUBLIC")])
    got = {n: (s, d) for s, n, d in c.rows}
    assert got["owner/repo [other:gate.yml]"][0] == fc.WARN
    assert "upstream API is flaky" in got["owner/repo [other:gate.yml]"][1]
    # the exemption is per workflow, never per tier: the guard beside it still fails
    assert got["owner/repo [guard:pii-guard.yml]"][0] == fc.FAIL


def test_ci_unobserved_listing_is_unknown_and_still_names_the_repo(monkeypatch):
    """A repo whose workflow listing could not be read must not just vanish from the report."""
    c = _ci_with_gh(monkeypatch, 0, _runs("success"),
                    targets=[("owner/repo", None, "gh could not reach it", "PUBLIC")])
    assert [s for s, _n, _d in c.rows] == [fc.UNKNOWN]
    assert "gh could not reach it" in c.rows[0][2]


def test_ci_public_repo_with_no_workflows_at_all_is_warned_not_silent(monkeypatch):
    c = _ci_with_gh(monkeypatch, 0, _runs("success"),
                    targets=[("owner/repo", [], "", "PUBLIC")])
    assert [s for s, _n, _d in c.rows] == [fc.WARN]


def test_ci_private_companion_repo_with_no_workflows_is_a_named_skip(monkeypatch):
    """CI is not mandated on a private data repo, but the row still names it."""
    c = _ci_with_gh(monkeypatch, 0, _runs("success"),
                    targets=[("owner/repo-config", [], "", "PRIVATE")])
    assert [(s, n) for s, n, _d in c.rows] == [(fc.SKIP, "owner/repo-config")]


def test_workflow_tier_classifies_by_name_and_never_filters():
    assert fc.workflow_tier("pii-guard.yml") == "guard"
    assert fc.workflow_tier("DASH-Guard.YAML") == "guard"      # case and extension agnostic
    assert fc.workflow_tier("gate.yml") == "other"
    assert fc.workflow_tier("heartbeat.yml") == "other"


# --- ci_targets: PRIVATE repos are interrogated too ----------------------------------------------
def test_ci_targets_includes_private_repos_check_workflow_never_walked(tmp_path, monkeypatch):
    """check_workflow only walks PUBLIC entries; a private repo's red CI is just as broken."""
    wf = fc.Check("workflow", "t")
    wf.all_remote_workflows = {"owner/public-repo": ["pii-guard.yml"]}
    vis = _vis_map(tmp_path, {"owner/public-repo": "PUBLIC", "owner/private-repo": "PRIVATE"})
    monkeypatch.setattr(fc, "remote_workflow_files",
                        lambda *_a, **_k: (["memory-health.yml"], ""))
    got = {slug: (names, visibility)
           for slug, names, _why, visibility in fc.ci_targets(wf, vis, {"owner/private-repo": "p"}, 5)}
    assert got["owner/private-repo"] == (["memory-health.yml"], "PRIVATE")
    assert got["owner/public-repo"] == (["pii-guard.yml"], "PUBLIC")


def test_ci_targets_reuses_the_public_listings_without_refetching(tmp_path, monkeypatch):
    """The public repos were already listed by check_workflow; asking twice doubles the API cost."""
    calls = []
    wf = fc.Check("workflow", "t")
    wf.all_remote_workflows = {"owner/public-repo": ["pii-guard.yml"]}
    vis = _vis_map(tmp_path, {"owner/public-repo": "PUBLIC"})
    monkeypatch.setattr(fc, "remote_workflow_files",
                        lambda *a, **k: (calls.append(a), ([], ""))[1])
    fc.ci_targets(wf, vis, {"owner/public-repo": "p"}, 5)
    assert calls == []


# --- checks must not report a clean sheet by looking at nothing -----------------------------------
def test_junctions_missing_dir_is_unknown_not_silent(tmp_path):
    c = fc.check_junctions(str(tmp_path / "nope"))
    assert c.count(fc.UNKNOWN) == 1 and c.rows


def test_junctions_empty_dir_is_unknown_not_silent(tmp_path):
    d = tmp_path / "skills"
    d.mkdir()
    (d / "plain-copy").mkdir()
    c = fc.check_junctions(str(d))
    assert c.count(fc.UNKNOWN) == 1


def test_conformance_reports_repos_it_skipped(tmp_path):
    """A deleted plugin.json must show up as lost coverage, not as one fewer line."""
    root = tmp_path / "code"
    root.mkdir()
    make_repo(root, "not-a-plugin")
    c = fc.check_conformance({"not-a-plugin": str(root / "not-a-plugin")}, 30)
    assert [s for s, _n, _d in c.rows] == [fc.SKIP]


def test_conformance_exit_zero_with_warnings_is_not_a_pass(tmp_path, monkeypatch):
    """A linter that exits 0 having printed warnings has not reported a clean repo.

    Rolling that up into PASS is precisely how a green total was produced over a fleet in which
    every defect of the next day's audit was already present.
    """
    root = tmp_path / "code"
    root.mkdir()
    d = make_repo(root, "warny", plugin=True)
    out = ("  [PASS] file: README.md\n"
           "  [WARN] SKILL.md size (17000 chars): skills/x/SKILL.md  -> over the line\n"
           "  36/37 passed  (1 WARN)\n")
    monkeypatch.setattr(fc, "run", lambda *_a, **_k: (0, out, ""))
    c = fc.check_conformance({"warny": str(d)}, 30)
    assert [s for s, _n, _d in c.rows] == [fc.WARN], c.rows
    assert "1 WARN" in c.rows[0][2] and "SKILL.md size" in c.rows[0][2]


# --- the library budget check --------------------------------------------------------------------
def budget_digest(state, **kw):
    """A minimal budget_check stdout carrying only the digest line, which is the whole interface."""
    f = {"total": 1000, "capacity": 21565, "overflow": 0, "trim_headroom": 0, "min_lost": 0,
         "cap_over_ours": 0, "plugins": 0, "lever": "n/a", "fp": "aaaaaaaa"}
    f.update(kw)
    return ("  STATUS: %s\n  BUDGET: %s %s\n"
            % (state, state, " ".join("%s=%s" % kv for kv in f.items())))


@pytest.mark.parametrize("rc,want", [(0, "PASS"), (1, "FAIL"), (2, "UNKNOWN"), (None, "UNKNOWN")])
def test_budget_maps_the_tools_exit_code(monkeypatch, rc, want):
    monkeypatch.setattr(fc, "run", lambda *_a, **_k: (rc, budget_digest("OK"), "boom"))
    c = fc.check_budget("skills", "code", 30)
    assert c.rows[0][0] == want, c.rows


def test_budget_blocked_is_amber_and_names_the_remedy(monkeypatch):
    """The centre of the redesign, asserted at the caller.

    A real overflow that no edit can close must be WARN, so the fleet verdict is not RED forever
    for a condition nobody can act on. It must ALSO carry the numbers and point at the ranking,
    because an amber row that just says "blocked" is the same dead signal one shade lighter.
    """
    out = budget_digest("BLOCKED", overflow=32256, min_lost=83, trim_headroom=6774,
                        plugins=7, lever="decision", fp="70719bc7")
    monkeypatch.setattr(fc, "run", lambda *_a, **_k: (3, out, ""))
    c = fc.check_budget("skills", "code", 30)
    assert c.rows[0][0] == fc.WARN, c.rows
    detail = c.rows[0][2]
    assert "32256 chars over capacity" in detail, detail
    assert ">=83 skill(s) have no description in the prompt" in detail, detail
    assert "--plugins" in detail, detail
    assert "fp=70719bc7" in detail, detail


def test_budget_trimmable_overflow_stays_red(monkeypatch):
    """The other half of the split. Amber must not absorb work the operator could do tonight."""
    out = budget_digest("FAIL", overflow=800, min_lost=2, trim_headroom=6000, lever="trim",
                        fp="deadbeef")
    monkeypatch.setattr(fc, "run", lambda *_a, **_k: (1, out, ""))
    c = fc.check_budget("skills", "code", 30)
    assert c.rows[0][0] == fc.FAIL, c.rows
    assert "lever=trim" in c.rows[0][2], c.rows[0][2]


def test_budget_pass_with_an_overflow_is_a_warning(monkeypatch):
    """A tool exiting 0 while its own digest reports an overflow has drifted from its caller.

    A caller that trusts an exit code over the report it just read is how the last clean sheet was
    produced over a fleet with four unreported defects.
    """
    out = budget_digest("OK", overflow=900, min_lost=1)
    monkeypatch.setattr(fc, "run", lambda *_a, **_k: (0, out, ""))
    c = fc.check_budget("skills", "code", 30)
    assert c.rows[0][0] == fc.WARN, c.rows


def test_budget_reports_no_loss_count_when_the_library_fits(monkeypatch):
    monkeypatch.setattr(fc, "run", lambda *_a, **_k: (0, budget_digest("OK"), ""))
    c = fc.check_budget("skills", "code", 30)
    assert c.rows[0][0] == fc.PASS, c.rows
    assert "over capacity" not in c.rows[0][2], c.rows[0][2]


def test_budget_without_a_digest_is_unknown_not_pass(monkeypatch):
    """Fail closed on an unreadable report.

    Regression: the caller defaulted the count to 0 when it could not find the machine-readable
    line, so a budget_check whose output format had drifted, or which printed nothing at all while
    exiting 0, produced a clean green row over an unmeasured library.
    """
    monkeypatch.setattr(fc, "run", lambda *_a, **_k: (0, "some prose and no digest at all\n", ""))
    c = fc.check_budget("skills", "code", 30)
    assert c.rows[0][0] == fc.UNKNOWN, c.rows
    assert "no BUDGET: digest line" in c.rows[0][2], c.rows[0][2]


def test_budget_state_and_exit_code_disagreeing_lands_on_the_blocked_arm(monkeypatch):
    """rc and the printed state are OR-ed, so a drift between them cannot escape the amber arm.

    Asserting only the colour is not enough here: an rc==0 BLOCKED run would come out WARN anyway
    via the overflow cross-check, and the test would pass with the OR removed. What must hold is
    that it is recognised AS blocked, and therefore carries the remedy text an operator needs, so
    the assertion is on the detail and not just the colour.
    """
    out = budget_digest("BLOCKED", overflow=500, min_lost=1, lever="decision")
    monkeypatch.setattr(fc, "run", lambda *_a, **_k: (0, out, ""))
    c = fc.check_budget("skills", "code", 30)
    assert c.rows[0][0] == fc.WARN, c.rows
    assert "BLOCKED, no lever" in c.rows[0][2], \
        "a BLOCKED report with a drifting exit code was not recognised as blocked:\n%s" \
        % c.rows[0][2]


def test_budget_missing_tool_is_unknown_not_pass(monkeypatch):
    monkeypatch.setattr(fc.os.path, "isfile", lambda _p: False)
    c = fc.check_budget("skills", "code", 30)
    assert c.rows[0][0] == fc.UNKNOWN


# --- the output contract -------------------------------------------------------------------------
def test_status_json_shape_and_timestamp(tmp_path):
    c = fc.Check("demo", "demo check")
    c.add(fc.PASS, "a")
    c.add(fc.FAIL, "b", "because")
    c.add(fc.WARN, "c", "not clean, not blocking")
    c.add(fc.SKIP, "d", "not looked at")
    tot = {"pass": 1, "fail": 1, "warn": 1, "skip": 1, "unknown": 0}
    out = tmp_path / "nested" / "status.json"
    fc.write_status(str(out), [c], tot, "2026-01-01T00:00:00Z", 1.5, 1)

    got = json.loads(out.read_text(encoding="utf-8"))
    assert got["utc"] == "2026-01-01T00:00:00Z"     # freshness is the caller's whole mechanism
    assert got["exit"] == 1
    assert got["totals"] == tot
    assert got["checks"]["demo"]["fail"] == 1
    assert got["failures"] == ["demo: b -- because"]
    assert got["warnings"] == ["demo: c -- not clean, not blocking"]
    # The caller is meant to QUOTE this, not compose its own adjective out of the counts. That is
    # how "all green" got printed over a run with 82 unevaluated rows.
    assert got["verdict"] == "RED"
    assert "coverage 75% (3 of 4 rows)" in got["digest"], got["digest"]
    assert got["coverage"] == {"evaluated": 3, "not_evaluated": 1}
    assert not list(tmp_path.glob("**/*.tmp"))       # written atomically, no debris


def test_digest_never_calls_a_skipped_run_green():
    """A skip must be distinguishable from a pass in the one line a human reads."""
    line, verdict = fc.digest_line({"pass": 86, "fail": 0, "warn": 0, "skip": 82, "unknown": 0})
    assert verdict == "GREEN"
    assert "NOT EVALUATED 82" in line and "coverage 51%" in line, line
    line, verdict = fc.digest_line({"pass": 5, "fail": 0, "warn": 2, "skip": 0, "unknown": 0})
    assert verdict == "AMBER", "warnings must not read as a clean sheet: %s" % line
    line, verdict = fc.digest_line({"pass": 5, "fail": 1, "warn": 0, "skip": 0, "unknown": 0})
    assert verdict == "RED"


def test_no_status_flag_writes_nothing(tmp_path, capsys):
    rc = fc.main(["--skills-dir", str(tmp_path / "none"), "--code-root", str(tmp_path / "none"),
                  "--visibility", str(tmp_path / "none.json"), "--offline", "--no-status"])
    capsys.readouterr()
    assert rc == 0
    assert list(tmp_path.iterdir()) == []


def test_exit_code_is_driven_by_fail_not_by_unknown(tmp_path, capsys, monkeypatch):
    """UNKNOWN must never flip the exit code; that is what keeps the CI probe non-blocking."""
    monkeypatch.setattr(fc.shutil, "which", lambda _n: None)   # forces the ci check to UNKNOWN
    status = tmp_path / "s.json"
    rc = fc.main(["--skills-dir", str(tmp_path / "none"), "--code-root", str(tmp_path / "none"),
                  "--visibility", str(tmp_path / "none.json"), "--status-json", str(status)])
    capsys.readouterr()
    assert rc == 0
    assert json.loads(status.read_text(encoding="utf-8"))["totals"]["unknown"] >= 1


def test_report_rolls_up_repeated_skips(capsys):
    rows = [(fc.SKIP, "r%d" % i, "no local clone") for i in range(20)]
    rows.append((fc.FAIL, "real", "this one matters"))
    fc.print_rows(rows)
    out = capsys.readouterr().out
    assert "(20) no local clone" in out
    assert "real" in out and "this one matters" in out
    # 20 identical lines would bury the one that matters
    assert out.count("no local clone") == 1


def test_there_is_no_fix_flag():
    """Not a style preference. Three of the dirs this inspects have no companion repo on disk and
    two hold live secrets and uncommitted state; auto-converging them would destroy data."""
    src = open(FLEET, encoding="utf-8").read()
    assert '"--fix"' not in src and "'--fix'" not in src
    p = subprocess.run([sys.executable, FLEET, "--fix"], capture_output=True, text=True, timeout=60)
    assert p.returncode != 0
    assert "unrecognized arguments" in (p.stderr or "")


# --- concurrency: the answers must still be the answers ------------------------------------------
# These exist because the remote queries were moved onto a thread pool for wall clock, and a report
# that is fast and wrong is strictly worse than one that is slow and right. Every test above stubs
# gh to return the SAME answer to every call, so none of them can see a result being attached to the
# wrong row -- which is the one new way this refactor could fail: results now come back out of order
# and are matched to rows through a (slug, workflow) key instead of being consumed in place.

def test_ci_each_row_gets_its_own_run_result_not_a_neighbours(monkeypatch):
    """Distinct answer per (repo, workflow); every row must carry ITS OWN.

    Cross-talk is invisible to a uniform stub: if the fan-out mismatched results to rows, a fleet
    where one workflow is red would print the red on some other workflow, or lose it entirely, and
    every existing CI test would still pass. So each job here answers differently, and exactly the
    one that is red is asserted to be the one that fails.
    """
    monkeypatch.setattr(fc.shutil, "which", lambda _n: "gh")
    # one red among many greens, plus a distinguishable timestamp per job
    red = ("owner/beta", "dash-guard.yml")

    def fake(args, **_k):
        if "api" in args:
            return 0, "main\n", ""
        slug = args[args.index("-R") + 1]
        wf = args[args.index("-w") + 1]
        concl = "failure" if (slug, wf) == red else "success"
        return 0, json.dumps([{"conclusion": concl, "status": "completed",
                               "createdAt": "%s|%s" % (slug, wf), "headBranch": "main"}]), ""

    monkeypatch.setattr(fc, "run", fake)
    targets = [(s, ["pii-guard.yml", "dash-guard.yml", "test.yml"], "", "PUBLIC")
               for s in ("owner/alpha", "owner/beta", "owner/gamma")]
    c = fc.check_ci(targets, 5)

    assert len(c.rows) == 9
    # Every row carries the evidence generated for ITS OWN (slug, workflow), not another job's.
    for status, name, detail in c.rows:
        slug, _, rest = name.partition(" [")
        wf = rest.rstrip("]").split(":", 1)[1]
        assert "%s|%s" % (slug, wf) in detail, "row %s got another job's result: %s" % (name, detail)
        assert status == (fc.FAIL if (slug, wf) == red else fc.PASS)
    assert [n for s, n, _d in c.rows if s == fc.FAIL] == ["owner/beta [guard:dash-guard.yml]"]


def test_ci_rows_are_in_a_deterministic_order_regardless_of_completion_order(monkeypatch):
    """Row order must come from the sort, not from which thread finished first.

    A report whose row order moves run to run cannot be diffed against yesterday's, and diffing it
    against yesterday's is how a new offender gets noticed.
    """
    monkeypatch.setattr(fc.shutil, "which", lambda _n: "gh")
    delays = {"owner/alpha": 0.05, "owner/beta": 0.0, "owner/gamma": 0.025}

    def fake(args, **_k):
        if "api" in args:
            return 0, "main\n", ""
        time.sleep(delays[args[args.index("-R") + 1]])   # finish in the reverse of sorted order
        return 0, _runs("success"), ""

    monkeypatch.setattr(fc, "run", fake)
    targets = [(s, ["b.yml", "a.yml"], "", "PUBLIC")
               for s in ("owner/gamma", "owner/alpha", "owner/beta")]
    names = [n for _s, n, _d in fc.check_ci(targets, 5).rows]
    assert names == ["owner/alpha [other:a.yml]", "owner/alpha [other:b.yml]",
                     "owner/beta [other:a.yml]", "owner/beta [other:b.yml]",
                     "owner/gamma [other:a.yml]", "owner/gamma [other:b.yml]"]


def test_workflow_rows_keep_their_own_listing_under_the_fan_out(monkeypatch, tmp_path):
    """Same cross-talk question for the workflow check: the FAIL must name the right repo."""
    _fake_remote(monkeypatch, {"owner/full": BOTH, "owner/half": ["pii-guard.yml"],
                               "owner/none": []})
    c = fc.check_workflow(_vis(tmp_path, {"owner/full": "PUBLIC", "owner/half": "PUBLIC",
                                          "owner/none": "PUBLIC"}),
                          {"owner/full": "/x", "owner/half": "/y", "owner/none": "/z"}, "/code")
    assert {n: s for s, n, _d in c.rows} == {"owner/full": fc.PASS, "owner/half": fc.FAIL,
                                            "owner/none": fc.FAIL}
    detail = {n: d for _s, n, d in c.rows}
    # owner/half is missing exactly dash-guard, and its row must say so and echo ITS listing.
    assert "has no dash-guard" in detail["owner/half"]
    assert "pii-guard.yml" in detail["owner/half"]
    # owner/none is missing both, and must not have inherited a neighbour's listing.
    assert "has no pii-guard, dash-guard" in detail["owner/none"]
    assert "remote workflows: none" in detail["owner/none"]


def test_memo_calls_the_producer_once_per_key_even_under_concurrency():
    """The dedup has to hold when eight threads miss the same key at the same moment.

    A plain check-then-set would let them all through and reissue the same gh call, which is how a
    "memoized" run quietly costs what the unmemoized one did.
    """
    memo, calls = fc.Memo(), []
    lock = threading.Lock()

    def produce(key):
        time.sleep(0.02)                      # widen the window a naive cache would race through
        with lock:
            calls.append(key)
        return key.upper()

    keys = ["a", "b", "a", "b", "a", "b", "a", "b"]
    got = fc.pmap(lambda k: memo.get(k, lambda k=k: produce(k)), keys)
    assert got == [k.upper() for k in keys]
    assert sorted(calls) == ["a", "b"]


def test_pmap_preserves_input_order():
    out = fc.pmap(lambda n: (time.sleep((10 - n) / 200.0), n)[1], list(range(10)))
    assert out == list(range(10))


def test_coverage_is_stated_next_to_the_verdict_word_not_only_at_the_end():
    """A reader who stops after the verdict must not come away with the wrong noun.

    The coverage fraction was already on this line, four fields to the RIGHT of the verdict, on a
    run where 88 of 200 rows were never evaluated. That is not far enough forward to do any work.
    """
    partial = {"pass": 104, "fail": 0, "warn": 0, "skip": 88, "unknown": 0}
    line, verdict = fc.digest_line(partial)
    assert verdict == "GREEN"                  # the machine-readable token is unchanged
    head = line.split("|")[0]                  # ...but the word never travels alone
    assert "GREEN" in head and "88" in head and "NOT EVALUATED" in head
    assert line.index("54%") < line.index("pass 104")

    full = {"pass": 200, "fail": 0, "warn": 0, "skip": 0, "unknown": 0}
    assert "NOT EVALUATED" not in fc.digest_line(full)[0].split("|")[0]
