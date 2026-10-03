"""Keep scaffolder integration tests on the checked-out local kit revisions."""
import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def local_kits(tmp_path_factory):
    root = Path(__file__).resolve().parents[1]
    mirrors = tmp_path_factory.mktemp("local-kits")
    for folder in ("guards", "style"):
        source = root / folder
        if not (source / ".git").exists():
            pytest.fail(f"Required local kit is missing: {folder}; no network fallback")
        dest = mirrors / folder
        subprocess.run(["git", "clone", "--bare", "--no-hardlinks", str(source), str(dest)],
                       check=True, capture_output=True, timeout=30)
        subprocess.run(["git", "--git-dir", str(dest), "update-ref", "refs/heads/main", "HEAD"],
                       check=True, capture_output=True, timeout=30)
    return mirrors


@pytest.fixture(autouse=True)
def local_kit_transports(monkeypatch, local_kits):
    entries = [("protocol.file.allow", "always")]
    for name, folder in (("fleet-guards", "guards"), ("fleet-style", "style")):
        source = local_kits / folder
        entries.append((f"url.{source.as_uri()}.insteadOf", f"https://github.com/DaizeDong/{name}.git"))
    start = int(os.environ.get("GIT_CONFIG_COUNT", "0"))
    monkeypatch.setenv("GIT_CONFIG_COUNT", str(start + len(entries)))
    monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "file")
    for i, (key, value) in enumerate(entries, start):
        monkeypatch.setenv(f"GIT_CONFIG_KEY_{i}", key)
        monkeypatch.setenv(f"GIT_CONFIG_VALUE_{i}", value)


@pytest.fixture
def private_output(tmp_path, monkeypatch):
    """Exercise writer proofs on generated native Git without network or SSH execution."""
    import importlib.util
    root = Path(__file__).resolve().parents[1]
    scripts = root / "skills/skill-smith/scripts"
    monkeypatch.syspath_prepend(str(root / "tools"))
    monkeypatch.syspath_prepend(str(scripts))
    from make_fixtures import output_proof_fixture

    for key in tuple(os.environ):
        if key.upper().startswith("GIT_") or key.upper() in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}:
            monkeypatch.delenv(key)
    for key in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(key, str(tmp_path / "home"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    value = output_proof_fixture(tmp_path)

    def load(name):
        spec = importlib.util.spec_from_file_location(name + "_native_output", scripts / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    fleet, trim = load("fleet_check"), load("trim_descriptions")
    boundary = fleet._private_output_boundary()
    ssh = [str(value["home"] / ".ssh/config"), str(tmp_path / "ssh_config")]
    monkeypatch.setattr(boundary, "_ssh_config_sources", lambda: {"paths": ssh, "chains": [ssh]})
    value["boundary_loader"] = fleet._private_output_boundary
    monkeypatch.setattr(fleet, "_private_output_boundary", lambda: boundary)
    monkeypatch.setattr(trim, "_storage_module", lambda: fleet)
    native = subprocess.run

    def git(path, *args):
        return native(["git", "-C", str(path), *args], check=True, capture_output=True, text=True)

    def local_only(args, **kwargs):
        assert args[0] == "git", "No SSH, network or external helper may execute"
        return native(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", local_only)
    return {**value, "fleet": fleet, "trim": trim, "git": git}
