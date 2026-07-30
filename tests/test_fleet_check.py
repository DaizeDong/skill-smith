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


# --- check 2: PUBLIC implies a workflow ---------------------------------------------------------
def test_workflow_missing_is_a_fail(tmp_path):
    root = tmp_path / "code"
    root.mkdir()
    make_repo(root, "with-wf", workflow=True)
    make_repo(root, "no-wf")
    vis = tmp_path / "visibility.json"
    vis.write_text(json.dumps({"owner/with-wf": "PUBLIC", "owner/no-wf": "PUBLIC"}),
                   encoding="utf-8")
    slugs = {"owner/with-wf": str(root / "with-wf"), "owner/no-wf": str(root / "no-wf")}

    c = fc.check_workflow(str(vis), slugs, str(root))
    got = {n: s for s, n, _d in c.rows}
    assert got == {"owner/with-wf": fc.PASS, "owner/no-wf": fc.FAIL}


def test_workflow_phantom_entry_skips_not_fails(tmp_path):
    """The visibility map outlives its working copies and names repos not checked out here.

    Failing on one would make the check permanently red for a reason no edit in any repo can fix.
    """
    vis = tmp_path / "visibility.json"
    vis.write_text(json.dumps({"owner/never-cloned": "PUBLIC"}), encoding="utf-8")
    c = fc.check_workflow(str(vis), {}, str(tmp_path))
    assert [s for s, _n, _d in c.rows] == [fc.SKIP]
    assert c.count(fc.FAIL) == 0


def test_workflow_private_entries_are_not_checked(tmp_path):
    vis = tmp_path / "visibility.json"
    vis.write_text(json.dumps({"owner/secret": "PRIVATE", "owner/dunno": "UNKNOWN"}),
                   encoding="utf-8")
    c = fc.check_workflow(str(vis), {}, str(tmp_path))
    assert c.rows == []


def test_workflow_unreadable_map_is_unknown_not_fail(tmp_path):
    c = fc.check_workflow(str(tmp_path / "nope.json"), {}, str(tmp_path))
    assert c.count(fc.FAIL) == 0
    assert c.count(fc.UNKNOWN) == 1


# --- check 4: the inverse data boundary ---------------------------------------------------------
def test_data_dir_inside_a_git_worktree_fails(tmp_path, monkeypatch):
    """The one check that would have caught the 2026-07 leak from the other end."""
    root = tmp_path / "code"
    root.mkdir()
    make_repo(root, "leaky", datadir=True)

    worktree = tmp_path / "some-repo"
    (worktree / "data").mkdir(parents=True)
    assert git("init", "-q", cwd=worktree).returncode == 0
    monkeypatch.setenv("LEAKY_DATA_DIR", str(worktree / "data"))

    c = fc.check_data_boundary({"leaky": str(root / "leaky")})
    assert [s for s, _n, _d in c.rows] == [fc.FAIL]
    assert "inside git worktree" in c.rows[0][2]


def test_data_dir_outside_git_passes(tmp_path, monkeypatch):
    root = tmp_path / "code"
    root.mkdir()
    make_repo(root, "clean", datadir=True)
    store = tmp_path / "private-store"
    store.mkdir()
    monkeypatch.setenv("CLEAN_DATA_DIR", str(store))

    c = fc.check_data_boundary({"clean": str(root / "clean")})
    assert [s for s, _n, _d in c.rows] == [fc.PASS]


def test_uninitialized_data_dir_skips(tmp_path, monkeypatch):
    """An uninitialized tool is the CORRECT shipping state, so this must never be a failure."""
    root = tmp_path / "code"
    root.mkdir()
    make_repo(root, "fresh", datadir=True)
    monkeypatch.delenv("FRESH_DATA_DIR", raising=False)

    c = fc.check_data_boundary({"fresh": str(root / "fresh")})
    assert [s for s, _n, _d in c.rows] == [fc.SKIP]
    assert c.count(fc.FAIL) == 0


def test_repo_without_datadir_is_not_reported(tmp_path):
    root = tmp_path / "code"
    root.mkdir()
    make_repo(root, "plain")
    assert fc.check_data_boundary({"plain": str(root / "plain")}).rows == []


# --- check 5: the CI probe degrades, it never blocks ---------------------------------------------
def _ci_with_gh(monkeypatch, rc, stdout, stderr=""):
    monkeypatch.setattr(fc.shutil, "which", lambda _n: "gh")
    monkeypatch.setattr(fc, "run", lambda *_a, **_k: (rc, stdout, stderr))
    return fc.check_ci(["owner/repo"], 5)


def test_ci_success_passes(monkeypatch):
    c = _ci_with_gh(monkeypatch, 0, json.dumps(
        [{"conclusion": "success", "status": "completed", "createdAt": "2026-01-01T00:00:00Z"}]))
    assert [s for s, _n, _d in c.rows] == [fc.PASS]


def test_ci_failure_fails(monkeypatch):
    c = _ci_with_gh(monkeypatch, 0, json.dumps(
        [{"conclusion": "failure", "status": "completed", "createdAt": "2026-01-01T00:00:00Z"}]))
    assert [s for s, _n, _d in c.rows] == [fc.FAIL]


@pytest.mark.parametrize("rc,out,err", [
    (1, "", "gh: not authenticated"),          # unauthenticated
    (1, "", "API rate limit exceeded"),        # rate limited
    (0, "[]", ""),                             # workflow never ran
    (0, "not json", ""),                       # garbage
])
def test_ci_unobservable_is_unknown_never_fail(monkeypatch, rc, out, err):
    c = _ci_with_gh(monkeypatch, rc, out, err)
    assert c.count(fc.FAIL) == 0
    assert c.count(fc.UNKNOWN) == 1


def test_ci_in_progress_is_unknown(monkeypatch):
    c = _ci_with_gh(monkeypatch, 0, json.dumps(
        [{"conclusion": None, "status": "in_progress", "createdAt": "2026-01-01T00:00:00Z"}]))
    assert [s for s, _n, _d in c.rows] == [fc.UNKNOWN]


def test_ci_without_gh_is_unknown(monkeypatch):
    monkeypatch.setattr(fc.shutil, "which", lambda _n: None)
    c = fc.check_ci(["owner/repo"], 5)
    assert c.count(fc.FAIL) == 0
    assert c.count(fc.UNKNOWN) == 1


# --- the output contract -------------------------------------------------------------------------
def test_status_json_shape_and_timestamp(tmp_path):
    c = fc.Check("demo", "demo check")
    c.add(fc.PASS, "a")
    c.add(fc.FAIL, "b", "because")
    tot = {"pass": 1, "fail": 1, "skip": 0, "unknown": 0}
    out = tmp_path / "nested" / "status.json"
    fc.write_status(str(out), [c], tot, "2026-01-01T00:00:00Z", 1.5, 1)

    got = json.loads(out.read_text(encoding="utf-8"))
    assert got["utc"] == "2026-01-01T00:00:00Z"     # freshness is the caller's whole mechanism
    assert got["exit"] == 1
    assert got["totals"] == tot
    assert got["checks"]["demo"]["fail"] == 1
    assert got["failures"] == ["demo: b -- because"]
    assert not list(tmp_path.glob("**/*.tmp"))       # written atomically, no debris


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
