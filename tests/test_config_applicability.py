"""Explicit applicability cannot be inferred from settings-like prose or silence."""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from make_fixtures import (config_classifier_fixture, config_lifecycle, powershell_config_lifecycle,
                           private_config_lifecycle, review15_doctor_layout, write_json)

CHECKER = Path(__file__).resolve().parents[1] / "skills/skill-smith/scripts/check_config_conformance.py"


@pytest.mark.parametrize("kind", ["skill", "software", "combined"])
def test_declared_storage_only_ignores_settings_words(tmp_path, kind):
    source = config_classifier_fixture(tmp_path / "source", "runtime-storage-only", repository_kind=kind)
    result = subprocess.run([sys.executable, str(CHECKER), str(source), "--no-run"],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[NOT_APPLICABLE] E1" in result.stdout
    assert "[PASS] E8" in result.stdout


def test_declared_settings_missing_native_lifecycle_cannot_be_storage_only(tmp_path):
    source = config_classifier_fixture(tmp_path / "source", "settings")
    result = subprocess.run([sys.executable, str(CHECKER), str(source), "--no-run"],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "[FAIL] E3" in result.stdout
    assert "NOT_APPLICABLE" not in result.stdout


def test_missing_applicability_is_unknown_and_keeps_all_rows(tmp_path):
    source = config_classifier_fixture(tmp_path / "source", None)
    result = subprocess.run([sys.executable, str(CHECKER), str(source), "--no-run"],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "UNKNOWN" in result.stdout
    for number in range(1, 9):
        assert f"E{number} " in result.stdout


def test_native_doctor_ready_for_blank_required_fields_is_rejected(tmp_path):
    source = config_lifecycle(tmp_path / "source", doctor_mode="ready_when_blank")
    result = subprocess.run([sys.executable, str(CHECKER), str(source), "--run-synthetic"],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "[FAIL] E3" in result.stdout
    assert "[PASS] E4" in result.stdout


def test_exit_zero_without_ready_does_not_prove_configured_switch(tmp_path):
    layout = review15_doctor_layout(tmp_path)
    config_lifecycle(layout["tool"], doctor_mode="schema_only")
    result = subprocess.run([sys.executable, str(CHECKER), str(layout["tool"]), "--run-synthetic",
                             "--config-a", str(layout["configs"][0]), "--config-b", str(layout["configs"][1]),
                             "--synthetic-root", str(tmp_path)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "[PASS] E3" in result.stdout and "[FAIL] E5" in result.stdout


def test_native_configuration_paths_do_not_require_generic_registry_names(tmp_path):
    source = config_lifecycle(tmp_path / "source")
    import json
    declaration = json.loads((source / "config.contract.json").read_text(encoding="utf-8"))
    for key, new_name in (("initializer", "native_setup.py"), ("doctor", "native_doctor.py")):
        previous = source / declaration["settings"][key]["path"]
        previous.rename(previous.with_name(new_name))
        declaration["settings"][key]["path"] = "scripts/" + new_name
    write_json(source / "config.contract.json", declaration)
    result = subprocess.run([sys.executable, str(CHECKER), str(source), "--run-synthetic"],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "[PASS] E3" in result.stdout and "[PASS] E4" in result.stdout


def test_native_json_doctor_can_report_identical_root_aliases(tmp_path):
    layout = review15_doctor_layout(tmp_path)
    config_lifecycle(layout["tool"], doctor_mode="json")
    result = subprocess.run([sys.executable, str(CHECKER), str(layout["tool"]), "--run-synthetic",
                             "--config-a", str(layout["configs"][0]), "--config-b", str(layout["configs"][1]),
                             "--synthetic-root", str(tmp_path)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[PASS] E3" in result.stdout and "[PASS] E5" in result.stdout


def test_native_powershell_initializer_is_supported(tmp_path):
    import shutil
    if not (shutil.which("pwsh") or shutil.which("powershell")):
        pytest.skip("Native PowerShell interpreter is unavailable")
    source = powershell_config_lifecycle(tmp_path / "source")
    result = subprocess.run([sys.executable, str(CHECKER), str(source), "--run-synthetic"],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "[PASS] E3" in result.stdout and "[PASS] E4" in result.stdout


@pytest.mark.parametrize("visibility", ["PRIVATE", "PUBLIC", "UNKNOWN"])
def test_native_initializer_retains_private_admission_with_prepared_fixtures(tmp_path, visibility):
    layout = private_config_lifecycle(tmp_path, visibility=visibility)
    command = [sys.executable, str(CHECKER), str(layout["source"]), "--run-synthetic",
               "--synthetic-root", str(tmp_path), "--synthetic-home", str(layout["home"])]
    for flag, key in (("--template-a", "template-a"), ("--template-b", "template-b"),
                      ("--config-a", "configured-a"), ("--config-b", "configured-b")):
        command.extend((flag, str(layout[key])))
    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    if visibility == "PRIVATE":
        assert result.returncode == 0, result.stdout + result.stderr
        assert all(f"[PASS] E{number}" in result.stdout for number in (3, 4, 5))
    else:
        assert result.returncode == 1, result.stdout + result.stderr
        assert "[FAIL] E4" in result.stdout
        assert not (layout["template-a"] / "registry.json").exists()
        assert not (layout["template-b"] / "registry.json").exists()
