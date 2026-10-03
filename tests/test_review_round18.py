"""Kit verification must bind required files and executable modes to Git's tree."""
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_review_round16 import fixtures, module


def kit_case(tmp_path, monkeypatch, kit, **options):
    scaffold = module("scaffold_skill")
    case = fixtures.review18_kit_payload(tmp_path, scaffold.KIT_FILES[kit], **options)

    def checked_git(root, *args):
        assert Path(root) == case["root"]
        assert args == ("ls-tree", "-r", "-z", "--full-tree", case["revision"])
        return case["entries"]

    monkeypatch.setattr(scaffold, "checked_git", checked_git)
    return scaffold, case


@pytest.mark.parametrize("kit", ["guards", "style"])
@pytest.mark.parametrize("object_format", ["sha1", "sha256"])
def test_complete_pinned_required_payload_is_accepted(tmp_path, monkeypatch, kit, object_format):
    scaffold, case = kit_case(tmp_path, monkeypatch, kit, object_format=object_format)
    scaffold.verify_kit_payload(case["root"], case["revision"], kit)


@pytest.mark.parametrize("kit", ["guards", "style"])
def test_ignored_required_replacement_cannot_supply_missing_pinned_member(tmp_path, monkeypatch, kit):
    required = module("scaffold_skill").KIT_FILES[kit]
    scaffold, case = kit_case(tmp_path, monkeypatch, kit, omitted=required[-1])
    assert (case["root"] / required[-1]).stat().st_size > 0
    with pytest.raises(SystemExit, match="required files absent from pinned tree"):
        scaffold.verify_kit_payload(case["root"], case["revision"], kit)


@pytest.mark.parametrize("pinned_mode,working_mode,accepted", [
    ("100755", 0o755, True), ("100755", 0o644, False),
    ("100644", 0o644, True), ("100644", 0o755, False),
])
def test_posix_execute_bit_is_verified_independently_of_git_status(
        tmp_path, monkeypatch, pinned_mode, working_mode, accepted):
    scaffold, case = kit_case(tmp_path, monkeypatch, "style", mode=pinned_mode)
    original_lstat = os.lstat
    members = {case["root"] / name for name in case["required"]}

    def lstat(path):
        info = original_lstat(path)
        if Path(path) in members:
            return SimpleNamespace(st_mode=stat.S_IFREG | working_mode,
                                   st_nlink=info.st_nlink,
                                   st_file_attributes=getattr(info, "st_file_attributes", 0))
        return info

    # A local os facade leaves pathlib and pytest's actual host platform untouched.
    monkeypatch.setattr(scaffold, "os", SimpleNamespace(name="posix", lstat=lstat))
    if accepted:
        scaffold.verify_kit_payload(case["root"], case["revision"], "style")
    else:
        with pytest.raises(SystemExit, match="executable mode differs"):
            scaffold.verify_kit_payload(case["root"], case["revision"], "style")


def test_windows_mode_metadata_does_not_reject_valid_pinned_executable(tmp_path, monkeypatch):
    scaffold, case = kit_case(tmp_path, monkeypatch, "style", mode="100755")
    monkeypatch.setattr(scaffold, "os", SimpleNamespace(name="nt", lstat=os.lstat))
    scaffold.verify_kit_payload(case["root"], case["revision"], "style")
