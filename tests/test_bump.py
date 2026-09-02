#!/usr/bin/env python3
"""Tests for bump_version.py and the shared version_sites.py site definitions.

The two behaviours that matter most are the ones a careless writer gets wrong:
  - it REFUSES on an already-drifted repo instead of papering over the drift, and
  - a bump that fails partway leaves NO half-written repo behind.
Everything else here guards the five sites moving together.

Stdlib + pytest only. No network. Every repo is scaffolded fresh into tmp_path.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_REPO, "skills", "skill-smith", "scripts")

SCAFFOLD = os.path.join(_SCRIPTS, "scaffold_skill.py")
CONFORM = os.path.join(_SCRIPTS, "check_conformance.py")
BUMP = os.path.join(_SCRIPTS, "bump_version.py")

sys.path.insert(0, _SCRIPTS)
import version_sites as vs  # noqa: E402

DATE = "2026-01-02"



# A scaffolded fixture is NOT green on one item, on purpose: .dataclass.json ships with an empty
# "data" list and no "_audited" key, and the boundary check fails that state because an empty
# declaration is only an answer if somebody looked. Where a skill writes is not knowable before
# it has run, so a scaffolder that pre-filled the key would assert, for the author, exactly the
# thing the key exists to make somebody check. These tests are about VERSION SITES, so they skip
# that one item by name rather than by relaxing the whole gate.
NEEDS_A_HUMAN = ("data boundary: repo is an uninitialized tool",)


def unexpected_failures(stdout):
    """FAIL lines that are not one of the known-and-required-open items."""
    return [ln for ln in stdout.splitlines()
            if "[FAIL]" in ln and not any(k in ln for k in NEEDS_A_HUMAN)]

def run(args, **kw):
    return subprocess.run([sys.executable] + args, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120, **kw)


def mkrepo(tmp_path, name="rel-skill", version="0.1.0"):
    out = str(tmp_path / "out")
    r = run([SCAFFOLD, name, "--description", "x", "--out-dir", out, "--version", version])
    assert r.returncode == 0, r.stdout + r.stderr
    return os.path.join(out, name)


def read(repo, rel):
    with open(os.path.join(repo, rel), encoding="utf-8", newline="") as f:
        return f.read()


def write(repo, rel, text):
    with open(os.path.join(repo, rel), "w", encoding="utf-8", newline="") as f:
        f.write(text)


# ===========================================================================
# version_sites: the shape, including the pre-release marker that used to break the linter
# ===========================================================================

def test_badge_regex_accepts_prerelease_suffix():
    plain = "[![Roadmap](https://img.shields.io/badge/Roadmap-v0.2.2-purple?style=flat)](ROADMAP.md)"
    alpha = "[![Roadmap](https://img.shields.io/badge/Roadmap-v0.2.2%20alpha-purple?style=flat)](ROADMAP.md)"
    assert vs.badge_version(plain) == ("0.2.2", "")
    assert vs.badge_version(alpha) == ("0.2.2", "%20alpha")


def test_conformance_green_on_prerelease_badge(tmp_path):
    """A deliberate pre-release marker in the badge is not drift. This is the buy-me-a-car case:
    all five sites read 0.2.2 and the linter used to call the repo broken."""
    repo = mkrepo(tmp_path)
    for rel in ("README.md", "README_CN.md"):
        write(repo, rel, read(repo, rel).replace("Roadmap-v0.1.0-purple",
                                                 "Roadmap-v0.1.0%20alpha-purple"))
    c = run([CONFORM, repo])
    _x = unexpected_failures(c.stdout)
    assert not _x, c.stdout
    assert any(k in c.stdout for k in NEEDS_A_HUMAN), c.stdout


def test_next_version_levels():
    assert vs.next_version("1.2.3", "patch") == "1.2.4"
    assert vs.next_version("1.2.3", "minor") == "1.3.0"
    assert vs.next_version("1.2.3", "major") == "2.0.0"


# ===========================================================================
# bump_version: all five sites move together
# ===========================================================================

def test_bump_moves_all_five_sites(tmp_path):
    repo = mkrepo(tmp_path, version="0.1.0")
    r = run([BUMP, repo, "--level", "minor", "--notes", "Adds the widget.", "--date", DATE])
    assert r.returncode == 0, r.stdout + r.stderr

    pj = json.loads(read(repo, os.path.join(".claude-plugin", "plugin.json")))
    assert pj["version"] == "0.2.0"
    assert "Roadmap-v0.2.0-purple" in read(repo, "README.md")
    assert "Roadmap-v0.2.0-purple" in read(repo, "README_CN.md")
    roadmap = read(repo, "ROADMAP.md")
    assert "Current: **v0.2.0**" in roadmap
    assert "## v0.2.0 (current)" in roadmap
    assert "Adds the widget." in roadmap
    changelog = read(repo, "CHANGELOG.md")
    assert ("## [0.2.0] - %s" % DATE) in changelog
    assert "## [0.1.0]" in changelog, "history must survive the bump"

    c = run([CONFORM, repo])
    _x = unexpected_failures(c.stdout)
    assert not _x, c.stdout
    assert any(k in c.stdout for k in NEEDS_A_HUMAN), c.stdout


def test_bump_demotes_previous_roadmap_heading(tmp_path):
    repo = mkrepo(tmp_path, version="0.1.0")
    assert "## v0.1.0 (current)" in read(repo, "ROADMAP.md")
    r = run([BUMP, repo, "--level", "patch", "--date", DATE])
    assert r.returncode == 0, r.stdout
    roadmap = read(repo, "ROADMAP.md")
    assert "## v0.1.1 (current)" in roadmap
    assert "## v0.1.0\n" in roadmap, "old heading must lose its (current) marker"
    assert roadmap.count("(current)") == 1


def test_bump_set_exact_version(tmp_path):
    repo = mkrepo(tmp_path, version="0.1.0")
    r = run([BUMP, repo, "--set", "1.4.7", "--date", DATE])
    assert r.returncode == 0, r.stdout
    assert vs.collect(repo)["plugin"] == "1.4.7"
    assert vs.is_synced(vs.collect(repo))


def test_bump_rejects_bad_set_value(tmp_path):
    repo = mkrepo(tmp_path)
    r = run([BUMP, repo, "--set", "1.4", "--date", DATE])
    assert r.returncode == 2, r.stdout
    assert vs.collect(repo)["plugin"] == "0.1.0", "a rejected bump must change nothing"


def test_bump_requires_a_level_or_set(tmp_path):
    repo = mkrepo(tmp_path)
    r = run([BUMP, repo])
    assert r.returncode != 0


# ===========================================================================
# the precondition: refuse on drift, and touch nothing while refusing
# ===========================================================================

def test_bump_refuses_drifted_repo_and_changes_nothing(tmp_path):
    repo = mkrepo(tmp_path, version="0.1.0")
    # simulate the usual half-applied release: plugin.json moved, the badges did not
    pjrel = os.path.join(".claude-plugin", "plugin.json")
    write(repo, pjrel, read(repo, pjrel).replace('"version": "0.1.0"', '"version": "0.1.1"'))
    before = {rel: read(repo, rel) for rel in
              (pjrel, "README.md", "README_CN.md", "ROADMAP.md", "CHANGELOG.md")}

    r = run([BUMP, repo, "--level", "patch", "--date", DATE])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "REFUSING" in r.stdout
    assert "version four-source synced" in r.stdout, "must print the check_conformance diff"
    assert "0.1.1" in r.stdout and "0.1.0" in r.stdout, "must name both drifted values"
    for rel, txt in before.items():
        assert read(repo, rel) == txt, "a refusal must not write to %s" % rel


def test_bump_refuses_when_a_site_is_missing(tmp_path):
    repo = mkrepo(tmp_path)
    os.remove(os.path.join(repo, "README_CN.md"))
    r = run([BUMP, repo, "--level", "patch", "--date", DATE])
    assert r.returncode == 1, r.stdout
    assert "REFUSING" in r.stdout


def test_bump_refuses_same_version(tmp_path):
    repo = mkrepo(tmp_path, version="0.1.0")
    r = run([BUMP, repo, "--set", "0.1.0", "--date", DATE])
    assert r.returncode == 2, r.stdout


# ===========================================================================
# pre-release round-trip
# ===========================================================================

def test_bump_preserves_prerelease_marker(tmp_path):
    """buy-me-a-car's badge says v0.2.2%20alpha on purpose. A bump that flattened it would quietly
    promote a pre-release to a release in the one place a user actually looks."""
    repo = mkrepo(tmp_path, version="0.2.2")
    for rel in ("README.md", "README_CN.md"):
        write(repo, rel, read(repo, rel).replace("Roadmap-v0.2.2-purple",
                                                 "Roadmap-v0.2.2%20alpha-purple"))
    r = run([BUMP, repo, "--level", "patch", "--date", DATE])
    assert r.returncode == 0, r.stdout
    assert "Roadmap-v0.2.3%20alpha-purple" in read(repo, "README.md")
    assert "Roadmap-v0.2.3%20alpha-purple" in read(repo, "README_CN.md")
    # semver sites stay plain: they are read by machines that expect semver
    assert json.loads(read(repo, os.path.join(".claude-plugin", "plugin.json")))["version"] == "0.2.3"
    assert "Current: **v0.2.3**" in read(repo, "ROADMAP.md")
    c = run([CONFORM, repo])
    _x = unexpected_failures(c.stdout)
    assert not _x, c.stdout
    assert any(k in c.stdout for k in NEEDS_A_HUMAN), c.stdout


def test_bump_can_drop_and_set_prerelease(tmp_path):
    repo = mkrepo(tmp_path, version="0.2.2")
    for rel in ("README.md", "README_CN.md"):
        write(repo, rel, read(repo, rel).replace("Roadmap-v0.2.2-purple",
                                                 "Roadmap-v0.2.2%20alpha-purple"))
    assert run([BUMP, repo, "--level", "patch", "--no-prerelease",
                "--date", DATE]).returncode == 0
    assert "Roadmap-v0.2.3-purple" in read(repo, "README.md")
    assert run([BUMP, repo, "--set", "1.0.0", "--prerelease", "rc.1",
                "--date", DATE]).returncode == 0
    assert "Roadmap-v1.0.0%20rc.1-purple" in read(repo, "README.md")


# ===========================================================================
# CHANGELOG Unreleased absorption
# ===========================================================================

def test_bump_absorbs_unreleased_section(tmp_path):
    repo = mkrepo(tmp_path, version="0.1.0")
    cl = read(repo, "CHANGELOG.md").replace(
        "## [0.1.0]",
        "## [Unreleased]\n### Added\n- Work that accumulated since 0.1.0.\n\n## [0.1.0]", 1)
    write(repo, "CHANGELOG.md", cl)
    r = run([BUMP, repo, "--level", "minor", "--date", DATE])
    assert r.returncode == 0, r.stdout
    out = read(repo, "CHANGELOG.md")
    assert "Unreleased" not in out, "the staging heading must become the release heading"
    assert ("## [0.2.0] - %s" % DATE) in out
    assert "Work that accumulated since 0.1.0." in out, "the body must be absorbed, not dropped"
    assert "## [0.1.0]" in out


# ===========================================================================
# dry run + no VCS side effects
# ===========================================================================

def test_dry_run_writes_nothing(tmp_path):
    repo = mkrepo(tmp_path, version="0.1.0")
    before = {rel: read(repo, rel) for rel in
              (os.path.join(".claude-plugin", "plugin.json"), "README.md", "README_CN.md",
               "ROADMAP.md", "CHANGELOG.md")}
    r = run([BUMP, repo, "--level", "major", "--dry-run", "--date", DATE])
    assert r.returncode == 0, r.stdout
    assert "1.0.0" in r.stdout
    for rel, txt in before.items():
        assert read(repo, rel) == txt


def test_bump_never_commits_or_tags(tmp_path):
    """A version bump is a release decision. The tool moves numbers and stops."""
    repo = mkrepo(tmp_path, version="0.1.0")
    assert subprocess.run(["git", "init", "-q"], cwd=repo, capture_output=True).returncode == 0
    r = run([BUMP, repo, "--level", "patch", "--date", DATE])
    assert r.returncode == 0, r.stdout
    n_commits = subprocess.run(["git", "rev-list", "--all", "--count"], cwd=repo,
                               capture_output=True, text=True).stdout.strip()
    assert n_commits == "0", "must not commit (found %s commit(s))" % n_commits
    tags = subprocess.run(["git", "tag"], cwd=repo, capture_output=True, text=True).stdout
    assert not tags.strip(), "must not tag"
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=repo,
                           capture_output=True, text=True).stdout
    assert dirty.strip(), "the bump must be left in the worktree for a human to review"


# ===========================================================================
# no half-written repo on failure
# ===========================================================================

def test_failure_leaves_no_partial_bump(tmp_path, monkeypatch):
    """Five files cannot be replaced in one filesystem operation, so the failure mode has to be
    tested directly: make the fourth write throw and assert the first three were put back."""
    repo = mkrepo(tmp_path, version="0.1.0")
    sys.path.insert(0, _SCRIPTS)
    import bump_version as bumpmod

    before = {rel: read(repo, rel) for rel in
              (os.path.join(".claude-plugin", "plugin.json"), "README.md", "README_CN.md",
               "ROADMAP.md", "CHANGELOG.md")}

    real = bumpmod._atomic_write
    state = {"n": 0}

    def flaky(path, text):
        state["n"] += 1
        if state["n"] == 4:
            raise OSError("simulated disk failure")
        return real(path, text)

    monkeypatch.setattr(bumpmod, "_atomic_write", flaky)
    try:
        bumpmod.main([repo, "--level", "patch", "--date", DATE])
    except RuntimeError:
        pass
    else:
        raise AssertionError("a failed write must surface, not pass silently")

    for rel, txt in before.items():
        assert read(repo, rel) == txt, "%s was left bumped after a failed run" % rel
    assert vs.is_synced(vs.collect(repo)), "repo must not be left drifted by a failed bump"
    leftovers = [f for f in os.listdir(repo) if f.startswith(".bump-")]
    assert not leftovers, "temp files left behind: %s" % leftovers


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
