"""Generated native regressions for initializer aliases and literal GitHub SSH policy."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import make_fixtures as fixtures


def native_git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                          text=True, timeout=30)


@pytest.fixture
def isolated_metadata(tmp_path, monkeypatch):
    for key in tuple(os.environ):
        if key.upper().startswith(("GIT_", "ACME_FIXTURE_")):
            monkeypatch.delenv(key)
    for key in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(key, str(tmp_path / "home"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("PYTHONUTF8", "1")


@pytest.fixture
def config_case(tmp_path, isolated_metadata):
    assets = ROOT / "skills/skill-smith/assets/config"
    resolver = (ROOT / "guards/tools/datadir.py").read_text(encoding="utf-8")
    layout = fixtures.review20_config_layout(tmp_path, assets, resolver)
    native_git(layout["dest"], "read-tree", "HEAD")
    native_git(layout["root"], "update-index", "--add", "--cacheinfo",
               "160000," + layout["revision"] + ",guards")
    return layout


def run_initializer(layout, selected, force):
    args = [sys.executable, "-B", "-X", "utf8", str(layout["initializer"]), "--out", str(selected)]
    if force:
        args.append("--force")
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=30)


@pytest.mark.native
@pytest.mark.parametrize("force", [False, True])
def test_initializer_preserves_an_ordinary_existing_file_without_force(config_case, force):
    destination = fixtures.review20_config_destination(config_case, "ordinary")
    result = run_initializer(config_case, destination["root"], force)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (destination["target"].read_bytes() == config_case["sentinel"]) is not force
    assert destination["outside"].read_bytes() == config_case["sentinel"]
    assert all((destination["root"] / relative).is_file() for relative in config_case["generated"])


@pytest.mark.native
@pytest.mark.parametrize("relative", ["registry.json", ".gitignore", "secrets/README.md"])
@pytest.mark.parametrize("force", [False, True])
def test_initializer_rejects_hardlink_before_any_generated_write(config_case, relative, force):
    destination = fixtures.review20_config_destination(config_case, relative)
    result = run_initializer(config_case, destination["root"], force)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "hardlink" in result.stdout.lower()
    assert destination["outside"].read_bytes() == config_case["sentinel"]
    assert destination["target"].read_bytes() == config_case["sentinel"]
    assert all(not (destination["root"] / item).exists()
               for item in config_case["generated"] if item != relative)


@pytest.mark.parametrize("operation", ["fsync", "replace"])
def test_initializer_write_failure_preserves_existing_bytes(config_case, monkeypatch, operation):
    destination = fixtures.review20_config_destination(config_case, "ordinary")
    monkeypatch.syspath_prepend(str(ROOT / "skills/skill-smith/assets/config"))
    spec = importlib.util.spec_from_file_location("review20_initializer", config_case["initializer"])
    initializer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(initializer)

    def failed(*args, **kwargs):
        raise OSError("Generated durable write failure")

    monkeypatch.setattr(initializer.os, operation, failed)
    with pytest.raises(OSError, match="Generated durable write failure"):
        initializer.write(destination["target"], config_case["replacement"], True)
    assert destination["target"].read_bytes() == config_case["sentinel"]
    assert not list(destination["root"].glob(".init-config-*"))


@pytest.fixture
def fleet():
    spec = importlib.util.spec_from_file_location("review20_fleet", ROOT / "skills/skill-smith/scripts/fleet_check.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@pytest.mark.native
@pytest.mark.parametrize("url_form", ["scp", "ssh"])
@pytest.mark.parametrize("name,config,accepted", fixtures.review20_ssh_configs())
def test_native_inventory_applies_literal_github_ssh_configuration(
        tmp_path, monkeypatch, isolated_metadata, fleet, name, config, accepted, url_form):
    layout = fixtures.review20_inventory_layout(tmp_path, config, url_form=url_form)
    for key in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(key, str(layout["home"]))
    native_git(layout["repository"], "init", "-q")
    native_git(layout["repository"], "remote", "add", "origin", layout["url"])
    problems = []
    result = fleet.repo_slugs({"synthetic-tool": str(layout["repository"])}, problems=problems)
    assert result == ({layout["slug"]: str(layout["repository"])} if accepted else {}), name
    assert bool(problems) is not accepted
    if problems:
        assert "unverified origin identity" in problems[0][1]


def test_https_identity_does_not_use_ssh_configuration(tmp_path, monkeypatch, isolated_metadata, fleet):
    config = next(row[1] for row in fixtures.review20_ssh_configs() if row[0] == "rewritten")
    layout = fixtures.review20_inventory_layout(tmp_path, config, url_form="https")
    monkeypatch.setenv("HOME", str(layout["home"]))
    monkeypatch.setenv("USERPROFILE", str(layout["home"]))
    assert fleet.slug_from_url(layout["url"]) == layout["slug"]
