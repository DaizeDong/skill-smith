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
    def fake(slug, path, timeout, offline=False):
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
def _vis_map(tmp_path, mapping):
    p = tmp_path / "visibility.json"
    p.write_text(json.dumps(mapping), encoding="utf-8")
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
def _ci_with_gh(monkeypatch, rc, stdout, stderr="", targets=None):
    monkeypatch.setattr(fc.shutil, "which", lambda _n: "gh")
    monkeypatch.setattr(fc, "run", lambda *_a, **_k: (rc, stdout, stderr))
    return fc.check_ci(targets or [("owner/repo", ["pii-guard"])], 5)


def _runs(conclusion, status="completed"):
    return json.dumps([{"conclusion": conclusion, "status": status,
                        "createdAt": "2026-01-01T00:00:00Z"}])


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
        wf = args[args.index("-w") + 1]
        return 0, _runs("success" if wf == "pii-guard" else "failure"), ""

    monkeypatch.setattr(fc, "run", fake_run)
    c = fc.check_ci([("owner/repo", ["pii-guard", "dash-guard"])], 5)
    got = {n: s for s, n, _d in c.rows}
    assert got == {"owner/repo [pii-guard]": fc.PASS, "owner/repo [dash-guard]": fc.FAIL}


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
    c = fc.check_ci([("owner/repo", ["pii-guard"])], 5)
    assert c.count(fc.FAIL) == 0
    assert c.count(fc.UNKNOWN) == 1


def test_ci_with_no_targets_says_so_instead_of_printing_nothing(monkeypatch):
    """Zero rows renders as "pass 0, fail 0", which reads like a clean fleet."""
    monkeypatch.setattr(fc.shutil, "which", lambda _n: "gh")
    c = fc.check_ci([], 5)
    assert c.count(fc.UNKNOWN) == 1


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
@pytest.mark.parametrize("rc,want", [(0, "PASS"), (1, "FAIL"), (2, "UNKNOWN"), (None, "UNKNOWN")])
def test_budget_maps_the_tools_exit_code(monkeypatch, rc, want):
    monkeypatch.setattr(fc, "run", lambda *_a, **_k: (rc, "STATUS: OK\n", "boom"))
    c = fc.check_budget("skills", "code", 30)
    assert c.rows[0][0] == want, c.rows


def test_budget_pass_with_truncation_is_a_warning(monkeypatch):
    """A tool that exits 0 while its own output names a truncated skill has drifted.

    budget_check now FAILS on truncation whatever the tier, so rc==0 with victims should be
    impossible. This asserts the disagreement is caught rather than rounded up to PASS: a caller
    that trusts an exit code over the report it just read is how the last clean sheet was produced.
    """
    out = ("user tier ends at : 20999 chars\n"
           "    training-check  other  running total 20617  (past the high bound: certainly truncated)\n"
           "  TRUNCATED: 1 skill(s) past the observed cutoff\n"
           "STATUS: OK (our tier clean)\n")
    monkeypatch.setattr(fc, "run", lambda *_a, **_k: (0, out, ""))
    c = fc.check_budget("skills", "code", 30)
    assert c.rows[0][0] == fc.WARN, c.rows
    assert "1 skill(s) past the cutoff" in c.rows[0][2]


def test_budget_truncation_count_comes_from_the_machine_readable_line(monkeypatch):
    """The count is READ, not inferred from prose.

    Regression: the count used to be derived by grepping stdout for the phrases that name a victim.
    Once budget_check also repeated those phrases in its FAIL list, four truncated skills were
    reported as eight. The victim names appear twice in this fixture on purpose.
    """
    out = ("user tier ends at : 20781 chars\n"
           "    training-check  other  running total 20399  (past the high bound: certainly truncated)\n"
           "    vast-gpu       other  running total 20591  (past the high bound: certainly truncated)\n"
           "  TRUNCATED: 2 skill(s) past the observed cutoff\n"
           "  STATUS: FAIL\n"
           "    - training-check [other]: past the high bound, certainly truncated at running total 20399\n"
           "    - vast-gpu [other]: past the high bound, certainly truncated at running total 20591\n")
    monkeypatch.setattr(fc, "run", lambda *_a, **_k: (1, out, ""))
    c = fc.check_budget("skills", "code", 30)
    assert c.rows[0][0] == fc.FAIL, c.rows
    assert "2 skill(s) past the cutoff" in c.rows[0][2], c.rows[0][2]


def test_budget_reports_no_count_when_nothing_is_truncated(monkeypatch):
    out = ("user tier ends at : 5000 chars\n"
           "  TRUNCATED: 0 skill(s) past the observed cutoff\n"
           "  STATUS: OK (our tier clean; user tier at 25% of the observed cutoff).\n")
    monkeypatch.setattr(fc, "run", lambda *_a, **_k: (0, out, ""))
    c = fc.check_budget("skills", "code", 30)
    assert c.rows[0][0] == fc.PASS, c.rows
    assert "past the cutoff" not in c.rows[0][2], c.rows[0][2]


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
