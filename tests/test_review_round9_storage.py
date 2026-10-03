"""Storage and inventory contracts, using generated paths and synthetic Git responses."""
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(os.environ.get("SS_SOURCE", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "skills/skill-smith/scripts"))


def module(name):
    spec = importlib.util.spec_from_file_location(name + "_storage9", ROOT / "skills/skill-smith/scripts" / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@pytest.fixture
def layout(private_output):
    return private_output


@pytest.mark.parametrize("index", range(5))
def test_non_github_identity_never_borrows_private_visibility(layout, monkeypatch, index):
    fc = layout["fleet"]
    layout["git"](layout["private"], "remote", "set-url", "origin", layout["bad_origins"][index])
    with pytest.raises(ValueError, match="PRIVATE"):
        fc.resolve_status_path(str(layout["data"] / "report.json"), str(layout["visibility"]))


def test_verified_github_and_explicit_ssh_alias_remain_supported(layout):
    fc = module("fleet_check")
    assert fc.slug_from_url(layout["origin"]) == layout["slug"]
    assert fc.slug_from_url("git@acme-code:AcmeCorp/skill-smith-config.git") == layout["slug"]


@pytest.mark.parametrize("index", range(4))
def test_git_inspection_errors_are_unknown(layout, monkeypatch, index):
    fc = module("fleet_check")
    monkeypatch.setattr(fc, "run", lambda *a, **kw: (128, "", layout["git_errors"][index]))
    assert fc.in_git_worktree(str(layout["data"]))[0] is None


def test_conclusive_non_repository_is_still_outside(layout, monkeypatch):
    fc = module("fleet_check")
    monkeypatch.setattr(fc, "run", lambda *a, **kw: (128, "", "fatal: not a git repository (or any of the parent directories): .git"))
    assert fc.in_git_worktree(str(layout["data"])) == (False, "")


def test_inventory_retains_failed_inspections(layout, monkeypatch):
    fc = module("fleet_check")
    (layout["tool"] / ".git").mkdir()
    monkeypatch.setattr(fc, "run", lambda *a, **kw: (128, "", layout["git_errors"][0]))
    problems = []
    repos = fc.local_repos(str(layout["tool"].parent), problems=problems)
    assert not repos
    assert any(name == "tool" and "ownership" in detail for name, detail in problems)


def test_origin_inventory_retains_unsupported_remote(layout, monkeypatch):
    fc = module("fleet_check")
    monkeypatch.setattr(fc, "run", lambda *a, **kw: (0, layout["bad_origins"][0], ""))
    problems = []
    assert not fc.repo_slugs({"tool": str(layout["tool"])}, problems=problems)
    assert problems and problems[0][0] == "tool"


def test_missing_kit_never_loads_consumer_legacy_resolver(layout, monkeypatch):
    fc = module("fleet_check")
    layout["resolver"].unlink()
    legacy = layout["tool"] / "tools/datadir.py"
    legacy.parent.mkdir()
    legacy.write_text("raise AssertionError('obsolete resolver executed')\n", encoding="utf-8")
    loads = []
    monkeypatch.setattr(fc, "load_datadir", lambda path, *a: loads.append(path) or SimpleNamespace(resolve_data_dir=lambda *a, **kw: None))
    check = fc.check_data_boundary("unused", {"tool": str(layout["tool"])}, offline=True)
    assert not loads
    assert check.count(fc.UNKNOWN) == 1 and check.count(fc.SKIP) == 0


@pytest.mark.parametrize("state,rc,want", [("UNKNOWN", 2, "UNKNOWN"), ("OK", 0, "UNKNOWN"), ("FAIL", 1, "FAIL"), ("BLOCKED", 3, "WARN")])
def test_budget_preserves_unresolved_coverage_and_known_failure(layout, monkeypatch, state, rc, want):
    fc = module("fleet_check")
    digest = f"BUDGET: {state} total=10 capacity=100 overflow=0 min_lost=0 unresolved=1 lever=n/a fp=synthetic"
    monkeypatch.setattr(fc, "run", lambda *a, **kw: (rc, digest, ""))
    check = fc.check_budget("synthetic", "synthetic", 2)
    assert check.rows[0][0] == want
    assert "unresolved=1" in check.rows[0][2]
    assert check.count(fc.UNKNOWN) >= 1


@pytest.mark.parametrize("kind", ["PUBLIC", "UNKNOWN", "unversioned"])
def test_trim_scan_requires_private_versioned_output(layout, monkeypatch, kind):
    trim = layout["trim"]
    states = json.loads(layout["visibility"].read_text(encoding="utf-8"))
    states[layout["slug"]] = kind
    layout["visibility"].write_text(json.dumps(states), encoding="utf-8")
    target = (layout["home"] if kind == "unversioned" else layout["data"]) / "worklist.json"
    monkeypatch.setattr(sys, "argv", ["trim", "--scan", "--skills-dir", str(layout["library"]), "--out", str(target)])
    assert trim.main() != 0
    assert not target.exists()


def test_trim_default_requires_pinned_resolver(layout, monkeypatch):
    trim = module("trim_descriptions")
    monkeypatch.setattr(trim, "_REPO_ROOT", str(layout["tool"]))
    with pytest.raises((ValueError, RuntimeError), match="companion|DATA"):
        trim._default_out_path()


def test_status_refuses_hardlinked_write_target(layout, monkeypatch):
    fc = module("fleet_check")
    monkeypatch.setattr(fc, "HERE", str(layout["tool"] / "skills/skill-smith/scripts"))
    monkeypatch.setattr(fc, "run", lambda args, **kw: (0, str(layout["data"].parent), "") if "rev-parse" in args else (0, layout["origin"], ""))
    original = layout["data"] / "original.json"
    original.write_text("synthetic\n", encoding="utf-8")
    linked = layout["data"] / "report.json"
    os.link(original, linked)
    oracle = SimpleNamespace(visibility=lambda *a: ("PRIVATE", "synthetic"))
    with pytest.raises(ValueError, match="hardlink|alias"):
        fc.resolve_status_path(str(linked), "unused", oracle=oracle)


def private_storage(layout, monkeypatch):
    fc = layout["fleet"]
    monkeypatch.setattr(fc, "HERE", str(layout["tool"] / "skills/skill-smith/scripts"))
    return fc, layout["trim"]


def test_private_trim_scan_apply_roundtrip_preserves_backup(layout, monkeypatch):
    fc, trim = private_storage(layout, monkeypatch)
    worklist = layout["data"] / "worklist.json"
    before = layout["descriptor"].read_text(encoding="utf-8")
    assert trim.do_scan(str(layout["library"]), 50, str(worklist)) == 0
    rows = json.loads(worklist.read_text(encoding="utf-8"))
    rows[0]["new"] = "Generate research reports."
    worklist.write_text(json.dumps(rows), encoding="utf-8")
    backup = layout["data"] / "backups"
    assert trim.do_apply(str(worklist), False, str(backup)) == 0
    assert "Generate research reports." in layout["descriptor"].read_text(encoding="utf-8")
    assert [p.read_text(encoding="utf-8") for p in backup.rglob("*") if p.is_file()] == [before]


def test_trim_rejects_public_backup_before_modifying_any_description(layout, monkeypatch):
    fc, trim = private_storage(layout, monkeypatch)
    worklist = layout["data"] / "worklist.json"
    assert trim.do_scan(str(layout["library"]), 50, str(worklist)) == 0
    rows = json.loads(worklist.read_text(encoding="utf-8"))
    rows[0]["new"] = "Generate research reports."
    worklist.write_text(json.dumps(rows), encoding="utf-8")
    before = layout["descriptor"].read_bytes()
    with pytest.raises(ValueError, match="tool repository"):
        trim.do_apply(str(worklist), False, str(layout["tool"] / "backups"))
    assert layout["descriptor"].read_bytes() == before
    assert not (layout["tool"] / "backups").exists()


def test_fixed_status_temporary_alias_is_rejected(layout):
    fc = module("fleet_check")
    output = layout["data"] / "status.json"
    sentinel = layout["data"] / "sentinel.json"
    sentinel.write_text("synthetic\n", encoding="utf-8")
    os.link(sentinel, str(output) + ".tmp")
    counts = {key: 0 for key in ("pass", "fail", "warn", "skip", "unknown")}
    with pytest.raises(ValueError, match="hardlink|alias"):
        fc.write_status(str(output), [], counts, "2026-01-01T00:00:00Z", 0, 0)
    assert not output.exists()


def test_github_queries_ignore_inherited_other_host(layout, monkeypatch):
    fc = module("fleet_check")
    monkeypatch.setenv("GH_HOST", "mirror.example.com")
    seen = []
    def child(args, **kwargs):
        seen.append(kwargs.get("env") or dict(os.environ))
        return SimpleNamespace(returncode=0, stdout="PRIVATE", stderr="")
    monkeypatch.setattr(fc.subprocess, "run", child)
    assert fc.run(["gh", "repo", "view", layout["slug"], "--json", "visibility"])[0] == 0
    assert seen[0]["GH_HOST"] == "github.com"


def test_existing_backup_directory_uses_its_own_repository_identity(layout, monkeypatch):
    fc, trim = private_storage(layout, monkeypatch)
    nested = layout["data"] / "backups"
    nested.mkdir()
    layout["git"](nested, "init", "-q")
    public_origin = layout["git"](layout["public"], "remote", "get-url", "origin").stdout.strip()
    layout["git"](nested, "remote", "add", "origin", public_origin)
    with pytest.raises(ValueError, match="PRIVATE"):
        fc.resolve_status_path(str(nested), str(layout["visibility"]), directory=True)
