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
