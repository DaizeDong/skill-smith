"""Exercise storage boundaries and real leaf removal using generated synthetic data."""
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/skill-smith/scripts"))
sys.path.insert(0, str(ROOT / "tools"))
import storage_contract as storage
from make_fixtures import storage_contract_fixture, write_json


@pytest.fixture
def layout(tmp_path, monkeypatch):
    value = storage_contract_fixture(tmp_path)
    proof = SimpleNamespace(root=value["companion"], repositories=("example/synthetic-config",))
    monkeypatch.setattr(storage, "prove_companion", lambda *args: (value["companion"], proof))
    return value


@pytest.mark.parametrize("bad", ["../outside", "/absolute", "C:/outside", "cache\\outside", "NUL.json", "cache/file:stream", "cache/trailing.", "**"])
def test_contract_rejects_escaping_and_catchall_patterns(layout, bad):
    contract = storage.validate_contract(layout["repo"])
    contract["artifacts"][1]["path_pattern"] = bad
    write_json(layout["repo"] / storage.CONTRACT, contract)
    with pytest.raises(ValueError):
        storage.validate_contract(layout["repo"])


def test_missing_retention_fails(layout):
    contract = storage.validate_contract(layout["repo"])
    contract["artifacts"][1].pop("retention_rule")
    write_json(layout["repo"] / storage.CONTRACT, contract)
    with pytest.raises(ValueError, match="retention"):
        storage.validate_contract(layout["repo"])


def test_working_data_budget_excludes_git_overhead(layout):
    admin = layout["companion"] / ".git/synthetic-object"
    admin.write_bytes(layout["sentinel"] * 100)
    result = storage.check_storage(layout["repo"], layout["companion"])
    assert result["ok"]
    assert result["git_overhead"]["bytes"] == admin.stat().st_size
    assert result["worktree_bytes_excluding_git"] < 1024
    (layout["companion"] / "cache/result.json").write_bytes(layout["sentinel"] * 100)
    result = storage.check_storage(layout["repo"], layout["companion"])
    assert not result["ok"] and result["over_budget"] == ["companion"]


def test_dry_run_reports_unknown_and_size_without_deleting(layout):
    unknown = layout["companion"] / "unmerged.py"
    unknown.write_bytes(layout["sentinel"])
    before = unknown.read_bytes()
    result = storage.check_storage(layout["repo"], layout["companion"])
    assert not result["ok"] and result["undeclared"] == ["unmerged.py"]
    assert result["bytes"] == sum(p.stat().st_size for p in layout["companion"].rglob("*") if p.is_file())
    assert unknown.read_bytes() == before


def test_core_and_unknown_paths_cannot_be_planned(layout):
    unknown = layout["companion"] / "unmerged.py"
    unknown.write_bytes(layout["sentinel"])
    for path in ("registry.json", "unmerged.py"):
        with pytest.raises(ValueError, match="core|unknown"):
            storage.create_plan(layout["repo"], layout["companion"], [path], "reviewed", "writer stopped")


def test_active_marker_and_protected_path_refuse_retirement(layout):
    marker = layout["companion"] / "cache/worker.lock"
    marker.write_bytes(layout["sentinel"])
    with pytest.raises(ValueError, match="active"):
        storage.create_plan(layout["repo"], layout["companion"], ["cache"], "reviewed", "writer stopped")
    contract = storage.validate_contract(layout["repo"])
    contract["protected_paths"] = ["retired/**"]
    write_json(layout["repo"] / storage.CONTRACT, contract)
    with pytest.raises(ValueError, match="protected"):
        storage.create_plan(layout["repo"], layout["companion"], ["retired"], "reviewed", "writer stopped")


def test_nested_repository_refuses_retirement(layout):
    (layout["companion"] / "cache/.git").mkdir()
    with pytest.raises(ValueError, match="nested repository"):
        storage.create_plan(layout["repo"], layout["companion"], ["cache"], "reviewed", "writer stopped")


def test_missing_inactivity_evidence_refuses_retirement(layout):
    with pytest.raises(ValueError, match="inactive"):
        storage.create_plan(layout["repo"], layout["companion"], ["cache"], "reviewed", "")


def plan_file(layout, tmp_path):
    plan = storage.create_plan(layout["repo"], layout["companion"], ["cache"], "reviewed disposable cache", "synthetic writer never started")
    target = tmp_path / "plan.json"
    write_json(target, plan)
    return target, hashlib.sha256(target.read_bytes()).hexdigest()


def test_wrong_approval_and_changed_bytes_preserve_targets(layout, tmp_path):
    plan, digest = plan_file(layout, tmp_path)
    with pytest.raises(ValueError, match="approval"):
        storage.apply_plan(layout["repo"], layout["companion"], plan, "0" * 64)
    target = layout["companion"] / "cache/result.json"
    target.write_bytes(layout["sentinel"])
    with pytest.raises(ValueError, match="changed"):
        storage.apply_plan(layout["repo"], layout["companion"], plan, digest)
    assert target.read_bytes() == layout["sentinel"]


def test_exact_authorized_removal_preserves_core_and_other_group(layout, tmp_path):
    plan, digest = plan_file(layout, tmp_path)
    result = storage.apply_plan(layout["repo"], layout["companion"], plan, digest)
    assert result["removed"] == ["cache"]
    assert not (layout["companion"] / "cache").exists()
    assert (layout["companion"] / "registry.json").is_file()
    assert (layout["companion"] / "retired/result.json").is_file()


def test_hardlinks_are_not_followed_or_deleted(layout):
    import os
    os.link(layout["companion"] / "registry.json", layout["companion"] / "cache/linked.json")
    result = storage.check_storage(layout["repo"], layout["companion"])
    assert any(row["reason"] == "hardlink" for row in result["boundary_errors"])
    with pytest.raises(ValueError, match="link"):
        storage.create_plan(layout["repo"], layout["companion"], ["cache"], "reviewed", "writer stopped")


def test_public_or_unknown_private_proof_failure_is_not_clean(tmp_path, monkeypatch):
    layout = storage_contract_fixture(tmp_path)
    class Refuse:
        def prove_private_companion(self, root):
            raise RuntimeError("PUBLIC or UNKNOWN destination")
    monkeypatch.setattr(storage, "load_guard", lambda *args: Refuse())
    assert storage.main(["check", "--repo", str(layout["repo"]), "--companion", str(layout["companion"])]) == 1


def test_junction_metadata_is_reported_without_descending(layout, monkeypatch):
    original = Path.lstat
    target = layout["companion"] / "cache"
    def lstat(path):
        info = original(path)
        if path == target:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        return info
    monkeypatch.setattr(Path, "lstat", lstat)
    result = storage.check_storage(layout["repo"], layout["companion"])
    assert result["boundary_errors"] == [{"path": "cache", "reason": "link_or_junction"}]
    assert not any(r["path"].startswith("cache/") for r in result["structure"])


@pytest.mark.parametrize("pattern", [".GIT", ".GIT/**", "cache/.GiT/**"])
def test_git_metadata_aliases_cannot_be_declared_for_retirement(layout, pattern):
    contract = storage.validate_contract(layout["repo"])
    contract["artifacts"][1]["path_pattern"] = pattern
    write_json(layout["repo"] / storage.CONTRACT, contract)

    with pytest.raises(ValueError, match="metadata"):
        storage.validate_contract(layout["repo"])


def test_uppercase_nested_repository_refuses_retirement(layout):
    (layout["companion"] / "cache/.GIT").mkdir()

    with pytest.raises(ValueError, match="nested repository"):
        storage.create_plan(layout["repo"], layout["companion"], ["cache"], "reviewed", "writer stopped")


def test_contract_change_after_full_preflight_preserves_targets(layout, tmp_path, monkeypatch):
    plan, digest = plan_file(layout, tmp_path)
    target = layout["companion"] / "cache/result.json"
    before = target.read_bytes()
    original = storage.create_plan
    calls = 0

    def change_contract_before_final_check(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            contract = storage.validate_contract(layout["repo"])
            contract["artifacts"][1]["purpose"] = "Synthetic consumer changed after plan review."
            write_json(layout["repo"] / storage.CONTRACT, contract)
        return original(*args, **kwargs)

    monkeypatch.setattr(storage, "create_plan", change_contract_before_final_check)

    with pytest.raises(ValueError, match="changed"):
        storage.apply_plan(layout["repo"], layout["companion"], plan, digest)
    assert target.read_bytes() == before


@pytest.mark.parametrize("name", ["worker.LOCK", "worker.PID", "state-WAL", "state-SHM"])
def test_uppercase_active_markers_refuse_retirement(layout, name):
    marker = layout["companion"] / "cache" / name
    marker.write_bytes(layout["sentinel"])

    with pytest.raises(ValueError, match="active"):
        storage.create_plan(layout["repo"], layout["companion"], ["cache"], "reviewed", "writer stopped")
    assert marker.read_bytes() == layout["sentinel"]


@pytest.fixture
def combined_layout(tmp_path, monkeypatch):
    value = storage_contract_fixture(tmp_path, combined=True)

    class PrivateBoundary:
        def prove_private_companion(self, root):
            return SimpleNamespace(root=root, repositories=("example/synthetic-config",))

    def load_guard(repo, name):
        assert name == "data_boundary", "combined layout must prove its own repository"
        return PrivateBoundary()

    monkeypatch.setattr(storage, "load_guard", load_guard)
    return value


def test_default_layout_rejects_source_as_its_own_companion(combined_layout):
    repo = combined_layout["repo"]
    contract = storage.validate_contract(repo)
    contract.pop("layout")
    contract.pop("data_roots")
    write_json(repo / storage.CONTRACT, contract)

    with pytest.raises(ValueError, match="separate|combined|same"):
        storage.prove_companion(repo, repo)


def test_explicit_combined_private_layout_proves_the_shared_root(combined_layout):
    repo = combined_layout["repo"]

    root, proof = storage.prove_companion(repo, repo)

    assert root == repo.resolve()
    assert proof.root == repo.resolve()
    assert proof.repositories == ("example/synthetic-config",)


def test_combined_layout_rejects_a_different_companion(combined_layout, tmp_path):
    other = tmp_path / "other-companion"
    other.mkdir()

    with pytest.raises(ValueError, match="same|source|combined"):
        storage.prove_companion(combined_layout["repo"], other)


@pytest.mark.parametrize("visibility", ["PUBLIC", "UNKNOWN"])
def test_combined_layout_still_requires_private_proof(combined_layout, monkeypatch, visibility):
    class RefuseBoundary:
        def prove_private_companion(self, root):
            raise RuntimeError(visibility + " destination")

    monkeypatch.setattr(storage, "load_guard", lambda *args: RefuseBoundary())

    with pytest.raises(RuntimeError, match=visibility):
        storage.prove_companion(combined_layout["repo"], combined_layout["companion"])


@pytest.mark.parametrize("roots", [
    [], ["."], [".."], ["../outside"], ["/absolute"], [".git"], [".GIT"],
    ["cache/*"], ["cache?"], ["cache", "cache/result.json"], ["cache", "cache"],
    ["cache", "CACHE"],
])
def test_combined_layout_rejects_unbounded_or_overlapping_roots(combined_layout, roots):
    repo = combined_layout["repo"]
    contract = storage.validate_contract(repo)
    contract["artifacts"] = [contract["artifacts"][1]]
    contract["data_roots"] = roots
    write_json(repo / storage.CONTRACT, contract)

    with pytest.raises(ValueError):
        storage.validate_contract(repo)


def test_combined_layout_requires_an_explicit_nonempty_scope(combined_layout):
    repo = combined_layout["repo"]
    contract = storage.validate_contract(repo)
    del contract["data_roots"]
    write_json(repo / storage.CONTRACT, contract)

    with pytest.raises(ValueError, match="data_roots|scope"):
        storage.validate_contract(repo)


@pytest.mark.parametrize("pattern", ["source-code.py", "cache-sibling/**", "*/result.json"])
def test_combined_artifacts_cannot_extend_beyond_data_roots(combined_layout, pattern):
    repo = combined_layout["repo"]
    contract = storage.validate_contract(repo)
    contract["artifacts"][1]["path_pattern"] = pattern
    write_json(repo / storage.CONTRACT, contract)

    with pytest.raises(ValueError, match="data_roots|scope"):
        storage.validate_contract(repo)


def test_combined_check_only_inventories_declared_data_roots(combined_layout):
    repo = combined_layout["repo"]
    source = repo / "source-code.py"
    before = source.read_bytes()

    result = storage.check_storage(repo, repo)

    assert result["ok"]
    assert result["layout"] == "combined_private_repo"
    assert set(result["data_roots"]) == {"registry.json", "cache", "retired"}
    assert {row["path"] for row in result["structure"]} == {
        "registry.json", "cache", "cache/result.json", "retired", "retired/result.json",
    }
    assert result["bytes"] == sum((repo / name).stat().st_size for name in (
        "registry.json", "cache/result.json", "retired/result.json",
    ))
    excluded = {entry["path"]: entry for entry in result["excluded_source"]}
    assert {"source-code.py", storage.CONTRACT}.issubset(excluded)
    assert excluded["source-code.py"]["type"] == "file"
    assert excluded["source-code.py"]["bytes"] == len(before)
    assert source.read_bytes() == before


def test_combined_apply_preserves_source_outside_the_data_scope(combined_layout, tmp_path):
    repo = combined_layout["repo"]
    source = repo / "source-code.py"
    before = source.read_bytes()
    plan, digest = plan_file(combined_layout, tmp_path)

    result = storage.apply_plan(repo, repo, plan, digest)

    assert result["removed"] == ["cache"]
    assert not (repo / "cache").exists()
    assert source.read_bytes() == before
    assert (repo / storage.CONTRACT).is_file()
    assert (repo / "registry.json").is_file()
    after = storage.check_storage(repo, repo)
    assert after["ok"]
    assert after["missing_data_roots"] == ["cache"]


def test_combined_apply_rejects_an_approved_source_path_outside_scope(combined_layout, tmp_path):
    repo = combined_layout["repo"]
    source = repo / "source-code.py"
    before = source.read_bytes()
    plan_path, _ = plan_file(combined_layout, tmp_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["items"][0]["path"] = "source-code.py"
    write_json(plan_path, plan)
    digest = hashlib.sha256(plan_path.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="scope|data_roots|unknown"):
        storage.apply_plan(repo, repo, plan_path, digest)
    assert source.read_bytes() == before
    assert (repo / "cache/result.json").is_file()


def test_combined_inaccessible_data_root_is_not_reported_as_missing(combined_layout, monkeypatch):
    import os

    repo = combined_layout["repo"]
    target = repo / "cache"
    original = os.lstat
    original_path_lstat = Path.lstat

    def lstat(path, *args, **kwargs):
        if Path(path) == target:
            raise PermissionError("Synthetic inaccessible data root")
        return original(path, *args, **kwargs)

    def path_lstat(path):
        if path == target:
            raise PermissionError("Synthetic inaccessible data root")
        return original_path_lstat(path)

    monkeypatch.setattr(os, "lstat", lstat)
    monkeypatch.setattr(Path, "lstat", path_lstat)

    with pytest.raises(PermissionError):
        storage.check_storage(repo, repo)


def test_combined_missing_root_does_not_hide_a_junction_ancestor(combined_layout, monkeypatch):
    repo = combined_layout["repo"]
    contract = storage.validate_contract(repo)
    contract["data_roots"][1] = "cache/missing"
    contract["artifacts"][1]["path_pattern"] = "cache/missing/**"
    write_json(repo / storage.CONTRACT, contract)
    original = Path.lstat
    target = repo / "cache"

    def lstat(path):
        info = original(path)
        if path == target:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        return info

    monkeypatch.setattr(Path, "lstat", lstat)

    with pytest.raises(ValueError, match="link|junction|reparse"):
        storage.check_storage(repo, repo)


@pytest.mark.parametrize("name,api", [
    ("data_boundary", "prove_private_companion"),
    ("datadir", "resolve_companion_root"),
])
def test_guard_loading_uses_the_checker_package_without_consumer_guards(tmp_path, name, api):
    value = storage_contract_fixture(tmp_path, combined=True)
    assert not (value["repo"] / "guards").exists()

    module = storage.load_guard(value["repo"], name)

    assert Path(module.__file__).resolve() == (ROOT / "guards/tools" / (name + ".py")).resolve()
    assert callable(getattr(module, api))
