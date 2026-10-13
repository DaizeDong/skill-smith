"""Report writes check the destination once; the fleet audit still proves PRIVATE routes."""
import json
from types import SimpleNamespace

import pytest

@pytest.fixture
def case(private_output):
    return private_output


def write_status(case, path):
    checked = case["fleet"].resolve_status_path(str(path))
    return case["fleet"].write_status(checked, [], case["counts"], "2000-01-01T00:00:00Z", 0, 0)


def audit(case):
    return case["fleet"].check_data_boundary(
        str(case["visibility"]), {"synthetic-tool": str(case["consumer"])}, offline=True)


def test_private_status_with_only_vault_remote_is_written(case):
    case["git"](case["private"], "remote", "rename", "origin", "Vault")
    target = case["data"] / "fleet-check-status.json"
    assert write_status(case, target)["schema"] == 2
    assert json.loads(target.read_text(encoding="utf-8"))["schema"] == 2
    assert audit(case).count("PASS") == 1


@pytest.mark.parametrize("setting", ["core.sshCommand", "GIT_SSH_COMMAND"])
def test_custom_ssh_transport_fails_the_audit(case, monkeypatch, setting):
    case["git"](case["private"], "remote", "set-url", "origin", case["ssh_origin"])
    if setting == "GIT_SSH_COMMAND":
        monkeypatch.setenv(setting, case["ssh_override"])
    else:
        case["git"](case["private"], "config", setting, case["ssh_override"])
    assert audit(case).count("FAIL") == 1


def test_private_destination_ignores_public_git_selectors(case, monkeypatch):
    monkeypatch.setenv("GIT_DIR", str(case["public"] / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(case["private"]))
    target = case["data"] / "fleet-check-status.json"
    write_status(case, target)
    assert target.is_file()


def test_private_destination_cannot_contain_the_audited_source(case):
    target = case["data"] / "fleet-check-status.json"
    with pytest.raises(ValueError, match="outside the tool repository"):
        case["fleet"].resolve_status_path(str(target), source_root=str(case["private"] / "source"))
    assert not target.exists()


def test_inverse_audit_rejects_live_public_visibility_despite_private_receipt(case):
    oracle = SimpleNamespace(error="", map_age=lambda: (0, None), prefetch=lambda slugs: None,
                             visibility=lambda slug: ("PUBLIC", "synthetic live observation"))
    result = case["fleet"].check_data_boundary(
        str(case["visibility"]), {"synthetic-tool": str(case["consumer"])}, oracle=oracle)
    assert result.count("FAIL") == 1 and result.count("PASS") == 0
    assert "PUBLIC" in result.rows[0][2]

