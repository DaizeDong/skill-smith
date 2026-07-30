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

    c = fc.check_data_boundary({"clean": str(root / "clean")})
    assert [s for s, _n, _d in c.rows] == [fc.UNKNOWN]
    assert c.count(fc.PASS) == 0


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

    c = fc.check_data_boundary({"drifted": str(d)})
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
