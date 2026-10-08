#!/usr/bin/env python3
"""A-provider signal for the config-bearing standard (config-spec E1-E8, Gate G8).

Verifies scaffold --with-config emits a conformant template, keeps configured G8 pending,
skips non-config skills, and rejects a broken one. Configured lifecycle tests are separate.

Run:  python -m pytest -q
Stdlib + pytest only. No network. Cross-platform.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_REPO, "skills", "skill-smith", "scripts")
sys.path.insert(0, os.path.join(_REPO, "tools"))

from make_fixtures import config_applicability, config_lifecycle, storage_contract_fixture, write_json

SCAFFOLD = os.path.join(_SCRIPTS, "scaffold_skill.py")
CFGCONF = os.path.join(_SCRIPTS, "check_config_conformance.py")
CONFORM = os.path.join(_SCRIPTS, "check_conformance.py")



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
    for rel in ("init_config.py", "verify_config.py", "config_runtime.py", "CONFIG.md.tmpl",
                "readme-config-section.md.tmpl", "readme-config-section.cn.md.tmpl",
                "skill-gitignore.tmpl"):
        p = os.path.join(_REPO, "skills", "skill-smith", "assets", "config", rel)
        assert os.path.isfile(p), "missing config asset: %s" % p


def test_with_config_scaffold_keeps_configured_g8_pending_and_passes_static_g6(tmp_path):
    out = str(tmp_path / "out")
    r = scaffold(out, "cfg-skill", "--with-config")
    assert r.returncode == 0, r.stdout + r.stderr
    repo = os.path.join(out, "cfg-skill")
    # E4 can run immediately; E5 needs independently configured A/B directories.
    g8 = run([CFGCONF, repo, "--run-synthetic"])
    _x = unexpected_failures(g8.stdout)
    assert not _x, "config-bearing template must satisfy executed checks:\n%s" % '\n'.join(_x)
    assert g8.returncode == 2 and "6/8 elements pass" in g8.stdout
    assert "[PASS] E8" in g8.stdout
    assert "configuration_required" in g8.stdout
    # G6: Spec v1 conformance unaffected by the config additions
    g6 = run([CONFORM, repo, "--stage", "draft"])
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
    assert "configuration=none" in g8.stdout


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


def test_g8_rejects_missing_storage_contract(tmp_path):
    repo = config_lifecycle(tmp_path / "storage-skill")
    (repo / "storage.contract.json").unlink()

    g8 = run([CFGCONF, str(repo), "--no-run"])

    assert g8.returncode == 1, g8.stdout + g8.stderr
    assert "[FAIL] E8" in g8.stdout
    assert "storage.contract.json" in g8.stdout


@pytest.mark.parametrize("defect", ["path_escape", "missing_retention_rule"])
def test_g8_rejects_invalid_storage_contract(tmp_path, defect):
    repo = config_lifecycle(tmp_path / "storage-skill")
    contract_path = repo / "storage.contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if defect == "path_escape":
        contract["artifacts"][0]["path_pattern"] = "../escaped.json"
    else:
        del contract["artifacts"][0]["retention_rule"]
    write_json(contract_path, contract)

    g8 = run([CFGCONF, str(repo), "--no-run"])

    assert g8.returncode == 1, g8.stdout + g8.stderr
    assert "[FAIL] E8" in g8.stdout
    assert "[PASS] E8" not in g8.stdout


@pytest.mark.parametrize("malformed", [False, True])
def test_storage_only_tool_validates_e8_without_requiring_settings(tmp_path, malformed):
    repo = storage_contract_fixture(tmp_path)["repo"]
    (repo / "README.md").write_text("Synthetic storage-only source.\n", encoding="utf-8")
    write_json(repo / "config.contract.json", config_applicability("runtime-storage-only"))
    if malformed:
        contract_path = repo / "storage.contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["schema_version"] = "1"
        write_json(contract_path, contract)

    g8 = run([CFGCONF, str(repo), "--no-run"])

    assert g8.returncode == (1 if malformed else 0), g8.stdout + g8.stderr
    assert "[NOT_APPLICABLE] E1 " in g8.stdout
    assert "[FAIL] E1" not in g8.stdout
    assert ("[FAIL] E8" if malformed else "[PASS] E8") in g8.stdout


def test_dangling_storage_contract_does_not_skip_g8(tmp_path):
    contract_path = tmp_path / "storage.contract.json"
    try:
        contract_path.symlink_to(tmp_path / "missing-contract.json")
    except OSError as exc:
        pytest.skip("File symlinks are unavailable: " + str(exc))

    g8 = run([CFGCONF, str(tmp_path), "--no-run"])

    assert g8.returncode == 1, g8.stdout + g8.stderr
    assert "NOT config-bearing" not in g8.stdout
    assert "[FAIL] E8" in g8.stdout


def test_init_deterministic_and_self_contained(tmp_path):
    """Emitted init: two inits are byte-identical (E4) and leak no absolute paths (E5)."""
    result = scaffold(str(tmp_path / "out"), "demo", "--with-config")
    assert result.returncode == 0, result.stdout + result.stderr
    initializer = str(tmp_path / "out/demo/scripts/init_config.py")
    a = str(tmp_path / "A")
    b = str(tmp_path / "B")
    r1 = run([initializer, "--skill", "demo", "--out", a])
    r2 = run([initializer, "--skill", "demo", "--out", b])
    assert r1.returncode == 0 and r2.returncode == 0, r1.stdout + r2.stdout
    reg_a = open(os.path.join(a, "registry.json"), encoding="utf-8").read()
    reg_b = open(os.path.join(b, "registry.json"), encoding="utf-8").read()
    assert reg_a == reg_b, "init must be deterministic (E4)"
    for bad in ("C:\\", "/home/", "/Users/", a, b):
        assert bad not in reg_a, "config must be self-contained, leaked: %r (E5)" % bad

    spec = importlib.util.spec_from_file_location("config_storage_contract", Path(_SCRIPTS) / "storage_contract.py")
    storage = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(storage)
    contract = storage.validate_contract(tmp_path / "out/demo")
    generated = [path.relative_to(Path(a)).as_posix() for path in Path(a).rglob("*") if path.is_file()]
    for relative in generated + ["tools/example/claude.json.template", "tools/example/env.template"]:
        assert len(storage.owners(contract, relative)) == 1, "generated or required config path is undeclared: " + relative


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
