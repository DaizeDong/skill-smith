#!/usr/bin/env python3
"""Regression suite for tools/load_budget.py, the PHILOSOPHY P7 always-loaded budget gate.

WHAT THESE TESTS EXIST TO STOP
    The tool shipped knowing one repo shape, skills/<name>/SKILL.md. Two repos in this fleet keep
    their single SKILL.md at the repo ROOT, and those two hold two of the largest always-loaded
    files on the machine. In both of them the tool printed "no SKILL.md found, nothing to measure"
    and returned a code its own docstring called "a state, not a failure". A gate that measures the
    files least in need of measuring, and reports that as a deliberate clean result, is worse than
    no gate: it teaches the reader that the question has been asked and answered.

Run:  python -m pytest -q   (from repo root).  Stdlib + pytest only. No network.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
LB = os.path.join(_REPO, "tools", "load_budget.py")

OVER_BUDGET = 1
NOTHING_MEASURED = 3


def run(args):
    return subprocess.run([sys.executable] + args, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(text.encode("utf-8"))


def plugin_repo(root):
    """A directory that declares itself a skill repo, with no SKILL.md anywhere."""
    write(os.path.join(root, ".claude-plugin", "plugin.json"), '{"name": "demo"}\n')
    return root


def test_tool_exists():
    assert os.path.isfile(LB), LB


def test_root_layout_is_measured(tmp_path):
    """SKILL.md at the repo root is the single-skill layout, and it must be measured."""
    d = str(tmp_path / "rootlayout")
    plugin_repo(d)
    write(os.path.join(d, "SKILL.md"), "---\nname: x\ndescription: y\n---\n" + "word " * 400)
    r = run([LB, d])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "always-loaded" in r.stdout, r.stdout
    # The row is named after the directory holding the SKILL.md, not after "."
    assert "rootlayout" in r.stdout, r.stdout


def test_nested_layout_is_measured(tmp_path):
    d = str(tmp_path / "nested")
    plugin_repo(d)
    write(os.path.join(d, "skills", "demo", "SKILL.md"),
          "---\nname: demo\ndescription: y\n---\n" + "word " * 400)
    r = run([LB, d])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "demo" in r.stdout, r.stdout


def test_both_layouts_in_one_repo_are_measured(tmp_path):
    """Neither layout may shadow the other: the tool discovers both, it does not choose."""
    d = str(tmp_path / "both")
    plugin_repo(d)
    write(os.path.join(d, "SKILL.md"), "---\nname: r\ndescription: y\n---\nroot\n")
    write(os.path.join(d, "skills", "kid", "SKILL.md"), "---\nname: kid\ndescription: y\n---\nkid\n")
    r = run([LB, d])
    assert r.returncode == 0, r.stdout + r.stderr
    rows = [ln for ln in r.stdout.splitlines() if "always-loaded" in ln]
    assert len(rows) == 2, r.stdout


def test_nothing_to_measure_is_a_failure(tmp_path):
    """Finding no SKILL.md in a skill repo is a failure, not a clean result.

    It used to exit on a code the docstring blessed as benign while printing a calm one-liner, so
    the run read as "asked and answered" when nothing had been asked.
    """
    d = plugin_repo(str(tmp_path / "empty"))
    r = run([LB, d])
    assert r.returncode == NOTHING_MEASURED, "expected %d, got %d:\n%s" % (
        NOTHING_MEASURED, r.returncode, r.stdout + r.stderr)
    assert "FAIL" in r.stdout, r.stdout
    assert "measured NOTHING" in r.stdout, r.stdout
    assert "nothing to measure" not in r.stdout.lower(), \
        "the reassuring old wording must not survive:\n%s" % r.stdout


def test_nothing_to_measure_in_a_non_skill_repo_still_fails_and_says_why(tmp_path):
    """A repo that ships no skill at all is a vendoring mistake, not a passing result."""
    d = str(tmp_path / "notaskill")
    write(os.path.join(d, "README.md"), "hello\n")
    r = run([LB, d])
    assert r.returncode == NOTHING_MEASURED, r.stdout + r.stderr
    assert "declares no skill" in r.stdout, r.stdout
    assert "Drop tools/load_budget.py" in r.stdout, r.stdout


def test_duplicated_prose_still_blocks(tmp_path):
    """The gate's actual job: a paragraph living in both SKILL.md and a reference."""
    d = str(tmp_path / "dup")
    plugin_repo(d)
    prose = ("the ratchet only turns one way and a grandfather clause without an expiry date is a "
             "permanent exemption wearing a reassuring name which is the defect this whole file "
             "exists to prevent from recurring quietly in the dark ") * 6
    write(os.path.join(d, "SKILL.md"), "---\nname: d\ndescription: y\n---\n" + prose)
    write(os.path.join(d, "reference", "why.md"), prose)
    r = run([LB, d])
    assert r.returncode == OVER_BUDGET, r.stdout + r.stderr
    assert "BLOCK" in r.stdout, r.stdout


def test_scan_all_covers_both_layouts(tmp_path):
    parent = tmp_path / "fleet"
    a = str(parent / "a")
    b = str(parent / "b")
    plugin_repo(a)
    plugin_repo(b)
    write(os.path.join(a, "SKILL.md"), "---\nname: a\ndescription: y\n---\nalpha\n")
    write(os.path.join(b, "skills", "bee", "SKILL.md"), "---\nname: bee\ndescription: y\n---\nbeta\n")
    r = run([LB, str(parent), "--scan-all"])
    assert r.returncode == 0, r.stdout + r.stderr
    rows = [ln for ln in r.stdout.splitlines() if "always-loaded" in ln]
    assert len(rows) == 2, "--scan-all must see the root layout too:\n%s" % r.stdout


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
