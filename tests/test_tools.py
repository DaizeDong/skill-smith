#!/usr/bin/env python3
"""A-provider signal for skill-smith: assert the pipeline and every tool work.

This is the self-evolve A-tier grader for this repo. It must:
  - exit 0 when the 4 scripts are correct, and
  - go red (mutation_killed) when any script is broken.

Run:  python -m pytest -q   (from repo root)

Stdlib + pytest only. No network. Cross-platform (uses tmp_path, no shell).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

# ---------------------------------------------------------------------------
# Locate scripts relative to this test file (repo-root independent).
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_REPO, "skills", "skill-smith", "scripts")

SCAFFOLD = os.path.join(_SCRIPTS, "scaffold_skill.py")
CONFORM = os.path.join(_SCRIPTS, "check_conformance.py")
BUDGET = os.path.join(_SCRIPTS, "budget_check.py")
DEDUP = os.path.join(_SCRIPTS, "dedup_check.py")


def run(args, **kw):
    """Run a script as a subprocess; return CompletedProcess (text)."""
    proc = subprocess.run(
        [sys.executable] + args,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, **kw,
    )
    return proc


def write_utf8(path, text, bom=False):
    """Write text without (default) or with a UTF-8 BOM, no platform newline mangling."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = text.encode("utf-8-sig" if bom else "utf-8")
    with open(path, "wb") as f:
        f.write(data)


def make_skill(libdir, name, desc, bom=False):
    """Create <libdir>/<name>/SKILL.md with given frontmatter."""
    body = "---\nname: %s\ndescription: %s\n---\nbody\n" % (name, desc)
    write_utf8(os.path.join(libdir, name, "SKILL.md"), body, bom=bom)


# ===========================================================================
# 0. Scripts exist and are importable as files
# ===========================================================================

def test_scripts_present():
    for p in (SCAFFOLD, CONFORM, BUDGET, DEDUP):
        assert os.path.isfile(p), "missing tool: %s" % p


# ===========================================================================
# 1. check_conformance on skill-smith itself -> 20/20, exit 0
# ===========================================================================

def test_conformance_self_passes():
    r = run([CONFORM, _REPO])
    assert r.returncode == 0, "skill-smith must pass its own gate:\n%s\n%s" % (r.stdout, r.stderr)
    assert "passed" in r.stdout
    # every line must be PASS (no FAIL anywhere)
    assert "[FAIL]" not in r.stdout, r.stdout


def test_conformance_bad_dir_fails():
    """A directory missing required files must FAIL (grader is discriminating, not a rubber stamp)."""
    r = run([CONFORM, _SCRIPTS])  # scripts dir is not a spec repo
    assert r.returncode == 1, "non-conformant dir must exit 1:\n%s" % r.stdout
    assert "[FAIL]" in r.stdout


# ===========================================================================
# 2. End-to-end: scaffold -> check_conformance passes (the core pipeline)
# ===========================================================================

def test_scaffold_then_conformance(tmp_path):
    out = str(tmp_path / "out")
    r = run([SCAFFOLD, "my-skill",
             "--tagline", "Do the thing fast.",
             "--description", "When the user wants X, do Y in scope Z.",
             "--topics", "alpha,beta",
             "--out-dir", out, "--version", "0.3.0"])
    assert r.returncode == 0, r.stdout + r.stderr
    repo = os.path.join(out, "my-skill")
    assert os.path.isdir(repo)
    c = run([CONFORM, repo])
    assert c.returncode == 0, "scaffold output must be 20/20 conformant:\n%s" % c.stdout
    assert "[FAIL]" not in c.stdout


def test_scaffold_kebab_normalization(tmp_path):
    out = str(tmp_path / "out")
    r = run([SCAFFOLD, "Test Skill_FOO",
             "--description", "x", "--out-dir", out])
    assert r.returncode == 0, r.stdout + r.stderr
    assert os.path.isdir(os.path.join(out, "test-skill-foo")), \
        "messy name must normalize to kebab-case: %s" % os.listdir(out)
    assert "normalized name" in r.stdout


def test_scaffold_rejects_empty_name(tmp_path):
    """A name that kebab-normalizes to empty must be refused with a clear error,
    not silently collapse the repo root onto --out-dir itself."""
    out = str(tmp_path / "out")
    os.makedirs(out, exist_ok=True)
    r = run([SCAFFOLD, "___", "--description", "x", "--out-dir", out])
    assert r.returncode == 2, "empty kebab name must be rejected (exit 2):\n%s" % r.stdout
    # Must be the *empty-name* error specifically, not the generic "already exists" path
    # the unfixed scaffold falls into when root collapses onto --out-dir.
    assert "normalizes to empty" in r.stdout, \
        "must give a clear empty-name error, not 'already exists':\n%s" % r.stdout
    assert os.listdir(out) == [], "must not scaffold anything for an empty name: %s" % os.listdir(out)


def test_dedup_candidate_case_insensitive(tmp_path):
    """An UPPERCASE candidate description must still match a lowercase library entry
    (tokenization lowercases), otherwise dedup misses real duplicates by mere casing."""
    lib = str(tmp_path / "lib")
    make_skill(lib, "alpha", "parse pdf invoices and extract totals.")
    r = run([DEDUP, "--skills-dir", lib, "--threshold", "0.4",
             "--desc", "PARSE PDF INVOICES AND EXTRACT TOTALS", "--name", "C"])
    assert r.returncode == 1, "uppercase duplicate must be flagged:\n%s" % r.stdout


def test_scaffold_version_four_source_sync(tmp_path):
    """The four version sources the linter checks must all carry the --version value."""
    out = str(tmp_path / "out")
    ver = "1.2.3"
    r = run([SCAFFOLD, "verskill", "--description", "x", "--out-dir", out, "--version", ver])
    assert r.returncode == 0
    repo = os.path.join(out, "verskill")
    pj = json.loads(open(os.path.join(repo, ".claude-plugin", "plugin.json"), encoding="utf-8").read())
    assert pj["version"] == ver
    readme = open(os.path.join(repo, "README.md"), encoding="utf-8").read()
    roadmap = open(os.path.join(repo, "ROADMAP.md"), encoding="utf-8").read()
    changelog = open(os.path.join(repo, "CHANGELOG.md"), encoding="utf-8").read()
    assert ("Roadmap-v%s-purple" % ver) in readme
    assert ("Current: **v%s**" % ver) in roadmap
    assert ("[%s]" % ver) in changelog


def test_scaffold_plugin_fingerprint(tmp_path):
    out = str(tmp_path / "out")
    r = run([SCAFFOLD, "fp-skill", "--description", "x", "--topics", "foo,bar", "--out-dir", out])
    assert r.returncode == 0
    pj = json.loads(open(os.path.join(out, "fp-skill", ".claude-plugin", "plugin.json"),
                         encoding="utf-8").read())
    assert pj["author"]["name"] == "DaizeDong"
    assert pj["license"] == "MIT"
    assert pj["homepage"] == "https://github.com/DaizeDong/fp-skill"
    assert pj["keywords"][-1] == "skill"
    assert "foo" in pj["keywords"] and "bar" in pj["keywords"]


def test_scaffold_refuses_without_force(tmp_path):
    out = str(tmp_path / "out")
    a1 = run([SCAFFOLD, "dup", "--description", "x", "--out-dir", out])
    assert a1.returncode == 0
    a2 = run([SCAFFOLD, "dup", "--description", "x", "--out-dir", out])  # no --force
    assert a2.returncode == 2, "existing repo without --force must refuse (exit 2):\n%s" % a2.stdout
    a3 = run([SCAFFOLD, "dup", "--description", "x", "--out-dir", out, "--force"])
    assert a3.returncode == 0, "with --force it must overwrite:\n%s" % a3.stdout


# ===========================================================================
# 3. budget_check: correct totals + case-insensitive dedupe (no double count)
# ===========================================================================

def test_budget_totals(tmp_path):
    lib = str(tmp_path / "lib")
    # name "alpha"(5) + desc(38) + 12 = 55 ; name "beta"(4) + desc(43) + 12 = 59
    make_skill(lib, "alpha", "parse pdf invoices and extract totals.")   # 38 chars
    make_skill(lib, "beta", "parse pdf invoices and extract totals fast.")  # 43 chars
    r = run([BUDGET, "--skills-dir", lib, "--max-chars", "15000"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "2 skills" in r.stdout, r.stdout
    assert "total 114 chars" in r.stdout, "expected 55+59=114:\n%s" % r.stdout


def test_budget_over_budget_exit1(tmp_path):
    lib = str(tmp_path / "lib")
    make_skill(lib, "big", "x" * 200)
    r = run([BUDGET, "--skills-dir", lib, "--max-chars", "100"])
    assert r.returncode == 1, "over budget must exit 1:\n%s" % r.stdout
    assert "OVER BUDGET" in r.stdout


def test_budget_extra_candidate(tmp_path):
    lib = str(tmp_path / "lib")
    make_skill(lib, "one", "abc")
    base = run([BUDGET, "--skills-dir", lib, "--max-chars", "15000"])
    assert base.returncode == 0
    withx = run([BUDGET, "--skills-dir", lib, "--max-chars", "15000", "--extra", "y" * 50])
    assert withx.returncode == 0
    assert "candidate description" in withx.stdout


def test_budget_bom_tolerant(tmp_path):
    """A SKILL.md saved with a UTF-8 BOM (common on Windows editors) must still be counted.

    Regression guard: parse_frontmatter must not be defeated by a leading BOM, otherwise
    the budget silently under-counts and a library can overflow undetected.
    """
    lib = str(tmp_path / "lib")
    make_skill(lib, "withbom", "parse pdf invoices and extract totals.", bom=True)
    r = run([BUDGET, "--skills-dir", lib, "--max-chars", "15000"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 skills" in r.stdout, "BOM'd SKILL.md was dropped (under-count):\n%s" % r.stdout


# ===========================================================================
# 4. dedup_check: flags a known duplicate + --desc candidate mode
# ===========================================================================

def test_dedup_flags_pair(tmp_path):
    lib = str(tmp_path / "lib")
    make_skill(lib, "alpha", "parse pdf invoices and extract totals.")
    make_skill(lib, "beta", "parse pdf invoices and extract totals fast.")
    r = run([DEDUP, "--skills-dir", lib, "--threshold", "0.4"])
    assert r.returncode == 1, "near-duplicate pair must be flagged (exit 1):\n%s" % r.stdout
    assert "alpha" in r.stdout and "beta" in r.stdout


def test_dedup_distinct_ok(tmp_path):
    lib = str(tmp_path / "lib")
    make_skill(lib, "alpha", "parse pdf invoices and extract totals.")
    make_skill(lib, "gamma", "schedule recurring kubernetes cluster backups nightly.")
    r = run([DEDUP, "--skills-dir", lib, "--threshold", "0.4"])
    assert r.returncode == 0, "distinct descriptions must pass:\n%s" % r.stdout


def test_dedup_desc_candidate_mode(tmp_path):
    lib = str(tmp_path / "lib")
    make_skill(lib, "alpha", "parse pdf invoices and extract totals.")
    # candidate nearly identical to alpha -> overlap, exit 1
    r = run([DEDUP, "--skills-dir", lib, "--threshold", "0.4",
             "--desc", "parse pdf invoices and extract totals", "--name", "cand"])
    assert r.returncode == 1, "overlapping candidate must exit 1:\n%s" % r.stdout
    assert "OVERLAP" in r.stdout
    # distinct candidate -> exit 0
    r2 = run([DEDUP, "--skills-dir", lib, "--threshold", "0.4",
              "--desc", "render 3d terrain meshes from gis elevation rasters", "--name", "cand2"])
    assert r2.returncode == 0, "distinct candidate must exit 0:\n%s" % r2.stdout


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
