"""Installed aliases must retain the physical consumer for shared storage resolution."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from make_fixtures import fleet_alias_fixture


@pytest.mark.native
@pytest.mark.parametrize("entry", ["physical", "claude", "agents"])
@pytest.mark.parametrize("different_cwd", [False, True], ids=["relative-entry", "different-cwd"])
def test_installed_entry_resolves_the_physical_companion(tmp_path, entry, different_cwd):
    layout = fleet_alias_fixture(tmp_path, ROOT)
    for name in ("claude", "agents"):
        info = layout["entries"][name].lstat()
        if os.name == "nt":
            assert info.st_reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT
        else:
            assert stat.S_ISLNK(info.st_mode)
    selected = layout["entries"][entry]
    script = selected / "scripts/fleet_check.py" if different_cwd else Path("scripts/fleet_check.py")
    cwd = layout["unrelated"] if different_cwd else selected
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(("GIT_", "SKILL_SMITH_"))}
    env.update(HOME=str(layout["home"]), USERPROFILE=str(layout["home"]), PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run(
        [sys.executable, "-I", "-B", str(layout["probe"]), str(script), str(layout["source_output"])],
        cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    observed = json.loads(result.stdout)
    assert Path(observed["destination"]) == layout["data"] / "synthetic-status.json"
    assert Path(observed["boundary"]) == layout["consumer"] / "guards/tools/data_boundary.py"
    assert observed["refusal"] == "Report DATA cannot be written inside the tool repository"
    assert not layout["source_output"].exists()
    assert list(layout["data"].iterdir()) == []
