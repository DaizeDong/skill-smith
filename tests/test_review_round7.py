"""Default fleet report discovery through the real pinned resolver."""
import importlib.util
import json
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
    boundary = private_output["fleet"]._private_output_boundary()
    storage = private_output["fleet"]._artifact_storage()
    monkeypatch.setattr(fc, "HERE", str(value["scripts"]))
    monkeypatch.setattr(fc, "_artifact_storage", lambda: storage)
    monkeypatch.setattr(fc, "_private_output_boundary", lambda: boundary)
    monkeypatch.setenv("HOME", str(value["home"]))
    monkeypatch.setenv("USERPROFILE", str(value["home"]))
    for name in ("SKILL_SMITH_CONFIG", "SKILL_SMITH_CONFIG_DIR", "SKILL_SMITH_DATA_DIR"):
        monkeypatch.delenv(name, raising=False)
    return value


def test_default_report_finds_private_sibling_without_writing(layout):
    path, proof = fc.resolve_status_path(None, str(layout["visibility"]), True)
    assert Path(path) == layout["companion"] / "data/fleet-check-status.json"
    assert proof.repositories == ("acmecorp/skill-smith-config",)
    assert not Path(path).exists()


def test_explicit_undeclared_private_report_is_refused(layout):
    expected = layout["companion"] / "data/custom.json"
    with pytest.raises(ValueError, match="undeclared"):
        fc.resolve_status_path(str(expected), str(layout["visibility"]), True)
    assert not expected.exists()


@pytest.mark.parametrize("visibility", ["PUBLIC", "UNKNOWN"])
def test_discovered_sibling_still_requires_private_visibility(layout, visibility):
    cache = json.loads(layout["visibility"].read_text(encoding="utf-8"))
    cache["AcmeCorp/skill-smith-config"] = visibility
    layout["visibility"].write_text(json.dumps(cache), encoding="utf-8")
    with pytest.raises(ValueError, match="PRIVATE"):
        fc.resolve_status_path(None, str(layout["visibility"]), True)
    assert not (layout["companion"] / "data/fleet-check-status.json").exists()


def test_consumer_data_override_cannot_use_sibling_as_fallback(layout, monkeypatch):
    forbidden = layout["consumer"] / "data"
    forbidden.mkdir()
    monkeypatch.setenv("SKILL_SMITH_DATA_DIR", str(forbidden))
    with pytest.raises((ValueError, RuntimeError), match="(?i)inside|repository"):
        fc.resolve_status_path(None, str(layout["visibility"]), True)
    assert not (forbidden / "fleet-check-status.json").exists()
