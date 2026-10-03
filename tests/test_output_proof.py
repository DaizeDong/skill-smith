"""PRIVATE writer admission uses native Git and the pinned shared proof API."""
import json
from types import SimpleNamespace

import pytest

@pytest.fixture
def case(private_output):
    return private_output


def write_status(case, path, **kwargs):
    return case["fleet"].write_status(str(path), [], case["counts"], "2000-01-01T00:00:00Z",
                                      0, 0, visibility_path=str(case["visibility"]), **kwargs)


def audit(case):
    return case["fleet"].check_data_boundary(
        str(case["visibility"]), {"synthetic-tool": str(case["consumer"])}, offline=True)


def test_private_status_with_only_vault_remote_is_written(case):
    case["git"](case["private"], "remote", "rename", "origin", "Vault")
    target = case["data"] / "reports/status.json"
    assert write_status(case, target)["schema"] == 2
    assert json.loads(target.read_text(encoding="utf-8"))["schema"] == 2
    assert audit(case).count("PASS") == 1


@pytest.mark.parametrize("setting", ["core.sshCommand", "GIT_SSH_COMMAND"])
def test_custom_ssh_transport_is_refused_before_output(case, monkeypatch, setting):
    case["git"](case["private"], "remote", "set-url", "origin", case["ssh_origin"])
    if setting == "GIT_SSH_COMMAND":
        monkeypatch.setenv(setting, case["ssh_override"])
    else:
        case["git"](case["private"], "config", setting, case["ssh_override"])
    target = case["data"] / "reports/status.json"
    with pytest.raises(ValueError, match="PRIVATE"):
        write_status(case, target)
    assert not target.parent.exists()
    assert audit(case).count("FAIL") == 1


def test_public_destination_cannot_borrow_private_git_selectors(case, monkeypatch):
    monkeypatch.setenv("GIT_DIR", str(case["private"] / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(case["public"]))
    target = case["public"] / "reports/status.json"
    with pytest.raises(ValueError, match="PRIVATE"):
        write_status(case, target)
    assert not target.parent.exists()


def test_private_destination_ignores_public_git_selectors(case, monkeypatch):
    monkeypatch.setenv("GIT_DIR", str(case["public"] / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(case["private"]))
    target = case["data"] / "reports/status.json"
    write_status(case, target)
    assert target.is_file()


def test_status_refuses_a_changed_proof_before_creating_parents(case):
    target = case["data"] / "reports/status.json"
    _, proof = case["fleet"].resolve_status_path(str(target), str(case["visibility"]))
    case["git"](case["private"], "config", "user.name", case["changed_signature"])
    with pytest.raises(ValueError, match="changed"):
        write_status(case, target, proof=proof)
    assert not target.parent.exists()


def test_status_refuses_a_new_nearer_worktree_before_creating_parents(case):
    target = case["data"] / "reports/status.json"
    _, proof = case["fleet"].resolve_status_path(str(target), str(case["visibility"]))
    case["git"](case["data"], "init", "-q")
    case["git"](case["data"], "remote", "add", "origin", case["origin"])
    with pytest.raises(ValueError, match="changed"):
        write_status(case, target, proof=proof)
    assert not target.parent.exists()


def test_private_destination_cannot_contain_the_audited_source(case):
    target = case["data"] / "reports/status.json"
    with pytest.raises(ValueError, match="outside the tool repository"):
        case["fleet"].resolve_status_path(str(target), str(case["visibility"]),
                                           source_root=str(case["private"] / "source"))
    assert not target.parent.exists()


def test_inverse_audit_rejects_live_public_visibility_despite_private_receipt(case):
    oracle = SimpleNamespace(error="", map_age=lambda: (0, None), prefetch=lambda slugs: None,
                             visibility=lambda slug: ("PUBLIC", "synthetic live observation"))
    result = case["fleet"].check_data_boundary(
        str(case["visibility"]), {"synthetic-tool": str(case["consumer"])}, oracle=oracle)
    assert result.count("FAIL") == 1 and result.count("PASS") == 0
    assert "PUBLIC" in result.rows[0][2]


@pytest.mark.parametrize("dependency", ["missing", "incompatible"])
def test_unavailable_shared_proof_fails_before_output(case, monkeypatch, dependency):
    fleet = case["fleet"]
    monkeypatch.setattr(fleet, "HERE", str(case["tool"] / "skills/skill-smith/scripts"))
    monkeypatch.setattr(fleet, "_private_output_boundary", case["boundary_loader"])
    if dependency == "incompatible":
        (case["tool"] / "guards/tools/data_boundary.py").write_text(
            case["incompatible_api"], encoding="utf-8")
    target = case["data"] / "reports/status.json"
    with pytest.raises((OSError, ImportError)):
        write_status(case, target)
    assert not target.parent.exists()


def test_trim_scan_rechecks_proof_after_collecting_descriptions(case, monkeypatch):
    trim = case["trim"]
    find = trim.find_skill_mds

    def changed(base):
        case["git"](case["private"], "config", "user.name", case["changed_signature"])
        return find(base)

    monkeypatch.setattr(trim, "find_skill_mds", changed)
    target = case["data"] / "reports/worklist.json"
    with pytest.raises(ValueError, match="changed"):
        trim.do_scan(str(case["library"]), 50, str(target))
    assert not target.parent.exists()


def test_trim_backup_rechecks_proof_before_modifying_descriptions(case, monkeypatch):
    trim = case["trim"]
    worklist = case["data"] / "worklist.json"
    assert trim.do_scan(str(case["library"]), 50, str(worklist)) == 0
    rows = json.loads(worklist.read_text(encoding="utf-8"))
    rows[0]["new"] = case["replacement"]
    worklist.write_text(json.dumps(rows), encoding="utf-8")
    before = case["descriptor"].read_bytes()
    validate = trim.validate_replacement

    def changed(*args):
        validate(*args)
        case["git"](case["private"], "config", "user.name", case["changed_signature"])

    monkeypatch.setattr(trim, "validate_replacement", changed)
    backups = case["data"] / "backups"
    with pytest.raises(ValueError, match="changed"):
        trim.do_apply(str(worklist), False, str(backups))
    assert case["descriptor"].read_bytes() == before
    assert not backups.exists()
