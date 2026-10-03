"""Actual emitted config lifecycle, with generated ordinary and linked worktrees."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from make_fixtures import config_cold_start, config_companion, config_legacy_decoy, conformance_scanner

_CONSUMERS = {}


@pytest.fixture(params=["ordinary", "linked"])
def consumer(request, tmp_path_factory, local_kit_transports):
    if request.param not in _CONSUMERS:
        _CONSUMERS[request.param] = config_cold_start(tmp_path_factory.mktemp("cold-start"), request.param)
    return _CONSUMERS[request.param]


@pytest.fixture
def config_env(tmp_path):
    home = tmp_path / "isolated home"
    home.mkdir()
    env = {key: value for key, value in os.environ.items() if not key.startswith("ACME_COLD_TOOL_")}
    env.update(HOME=str(home), USERPROFILE=str(home))
    return env


def invoke(consumer, script, env, *args, caller="caller"):
    return subprocess.run([sys.executable, str(consumer["consumer"] / "scripts" / script), *args],
                          cwd=consumer[caller], env=env, capture_output=True, text=True,
                          encoding="utf-8", timeout=60)


@pytest.mark.parametrize("caller", ["consumer", "caller"])
def test_default_doctor_finds_proven_sibling(consumer, config_env, caller):
    result = invoke(consumer, "verify_config.py", config_env, caller=caller)
    assert result.returncode == 0, result.stdout + result.stderr
    assert str(consumer["companion"]) in result.stdout
    assert "synthetic-decoy" not in result.stdout


def test_default_init_preserves_selected_sibling_and_does_not_create_home_copy(consumer, config_env):
    registry = consumer["companion"] / "registry.json"
    before = registry.read_bytes()
    result = invoke(consumer, "init_config.py", config_env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert str(consumer["companion"]) in result.stdout
    assert registry.read_bytes() == before
    assert list(Path(config_env["HOME"]).iterdir()) == []


def test_explicit_primary_alias_and_cli_switching(consumer, config_env, tmp_path):
    roots = [config_companion(tmp_path / label, label=label) for label in ("config A", "config B", "config C")]
    config_env.update(ACME_COLD_TOOL_CONFIG=str(roots[0]), ACME_COLD_TOOL_CONFIG_DIR=str(roots[1]))
    for script in ("init_config.py", "verify_config.py"):
        result = invoke(consumer, script, config_env)
        assert result.returncode == 0, result.stdout + result.stderr
        assert str(roots[0]) in result.stdout
    config_env.pop("ACME_COLD_TOOL_CONFIG")
    result = invoke(consumer, "verify_config.py", config_env)
    assert result.returncode == 0 and str(roots[1]) in result.stdout
    result = invoke(consumer, "verify_config.py", config_env, "--config-dir", str(roots[2]))
    assert result.returncode == 0 and str(roots[2]) in result.stdout


def test_missing_explicit_config_cannot_fall_through_to_sibling(consumer, config_env, tmp_path):
    config_env["ACME_COLD_TOOL_CONFIG"] = str(tmp_path / "missing config")
    result = invoke(consumer, "verify_config.py", config_env)
    assert result.returncode != 0


def test_unproven_sibling_is_a_failure(consumer, config_env):
    marker = consumer["companion"] / ".companion"
    original = marker.read_bytes()
    marker.unlink()
    try:
        for script in ("init_config.py", "verify_config.py"):
            result = invoke(consumer, script, config_env)
            assert result.returncode != 0, result.stdout + result.stderr
        assert list(Path(config_env["HOME"]).iterdir()) == []
    finally:
        marker.write_bytes(original)


def test_consumer_boundary_applies_in_linked_worktrees_too(consumer, config_env):
    inside = config_companion(consumer["consumer"] / "synthetic forbidden config")
    config_env["ACME_COLD_TOOL_CONFIG"] = str(inside)
    for script in ("init_config.py", "verify_config.py"):
        result = invoke(consumer, script, config_env)
        assert result.returncode != 0, result.stdout + result.stderr


def test_missing_pinned_resolver_never_uses_legacy_helper(consumer, config_env):
    resolver = consumer["consumer"] / "guards/tools/datadir.py"
    original = resolver.read_bytes()
    legacy = config_legacy_decoy(consumer["consumer"], consumer["companion"])
    resolver.unlink()
    config_env["ACME_COLD_TOOL_CONFIG"] = str(consumer["companion"])
    try:
        for script in ("init_config.py", "verify_config.py"):
            result = invoke(consumer, script, config_env)
            assert result.returncode != 0, result.stdout + result.stderr
    finally:
        resolver.write_bytes(original)
        legacy.unlink()


CHECKER = Path(__file__).resolve().parents[1] / "skills/skill-smith/scripts/check_conformance.py"


def test_checker_help_has_no_fake_repo_failures():
    result = subprocess.run([sys.executable, str(CHECKER), "--help"],
                            capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "usage:" in result.stdout.lower() and "repo" in result.stdout.lower()
    assert "[FAIL]" not in result.stdout and "conformance:" not in result.stdout


@pytest.mark.parametrize("case", ["clean", "warn_stdout", "warn_stderr", "cross_repo", "history_debt",
                                 "failure_stdout", "failure_empty"])
def test_checker_preserves_scanner_severity_and_diagnostics(consumer, config_env, case):
    scanner = consumer["consumer"] / "guards/tools/pii_guard.py"
    original = scanner.read_bytes()
    try:
        fixture = conformance_scanner(consumer["consumer"], case)
        result = subprocess.run([sys.executable, str(CHECKER), str(consumer["consumer"])],
                                env=config_env, capture_output=True, text=True, encoding="utf-8", timeout=60)
        rows = [line for line in result.stdout.splitlines()
                if "PII gate:" in line and "(tree + history)" in line]
        assert len(rows) == 1, result.stdout + result.stderr
        row = rows[0]
        if fixture["exit_code"]:
            assert "[FAIL]" in row and result.returncode != 0
            assert str(fixture["exit_code"]) in row
        elif case == "clean":
            assert "[PASS]" in row
        else:
            assert "[WARN]" in row and "clean" not in row.lower()
            assert "WARN" in result.stdout.splitlines()[-1]
        if case != "clean":
            for detail in (fixture["stdout"], fixture["stderr"]):
                if detail:
                    assert detail in result.stdout
    finally:
        scanner.write_bytes(original)
