"""The shared proof API replaces the legacy consumer publication helpers."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from make_fixtures import materialize_review13_repositories


@pytest.fixture
def publication(private_output):
    return private_output, materialize_review13_repositories(private_output)


def test_private_proof_covers_every_native_fetch_and_push_destination(publication):
    layout, case = publication
    target = layout["data"] / "fleet-check-status.json"
    path, proof = layout["fleet"].resolve_status_path(str(target), str(layout["visibility"]))
    assert path == str(target)
    assert Path(proof.root) == layout["private"]
    assert proof.repositories == tuple(case["identities"])
    assert proof.signature
    assert not target.exists()


@pytest.mark.parametrize("index", range(3))
@pytest.mark.parametrize("visibility", ["PUBLIC", "UNKNOWN"])
def test_nonprivate_receipt_refuses_each_native_destination(publication, index, visibility):
    layout, case = publication
    states = json.loads(layout["visibility"].read_text(encoding="utf-8"))
    states[case["identities"][index]] = visibility
    layout["visibility"].write_text(json.dumps(states), encoding="utf-8")
    target = layout["data"] / "reports/status.json"
    with pytest.raises(ValueError, match="PRIVATE"):
        layout["fleet"].resolve_status_path(str(target), str(layout["visibility"]))
    assert not target.parent.exists()


@pytest.mark.parametrize("offline", [False, True])
def test_legacy_inventory_arguments_cannot_override_writer_proof(publication, offline):
    layout, _case = publication
    layout["git"](layout["private"], "remote", "set-url", "origin", layout["bad_origins"][0])
    oracle = SimpleNamespace(visibility=lambda slug: ("PRIVATE", "synthetic inventory"))
    target = layout["data"] / "reports/status.json"
    with pytest.raises(ValueError, match="PRIVATE"):
        layout["fleet"].resolve_status_path(str(target), str(layout["visibility"]), offline, oracle)
    assert not target.parent.exists()


def test_shared_verifier_failure_propagates_without_compatibility_retry(publication, monkeypatch):
    layout, case = publication
    fleet = layout["fleet"]
    boundary = fleet._private_output_boundary()
    calls = []

    def failed(*args, **kwargs):
        calls.append((args, kwargs))
        raise boundary.GitError(case["helper_failure"])

    monkeypatch.setattr(boundary, "prove_private_companion", failed)
    with pytest.raises(ValueError, match=case["helper_failure"]):
        fleet.resolve_status_path(str(layout["data"] / "status.json"), str(layout["visibility"]))
    assert len(calls) == 1
