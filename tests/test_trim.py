#!/usr/bin/env python3
"""Tests for trim_descriptions.py — library description-budget remediation.

Verifies scan/apply roundtrip with backups, and that --dry-run never modifies files.
Stdlib + pytest only. No network. Isolated via tmp_path + --backup-dir.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
TRIM = os.path.join(_REPO, "skills", "skill-smith", "scripts", "trim_descriptions.py")


def run(args):
    return subprocess.run(
        [sys.executable, TRIM] + args,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )


def mkskill(libdir, name, desc):
    d = os.path.join(libdir, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("---\nname: %s\ndescription: %s\n---\nbody\n" % (name, desc))


def read(libdir, name):
    with open(os.path.join(libdir, name, "SKILL.md"), encoding="utf-8") as f:
        return f.read()


def test_scan_finds_only_over_cap(tmp_path):
    lib = str(tmp_path / "skills")
    os.makedirs(lib)
    mkskill(lib, "big", "X" * 200)
    mkskill(lib, "small", "short")
    wl = str(tmp_path / "wl.json")
    r = run(["--scan", "--skills-dir", lib, "--cap", "50", "--out", wl])
    assert r.returncode == 0, r.stderr
    rows = json.load(open(wl, encoding="utf-8"))
    names = [x["name"] for x in rows]
    assert "big" in names and "small" not in names
    assert rows[0]["old_len"] == 200


def test_apply_roundtrip_with_backup(tmp_path):
    lib = str(tmp_path / "skills")
    os.makedirs(lib)
    mkskill(lib, "big", "X" * 200)
    wl = str(tmp_path / "wl.json")
    run(["--scan", "--skills-dir", lib, "--cap", "50", "--out", wl])
    rows = json.load(open(wl, encoding="utf-8"))
    rows[0]["new"] = "trimmed desc"
    json.dump(rows, open(wl, "w", encoding="utf-8"))
    bak = str(tmp_path / "bak")
    r = run(["--apply", wl, "--backup-dir", bak])
    assert r.returncode == 0, r.stderr
    txt = read(lib, "big")
    assert "description: trimmed desc" in txt
    assert "X" * 200 not in txt
    assert any(os.path.isfile(os.path.join(dp, fn)) for dp, _, fns in os.walk(bak) for fn in fns), "backup missing"


def test_dry_run_does_not_modify(tmp_path):
    lib = str(tmp_path / "skills")
    os.makedirs(lib)
    mkskill(lib, "big", "X" * 200)
    wl = str(tmp_path / "wl.json")
    run(["--scan", "--skills-dir", lib, "--cap", "50", "--out", wl])
    rows = json.load(open(wl, encoding="utf-8"))
    rows[0]["new"] = "new short"
    json.dump(rows, open(wl, "w", encoding="utf-8"))
    before = read(lib, "big")
    r = run(["--apply", wl, "--dry-run"])
    assert r.returncode == 0, r.stderr
    assert read(lib, "big") == before


def test_changed_since_scan_is_skipped(tmp_path):
    lib = str(tmp_path / "skills")
    os.makedirs(lib)
    mkskill(lib, "big", "X" * 200)
    wl = str(tmp_path / "wl.json")
    run(["--scan", "--skills-dir", lib, "--cap", "50", "--out", wl])
    rows = json.load(open(wl, encoding="utf-8"))
    rows[0]["new"] = "trimmed"
    json.dump(rows, open(wl, "w", encoding="utf-8"))
    mkskill(lib, "big", "Y" * 200)  # mutate after scan
    bak = str(tmp_path / "bak")
    r = run(["--apply", wl, "--backup-dir", bak])
    assert r.returncode == 0, r.stderr
    assert "Y" * 200 in read(lib, "big")  # untouched because it changed since scan
    assert "skipped" in r.stdout.lower()
