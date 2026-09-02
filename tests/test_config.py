#!/usr/bin/env python3
"""A-provider signal for the config-bearing standard (config-spec E1-E7, Gate G8).

Verifies scaffold --with-config emits a conformant config-bearing skill, the G8 gate accepts it,
skips non-config skills, and rejects a broken one. Mirrors test_tools.py conventions.

Run:  python -m pytest -q
Stdlib + pytest only. No network. Cross-platform.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_REPO, "skills", "skill-smith", "scripts")

SCAFFOLD = os.path.join(_SCRIPTS, "scaffold_skill.py")
CFGCONF = os.path.join(_SCRIPTS, "check_config_conformance.py")
CONFORM = os.path.join(_SCRIPTS, "check_conformance.py")
INIT_ASSET = os.path.join(_REPO, "skills", "skill-smith", "assets", "config", "init_config.py")



# A freshly scaffolded repo is NOT green on one item, on purpose: .dataclass.json ships with an
# empty "data" list and no "_audited" key, and the boundary check fails that state because an
# empty declaration is only an answer if somebody looked. Where a skill writes is not knowable
# before the skill has run, so a scaffolder that pre-filled the key would be asserting, on the
# author behalf, exactly the thing the key exists to make somebody check.
NEEDS_A_HUMAN = ("data boundary: repo is an uninitialized tool",)


def unexpected_failures(stdout):
    """FAIL lines that are not one of the known-and-required-open items."""
    return [ln for ln in stdout.splitlines()
            if "[FAIL]" in ln and not any(k in ln for k in NEEDS_A_HUMAN)]

def run(args, env=None, cwd=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run([sys.executable] + args, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120, env=e, cwd=cwd)


def scaffold(out, name, *extra):
    return run([SCAFFOLD, name, "--description", "When user wants %s, do it." % name,
                "--out-dir", out, *extra])


def test_config_assets_present():
    for rel in ("init_config.py", "verify_config.py", "CONFIG.md.tmpl",
                "readme-config-section.md.tmpl", "readme-config-section.cn.md.tmpl",
                "skill-gitignore.tmpl"):
        p = os.path.join(_REPO, "skills", "skill-smith", "assets", "config", rel)
        assert os.path.isfile(p), "missing config asset: %s" % p


def test_with_config_scaffold_passes_g8_and_g6(tmp_path):
    out = str(tmp_path / "out")
    r = scaffold(out, "cfg-skill", "--with-config")
    assert r.returncode == 0, r.stdout + r.stderr
    repo = os.path.join(out, "cfg-skill")
    # G8: full dynamic run (init x2 determinism + hot-swap) must accept
    g8 = run([CFGCONF, repo])
    _x = unexpected_failures(g8.stdout)
    assert not _x, "config-bearing scaffold must pass G8:\n%s" % '\n'.join(_x)
    assert "7/7 elements pass" in g8.stdout
    # G6: Spec v1 conformance unaffected by the config additions
    g6 = run([CONFORM, repo])
    _x = unexpected_failures(g6.stdout)
    assert not _x, "must remain Spec-v1 conformant, and not merely the audit key:\n%s" % '\n'.join(_x)
    assert any(k in g6.stdout for k in NEEDS_A_HUMAN), g6.stdout


def test_plain_scaffold_is_not_config_bearing(tmp_path):
    out = str(tmp_path / "out")
    r = scaffold(out, "plain-skill")  # no --with-config
    assert r.returncode == 0, r.stdout + r.stderr
    repo = os.path.join(out, "plain-skill")
    g8 = run([CFGCONF, repo])
    assert g8.returncode == 0, "non-config skill must pass vacuously:\n%s" % g8.stdout
    assert "NOT config-bearing" in g8.stdout


def test_g8_rejects_missing_secrets_gate(tmp_path):
    out = str(tmp_path / "out")
    r = scaffold(out, "leaky-skill", "--with-config")
    assert r.returncode == 0
    repo = os.path.join(out, "leaky-skill")
    os.remove(os.path.join(repo, ".gitignore"))  # break E6
    g8 = run([CFGCONF, repo, "--no-run"])
    assert g8.returncode == 1, "missing secrets gate must REJECT:\n%s" % g8.stdout
    assert "E6" in g8.stdout and "REJECT" in g8.stdout


def test_g8_rejects_missing_verify_script(tmp_path):
    out = str(tmp_path / "out")
    r = scaffold(out, "halfcfg-skill", "--with-config")
    assert r.returncode == 0
    repo = os.path.join(out, "halfcfg-skill")
    os.remove(os.path.join(repo, "scripts", "verify_config.py"))  # break E3
    g8 = run([CFGCONF, repo])
    assert g8.returncode == 1, "missing verify script must REJECT:\n%s" % g8.stdout
    assert "E3" in g8.stdout


def test_init_deterministic_and_self_contained(tmp_path):
    """Generic init asset: two inits are byte-identical (E4) and leak no absolute paths (E5)."""
    a = str(tmp_path / "A")
    b = str(tmp_path / "B")
    r1 = run([INIT_ASSET, "--skill", "demo", "--out", a])
    r2 = run([INIT_ASSET, "--skill", "demo", "--out", b])
    assert r1.returncode == 0 and r2.returncode == 0, r1.stdout + r2.stdout
    reg_a = open(os.path.join(a, "registry.json"), encoding="utf-8").read()
    reg_b = open(os.path.join(b, "registry.json"), encoding="utf-8").read()
    assert reg_a == reg_b, "init must be deterministic (E4)"
    for bad in ("C:\\", "/home/", "/Users/", a, b):
        assert bad not in reg_a, "config must be self-contained, leaked: %r (E5)" % bad


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
