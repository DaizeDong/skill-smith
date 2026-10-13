"""Default fleet report discovery through the real pinned resolver."""
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from make_fixtures import fleet_writer_layout

spec = importlib.util.spec_from_file_location("fleet_writer_test", ROOT / "skills/skill-smith/scripts/fleet_check.py")
fc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fc)


@pytest.fixture(params=["ordinary", "linked"])
def layout(request, tmp_path, monkeypatch, private_output):
    value = fleet_writer_layout(tmp_path / "writer", request.param)
    monkeypatch.setattr(fc, "HERE", str(value["scripts"]))
    monkeypatch.setenv("HOME", str(value["home"]))
    monkeypatch.setenv("USERPROFILE", str(value["home"]))
    for name in ("SKILL_SMITH_CONFIG", "SKILL_SMITH_CONFIG_DIR", "SKILL_SMITH_DATA_DIR"):
        monkeypatch.delenv(name, raising=False)
    return value


def test_default_report_finds_private_sibling_without_writing(layout):
    path = fc.resolve_status_path(None)
    assert Path(path) == layout["companion"] / "data/fleet-check-status.json"
    assert not Path(path).exists()


def test_consumer_data_override_cannot_use_sibling_as_fallback(layout, monkeypatch):
    forbidden = layout["consumer"] / "data"
    forbidden.mkdir()
    monkeypatch.setenv("SKILL_SMITH_DATA_DIR", str(forbidden))
    with pytest.raises((ValueError, RuntimeError), match="(?i)inside|repository"):
        fc.resolve_status_path(None)
    assert not (forbidden / "fleet-check-status.json").exists()
