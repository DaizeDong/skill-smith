"""Exercise bounded batch retirement using generated data and real native deletion.

Plans, hashes, path boundaries, the frozen source contract and Windows
Remove-Item are real. Pure path planning tests separately substitute bounded
snapshot metadata. Timing evidence describes this synthetic workload and has no
machine-speed gate.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/skill-smith/scripts"))
sys.path.insert(0, str(ROOT / "tools"))
import storage_contract as storage
from make_fixtures import storage_contract_fixture, write_json

@pytest.fixture
def batch_layout(tmp_path):
    value = storage_contract_fixture(tmp_path)
    value["temporary_root"] = tmp_path
    return value


def generated_leaves(layout, names):
    paths = []
    for name in names:
        relative = "retired/batch/" + name
        target = layout["companion"] / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(layout["sentinel"])
        paths.append(relative)
    return paths


def approved_plan(layout, paths, filename="approved-plan.json"):
    plan = storage.create_plan(layout["repo"], layout["companion"], paths,
                               "Reviewed generated telemetry", "Synthetic writer was never started")
    path = layout["temporary_root"] / filename
    write_json(path, plan)
    return path, hashlib.sha256(path.read_bytes()).hexdigest(), plan


def stub_snapshot(layout, monkeypatch):
    calls = []
    payload = layout["sentinel"]

    def snapshot(contract, root, path):
        calls.append(path)
        return [{"path": path, "type": "file", "bytes": len(payload), "mtime_ns": 0,
                 "sha256": hashlib.sha256(payload).hexdigest()}]

    monkeypatch.setattr(storage, "retirement_rows", snapshot)
    return calls


def legacy_pairwise_overlap(paths):
    """The previous planning predicate, retained only as a measured comparison."""
    clean = sorted(set(paths))
    return any(right.startswith(left + "/") for i, left in enumerate(clean) for right in clean[i + 1:])


@pytest.mark.parametrize("paths,overlap", [
    (["retired/a", "retired/a-b", "retired/a/b"], True),
    (["retired/a/b", "retired/a-b", "retired/a"], True),
    (["retired/a", "retired/a-b", "retired/ab"], False),
    (["retired/a/b", "retired/a-b/c", "retired/a/c"], False),
])
def test_path_components_detect_nonadjacent_ancestors(batch_layout, monkeypatch, paths, overlap):
    calls = stub_snapshot(batch_layout, monkeypatch)
    if overlap:
        with pytest.raises(ValueError, match="overlap"):
            storage.create_plan(batch_layout["repo"], batch_layout["companion"], paths,
                                "Reviewed generated paths", "Synthetic writer inactive")
        assert calls == [], "Overlap must be rejected before walking or hashing selected data"
    else:
        plan = storage.create_plan(batch_layout["repo"], batch_layout["companion"], paths,
                                   "Reviewed generated paths", "Synthetic writer inactive")
        assert [item["path"] for item in plan["items"]] == sorted(paths)
        assert calls == sorted(paths)


def test_ten_thousand_path_plan_reports_scaling_without_a_wall_time_gate(batch_layout, monkeypatch):
    calls = stub_snapshot(batch_layout, monkeypatch)
    paths = ["retired/batch/telemetry-%05d.json" % index for index in range(10000)]
    start = time.perf_counter()
    assert not legacy_pairwise_overlap(paths)
    legacy_seconds = time.perf_counter() - start
    start = time.perf_counter()
    plan = storage.create_plan(batch_layout["repo"], batch_layout["companion"], paths,
                               "Reviewed generated paths", "Synthetic writer inactive")
    elapsed = time.perf_counter() - start
    assert len(plan["items"]) == 10000 and calls == paths
    evidence = {"paths": len(paths), "legacy_pairwise_overlap_seconds": legacy_seconds,
                "current_plan_seconds_with_metadata_stub": elapsed,
                "snapshot_calls": len(calls), "benchmark_payload_files_created": 0}
    write_json(batch_layout["temporary_root"] / "planning-performance.json", evidence)
    print(json.dumps(evidence, sort_keys=True))


@pytest.mark.skipif(os.name != "nt", reason="Checks Windows plan admission limits")
def test_plan_rejects_more_than_ten_thousand_snapshot_rows(batch_layout, monkeypatch):
    paths = ["retired/batch/telemetry-%05d.json" % index for index in range(10001)]
    stub_snapshot(batch_layout, monkeypatch)
    with pytest.raises(ValueError, match="1..10000 rows"):
        storage.create_plan(batch_layout["repo"], batch_layout["companion"], paths,
                            "Reviewed synthetic paths", "Synthetic writer inactive")


@pytest.mark.skipif(os.name != "nt", reason="Counts directories in Windows plan admission")
def test_plan_row_limit_includes_selected_directory_shells(batch_layout, monkeypatch):
    row = {"path": "retired/batch", "type": "directory", "bytes": 0, "mtime_ns": 0}
    payload = {"path": "retired/batch/file.json", "type": "file", "bytes": 0,
               "mtime_ns": 0, "sha256": hashlib.sha256(b"").hexdigest()}
    monkeypatch.setattr(storage, "retirement_rows", lambda *args: [row] + [payload] * 10000)
    with pytest.raises(ValueError, match="1..10000 rows"):
        storage.create_plan(batch_layout["repo"], batch_layout["companion"], ["retired/batch"],
                            "Reviewed synthetic directory", "Synthetic writer inactive")


@pytest.mark.skipif(os.name != "nt", reason="Checks complete Windows native request bytes")
def test_plan_size_limit_includes_configuration_controls(batch_layout, monkeypatch):
    root = batch_layout["companion"]
    before = (root / "cache/result.json").read_bytes()
    rows = storage.retirement_rows(storage.validate_contract(batch_layout["repo"]), root, "cache/result.json")
    without_controls = json.dumps({"root": str(root), "rows": rows, "controls": []}).encode("utf-8")
    monkeypatch.setattr(storage, "MAX_NATIVE_REQUEST_BYTES", len(without_controls))
    with pytest.raises(ValueError, match="request exceeds"):
        storage.create_plan(batch_layout["repo"], root, ["cache/result.json"],
                            "Reviewed synthetic payload", "Synthetic writer inactive")
    assert (root / "cache/result.json").read_bytes() == before


@pytest.mark.skipif(os.name != "nt", reason="Checks Windows case-insensitive selection")
def test_paths_file_rejects_casefold_duplicates(batch_layout, tmp_path, capsys):
    selection = tmp_path / "selection.json"
    write_json(selection, ["cache/result.json", "CACHE/result.json"])
    before = (batch_layout["companion"] / "cache/result.json").read_bytes()
    assert storage.main(["plan", "--repo", str(batch_layout["repo"]),
                         "--companion", str(batch_layout["companion"]),
                         "--paths-file", str(selection), "--reason", "reviewed",
                         "--inactive-evidence", "inactive"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False and "items" not in result
    assert (batch_layout["companion"] / "cache/result.json").read_bytes() == before


@pytest.mark.native
@pytest.mark.skipif(os.name != "nt", reason="Measures the Windows native batch-removal path")
def test_thousand_files_use_one_plan_check_and_one_native_process(batch_layout, monkeypatch):
    paths = generated_leaves(batch_layout, ("telemetry-%05d.json" % index for index in range(1000)))
    start = time.perf_counter()
    assert not legacy_pairwise_overlap(paths)
    legacy_seconds = time.perf_counter() - start
    start = time.perf_counter()
    plan_path, digest, plan = approved_plan(batch_layout, paths)
    planning_seconds = time.perf_counter() - start
    original_plan, original_run = storage.create_plan, storage.subprocess.run
    calls = {"plans": 0, "powershell": 0}

    def counted_plan(*args, **kwargs):
        calls["plans"] += 1
        return original_plan(*args, **kwargs)

    def counted_run(args, **kwargs):
        if Path(args[0]).name.casefold() in ("powershell.exe", "pwsh.exe", "pwsh"):
            calls["powershell"] += 1
        return original_run(args, **kwargs)

    monkeypatch.setattr(storage, "create_plan", counted_plan)
    monkeypatch.setattr(storage.subprocess, "run", counted_run)
    start = time.perf_counter()
    result = storage.apply_plan(batch_layout["repo"], batch_layout["companion"], plan_path, digest)
    apply_seconds = time.perf_counter() - start
    assert calls["plans"] == 1
    assert calls["powershell"] == 1
    assert result["removed"] == [item["path"] for item in plan["items"]]
    assert result["bytes"] == len(paths) * len(batch_layout["sentinel"])
    assert all(not (batch_layout["companion"] / path).exists() for path in paths)
    assert (batch_layout["companion"] / "registry.json").is_file()
    assert (batch_layout["companion"] / "cache/result.json").is_file()
    assert (batch_layout["companion"] / "retired/result.json").is_file()
    evidence = {"files": len(paths), "bytes": result["bytes"],
                "approved_plan_bytes": plan_path.stat().st_size,
                "legacy_pairwise_overlap_seconds": legacy_seconds,
                "current_full_plan_seconds": planning_seconds,
                "native_apply_seconds": apply_seconds, "plan_checks_during_apply": calls["plans"],
                "powershell_invocations": calls["powershell"]}
    write_json(batch_layout["temporary_root"] / "native-batch-performance.json", evidence)
    print(json.dumps(evidence, sort_keys=True))


def changed_before_native(layout, monkeypatch, mutate):
    original = storage.remove_exact
    calls = []

    def changed(root, rows, *args, **kwargs):
        calls.append(True)
        assert len(calls) == 1, "The approved plan must be removed in one native batch"
        mutate()
        return original(root, rows, *args, **kwargs)

    monkeypatch.setattr(storage, "remove_exact", changed)
    return calls


def partial_result(exc, paths, root):
    assert isinstance(exc, ValueError)
    assert type(exc).__name__ == "RetirementApplyError"
    result = exc.result
    assert result["ok"] is False and result["mode"] == "partial"
    assert result["failed_path"] in paths and result["error"]
    removed = [row["path"] if isinstance(row, dict) else row for row in result["removed"]]
    assert len(removed) == len(set(removed))
    assert all(not Path(path).is_absolute() and ".." not in Path(path).parts for path in removed)
    assert set(removed) == {path for path in paths if not (root / path).exists()}
    return result


@pytest.mark.native
@pytest.mark.skipif(os.name != "nt", reason="Exercises Windows final per-leaf validation")
@pytest.mark.parametrize("mutation", ["content", "mtime", "hardlink", "nested_git", "parent_link"])
def test_late_leaf_or_parent_change_fails_closed_with_exact_partial_result(batch_layout, monkeypatch, mutation):
    paths = generated_leaves(batch_layout, ["a.json", "z.json"])
    plan_path, digest, _ = approved_plan(batch_layout, paths)
    root = batch_layout["companion"]
    victim = root / paths[0]
    protected = batch_layout["temporary_root"] / "protected"
    protected.mkdir()
    before = victim.stat()

    def mutate():
        if mutation == "content":
            victim.write_bytes(batch_layout["sentinel"][::-1])
            os.utime(victim, ns=(before.st_atime_ns, before.st_mtime_ns))
        elif mutation == "mtime":
            os.utime(victim, ns=(before.st_atime_ns, before.st_mtime_ns + 2_000_000_000))
        elif mutation == "hardlink":
            os.link(victim, protected / "retained-link.json")
        elif mutation == "nested_git":
            (victim.parent / ".git").mkdir()
        else:
            import _winapi
            displaced = batch_layout["temporary_root"] / "displaced-batch"
            assert victim.parent.resolve().is_relative_to(batch_layout["temporary_root"].resolve())
            assert displaced.resolve().is_relative_to(batch_layout["temporary_root"].resolve())
            victim.parent.rename(displaced)
            _winapi.CreateJunction(str(displaced), str(victim.parent))

    calls = changed_before_native(batch_layout, monkeypatch, mutate)
    with pytest.raises(ValueError) as caught:
        storage.apply_plan(batch_layout["repo"], root, plan_path, digest)
    assert calls == [True]
    result = partial_result(caught.value, paths, root)
    if mutation in ("content", "mtime", "hardlink"):
        assert not (root / paths[1]).exists(), "The first valid native leaf must be removed before the final leaf fails"
        assert result["failed_path"] == paths[0]
        removed = [row["path"] if isinstance(row, dict) else row for row in result["removed"]]
        assert removed == [paths[1]]
    assert victim.exists(), "The changed or externally linked target must survive"
    assert victim.read_bytes() == (batch_layout["sentinel"][::-1] if mutation == "content" else batch_layout["sentinel"])
    assert (root / "registry.json").is_file()
    if mutation == "parent_link":
        assert all((batch_layout["temporary_root"] / "displaced-batch" / name).read_bytes()
                   == batch_layout["sentinel"] for name in ("a.json", "z.json"))


@pytest.mark.native
@pytest.mark.skipif(os.name != "nt", reason="Exercises the Windows contract freeze lock")
def test_contract_is_frozen_or_change_stops_all_removals(batch_layout, monkeypatch):
    paths = generated_leaves(batch_layout, ["a.json", "z.json"])
    plan_path, digest, _ = approved_plan(batch_layout, paths)
    root = batch_layout["companion"]
    target = batch_layout["repo"] / storage.CONTRACT
    before = target.read_bytes()
    observed = {"blocked": False}

    def mutate():
        try:
            contract = json.loads(before)
            contract["artifacts"][1]["purpose"] = "Synthetic changed consumer after review"
            write_json(target, contract)
        except PermissionError:
            observed["blocked"] = True
            assert target.read_bytes() == before

    calls = changed_before_native(batch_layout, monkeypatch, mutate)
    try:
        result = storage.apply_plan(batch_layout["repo"], root, plan_path, digest)
    except ValueError as exc:
        assert not observed["blocked"], "An unchanged frozen control file must not invalidate its approved plan"
        assert all((root / path).is_file() for path in paths)
        if hasattr(exc, "result"):
            assert exc.result["removed"] == [] and exc.result["ok"] is False
    else:
        assert observed["blocked"], "A successful control-file change must stop the whole batch"
        assert target.read_bytes() == before
        assert result["removed"] == paths
    assert calls == [True]


def test_wrong_approval_reaches_neither_reproof_nor_native_deletion(batch_layout, monkeypatch):
    paths = generated_leaves(batch_layout, ["a.json", "z.json"])
    plan_path, _, _ = approved_plan(batch_layout, paths)

    def forbidden(*args, **kwargs):
        pytest.fail("Unapproved plan reached a reproof or native deletion")

    monkeypatch.setattr(storage, "create_plan", forbidden)
    monkeypatch.setattr(storage, "remove_exact", forbidden)
    with pytest.raises(ValueError, match="approval"):
        storage.apply_plan(batch_layout["repo"], batch_layout["companion"], plan_path, "0" * 64)
    assert all((batch_layout["companion"] / path).read_bytes() == batch_layout["sentinel"] for path in paths)


def test_selected_activity_marker_cannot_enter_an_approved_batch(batch_layout, monkeypatch):
    paths = generated_leaves(batch_layout, ["worker.LOCK"])

    def forbidden(*args, **kwargs):
        pytest.fail("An activity marker reached native deletion")

    monkeypatch.setattr(storage, "remove_exact", forbidden)
    with pytest.raises(ValueError, match="active|marker"):
        approved_plan(batch_layout, paths)
    assert (batch_layout["companion"] / paths[0]).read_bytes() == batch_layout["sentinel"]


@pytest.mark.native
@pytest.mark.skipif(os.name != "nt", reason="Reconciles lost receipts after real native removal")
@pytest.mark.parametrize("unknown_boundary", [False, True])
def test_incomplete_native_receipts_keep_unacknowledged_state_separate(batch_layout, monkeypatch, unknown_boundary):
    """Truncate successful native output to simulate a broken acknowledgement channel."""
    paths = generated_leaves(batch_layout, ["a.json", "z.json"])
    plan_path, digest, _ = approved_plan(batch_layout, paths)
    root = batch_layout["companion"]
    original_run = storage.subprocess.run
    calls = []

    def interrupted_receipts(args, **kwargs):
        result = original_run(args, **kwargs)
        if Path(args[0]).name.casefold() != "powershell.exe":
            return result
        calls.append(True)
        assert result.returncode == 0, result.stderr
        receipts = [json.loads(line) for line in result.stdout.splitlines()]
        assert receipts == [{"removed": 0}, {"removed": 1}]
        assert all(not (root / path).exists() for path in paths)
        if unknown_boundary:
            import _winapi
            parent = root / "retired/batch"
            displaced = batch_layout["temporary_root"] / "displaced-after-native"
            assert parent.resolve().is_relative_to(batch_layout["temporary_root"].resolve())
            assert displaced.resolve().is_relative_to(batch_layout["temporary_root"].resolve())
            parent.rename(displaced)
            _winapi.CreateJunction(str(displaced), str(parent))
        return subprocess.CompletedProcess(result.args, 137,
                                           stdout=json.dumps(receipts[0]) + "\n",
                                           stderr="Synthetic acknowledgement channel interrupted")

    monkeypatch.setattr(storage.subprocess, "run", interrupted_receipts)
    with pytest.raises(storage.RetirementApplyError) as caught:
        storage.apply_plan(batch_layout["repo"], root, plan_path, digest)

    result = caught.value.result
    assert calls == [True]
    assert result["removed"] == [paths[1]] and result["removed_count"] == 1
    assert result["native_exit_code"] == 137
    assert result["failed_path"] == paths[0]
    assert result["unacknowledged_missing"] == ([] if unknown_boundary else [paths[0]])
    assert result["boundary_unknown"] == ([paths[0]] if unknown_boundary else [])


@pytest.mark.native
@pytest.mark.skipif(os.name != "nt", reason="Exercises real Windows Unicode paths and error output")
@pytest.mark.parametrize("missing_leaf", [False, True])
def test_unicode_leaf_receipts_preserve_paths_and_native_error(batch_layout, monkeypatch, missing_leaf):
    paths = generated_leaves(batch_layout, ["a-合成.json", "z-合成.json"])
    plan_path, digest, _ = approved_plan(batch_layout, paths)
    root = batch_layout["companion"]
    victim = root / paths[0]
    retained = batch_layout["temporary_root"] / "retained-合成.json"
    original_run = storage.subprocess.run
    native_results = []

    def recorded_run(args, **kwargs):
        result = original_run(args, **kwargs)
        if Path(args[0]).name.casefold() == "powershell.exe":
            native_results.append(result)
        return result

    monkeypatch.setattr(storage.subprocess, "run", recorded_run)
    if missing_leaf:
        def mutate():
            assert victim.resolve().is_relative_to(batch_layout["temporary_root"].resolve())
            assert retained.resolve().is_relative_to(batch_layout["temporary_root"].resolve())
            victim.rename(retained)

        changed_before_native(batch_layout, monkeypatch, mutate)
        with pytest.raises(storage.RetirementApplyError) as caught:
            storage.apply_plan(batch_layout["repo"], root, plan_path, digest)
        result = caught.value.result
        assert result["removed"] == [paths[1]] and result["removed_count"] == 1
        assert result["failed_path"] == paths[0]
        assert victim.name in result["error"] and "\ufffd" not in result["error"]
        assert result["unacknowledged_missing"] == [paths[0]]
        assert result["boundary_unknown"] == []
        assert retained.read_bytes() == batch_layout["sentinel"]
    else:
        result = storage.apply_plan(batch_layout["repo"], root, plan_path, digest)
        assert result["removed"] == paths
        assert result["bytes"] == len(paths) * len(batch_layout["sentinel"])
        assert not retained.exists()

    assert all(not (root / path).exists() for path in paths)
    assert len(native_results) == 1
    native = native_results[0]
    receipts = [json.loads(line) for line in native.stdout.splitlines()]
    assert native.returncode == int(missing_leaf)
    if missing_leaf:
        assert receipts == [{"removed": 0}, {"failed_index": 1, "error": result["error"]}]
    else:
        assert receipts == [{"removed": 0}, {"removed": 1}]
    assert (root / "registry.json").is_file()


@pytest.mark.skipif(os.name != "nt", reason="Exercises the Windows native receipt parser with a mocked child")
@pytest.mark.parametrize("invalid_output", [
    pytest.param("0", id="scalar"),
    pytest.param("[]", id="list"),
    pytest.param('{"failed_index":0,"error":"Synthetic mismatched index"}', id="mismatched-failure-index"),
    pytest.param('{"removed":0}', id="duplicate-ack"),
    pytest.param('{"removed":true}', id="boolean-ack"),
    pytest.param('{"removed":1,"extra":true}', id="extra-ack-field"),
    pytest.param('{"failed_index":1,"error":"Synthetic native failure"}\n{"removed":1}', id="output-after-failure"),
    pytest.param('{"removed":', id="truncated-json"),
])
def test_invalid_native_receipt_preserves_only_prior_acknowledgements(batch_layout, monkeypatch, invalid_output):
    """Mock child receipts only; no filesystem deletion is claimed by this test."""
    paths = generated_leaves(batch_layout, ["a.json", "z.json"])
    plan_path, digest, _ = approved_plan(batch_layout, paths)
    root = batch_layout["companion"]
    original_run = storage.subprocess.run
    calls = []

    def invalid_receipts(args, **kwargs):
        if Path(args[0]).name.casefold() != "powershell.exe":
            return original_run(args, **kwargs)
        calls.append(True)
        return subprocess.CompletedProcess(args, 0,
                                           stdout='{"removed":0}\n' + invalid_output + "\n", stderr="")

    monkeypatch.setattr(storage.subprocess, "run", invalid_receipts)
    with pytest.raises(storage.RetirementApplyError) as caught:
        storage.apply_plan(batch_layout["repo"], root, plan_path, digest)

    result = caught.value.result
    assert calls == [True]
    assert result["ok"] is False and result["mode"] == "partial"
    assert result["removed"] == [paths[1]] and result["removed_count"] == 1
    assert result["failed_path"] == paths[0] and result["error"]
    assert result["unacknowledged_missing"] == result["boundary_unknown"] == []
    assert result["native_exit_code"] == 0
    assert all((root / path).read_bytes() == batch_layout["sentinel"] for path in paths)


@pytest.mark.skipif(os.name != "nt", reason="Exercises pre-launch Windows native admission limits")
@pytest.mark.parametrize("limit", ["row_count", "request_bytes"])
def test_native_batch_limits_reject_before_launch(batch_layout, monkeypatch, limit):
    row = {"path": "retired/batch/synthetic.json", "type": "file",
           "bytes": len(batch_layout["sentinel"]), "mtime_ns": 0,
           "sha256": hashlib.sha256(batch_layout["sentinel"]).hexdigest()}
    if limit == "row_count":
        rows, message = [row] * 10001, "requires 1..10000 rows"
    else:
        rows, message = [row], "request exceeds"
        monkeypatch.setattr(storage, "MAX_NATIVE_REQUEST_BYTES", 64)

    def forbidden(*args, **kwargs):
        pytest.fail("An oversized native request launched a child process")

    monkeypatch.setattr(storage.subprocess, "run", forbidden)
    with pytest.raises(ValueError, match=message):
        storage.remove_exact(batch_layout["companion"], rows)
