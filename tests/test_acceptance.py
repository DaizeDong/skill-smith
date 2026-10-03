"""Contract tests use generated synthetic evidence, never model calls."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/skill-smith/scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tools"))
from make_fixtures import acceptance_bundle, write_json


def gate_module():
    path = SCRIPTS / "acceptance_gate.py"
    assert path.is_file(), "The complete evidence gate must be executable, not just documented"
    spec = importlib.util.spec_from_file_location("acceptance_gate_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def evaluate(tmp_path, mutate=None, stage="local"):
    mod = gate_module()
    candidate = "a" * 64
    policy, manifest, pin = acceptance_bundle(tmp_path, candidate)
    if mutate:
        mutate(policy, manifest, tmp_path)
    return mod.evaluate(tmp_path / "manifest.json", tmp_path / "policy.json", pin, candidate, stage=stage)


def rewrite_gate(manifest, root, gate, change):
    path = root / manifest["gates"][gate]["path"]
    value = json.loads(path.read_text(encoding="utf-8"))
    change(value)
    manifest["gates"][gate]["sha256"] = write_json(path, value)
    write_json(root / "manifest.json", manifest)


def test_complete_generated_bundle_validates_contract_but_is_not_real_acceptance(tmp_path):
    result = evaluate(tmp_path)
    assert result["contract_valid"] is True
    assert result["accepted"] is False
    assert result["verdict"] == "synthetic_only"
    assert result["gates"]["G1"]["mean_lift"] == 0.5
    assert result["gates"]["G2"]["positive_rate"] == 1.0


@pytest.mark.parametrize("gate", ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8"])
def test_missing_required_evidence_never_passes(tmp_path, gate):
    def remove(_policy, manifest, root):
        del manifest["gates"][gate]
        write_json(root / "manifest.json", manifest)
    result = evaluate(tmp_path, remove)
    assert not result["contract_valid"]
    assert not result["accepted"]
    assert result["gates"][gate]["status"] == "missing"


def test_negative_trigger_cases_cannot_be_ignored(tmp_path):
    def mutate(_policy, manifest, root):
        rewrite_gate(manifest, root, "G2", lambda v: [t.update(triggered=True) for t in v["trials"]])
    result = evaluate(tmp_path, mutate)
    assert result["gates"]["G2"]["status"] == "rejected"
    assert not result["contract_valid"]


@pytest.mark.parametrize("change", [
    lambda v: v.update(measurement="extrapolated"),
    lambda v: v.update(candidate_sha256="b" * 64),
    lambda v: v["pairs"][0].update(with_skill=float("nan")),
    lambda v: v.update(pairs=v["pairs"][:1]),
    lambda v: v["pairs"][0].update(input_sha256="c" * 64),
    lambda v: [p.update(with_skill=p["without_skill"]) for p in v["pairs"]],
])
def test_g1_requires_finite_paired_current_measurements(tmp_path, change):
    def mutate(_policy, manifest, root):
        rewrite_gate(manifest, root, "G1", change)
    result = evaluate(tmp_path, mutate)
    assert result["gates"]["G1"]["status"] == "rejected"
    assert not result["contract_valid"]


def test_policy_change_and_artifact_change_are_detected(tmp_path):
    def mutate(policy, manifest, root):
        policy["min_lift"] = -1
        write_json(root / "policy.json", policy)
    result = evaluate(tmp_path, mutate)
    assert result["verdict"] == "invalid_policy"


def test_published_stage_needs_remote_evidence(tmp_path):
    def mutate(_policy, manifest, root):
        del manifest["gates"]["G6b"]
        write_json(root / "manifest.json", manifest)
    result = evaluate(tmp_path, mutate, stage="published")
    assert result["gates"]["G6b"]["status"] == "missing"


def test_stale_artifact_bytes_fail_even_when_manifest_says_pass(tmp_path):
    def mutate(_policy, _manifest, root):
        (root / "G1.json").write_text("{}", encoding="utf-8")
    assert not evaluate(tmp_path, mutate)["contract_valid"]


def test_nonfixture_attestations_need_independent_acceptance(tmp_path):
    def mutate(_policy, manifest, root):
        for gate in manifest["gates"]:
            rewrite_gate(manifest, root, gate, lambda v: v["provenance"].update(fixture=False))
    result = evaluate(tmp_path, mutate)
    assert not result["accepted"] and result["verdict"] == "independent_review_required"
    assert result["contract_valid"]
    assert "attestations" in result["evidence_assurance"]
