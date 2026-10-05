"""Native spelling aliases must not grant access through escaping directory links."""
import os

import pytest

from skill_smith import catalog, paths
from tools.make_fixtures import catalog_path_alias_fixture, directory_link, windows_short_path


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows 8.3 path spelling")
def test_windows_short_root_resolves_the_same_catalog(tmp_path):
    case = catalog_path_alias_fixture(tmp_path)
    short = windows_short_path(case["approved"])
    if str(short).casefold() == str(case["approved"]).casefold():
        if os.environ.get("SKILL_SMITH_REQUIRE_SHORT_PATH") == "1":
            pytest.fail("Windows package CI requires a volume with 8.3 path aliases")
        pytest.skip("8.3 aliases are disabled for the generated directory")
    result = paths.probe(short / "skills/demo", [tmp_path / "missing-approved-root", short])
    assert result["resolution"] == "resolved", result
    assert result["resolved_path"] == os.path.realpath(case["approved"] / "skills/demo")
    snapshot = catalog.discover({"skill_roots": [{"path": str(short / "skills")}]})
    assert snapshot["coverage"]["skill_roots"]["status"] == "checked", snapshot["problems"]
    assert len(snapshot["records"]) == 1
    assert snapshot["records"][0]["entrypoints"][0]["name"] == "demo"


def test_approved_root_link_does_not_authorize_its_outside_target(tmp_path):
    case = catalog_path_alias_fixture(tmp_path)
    alias = tmp_path / "unapproved-root-link"
    directory_link(alias, case["outside"])
    result = paths.probe(alias / "skills/other", [alias])
    assert result["resolution"] == "outside_approved_roots", result


def test_child_link_escape_requires_its_target_to_be_explicitly_approved(tmp_path):
    case = catalog_path_alias_fixture(tmp_path)
    alias = case["approved"] / "child-link"
    directory_link(alias, case["outside"])
    result = paths.probe(alias / "skills/other", [case["approved"]])
    assert result["resolution"] == "outside_approved_roots", result
    allowed = paths.probe(alias / "skills/other", [case["approved"], case["outside"]])
    assert allowed["resolution"] == "resolved", allowed
