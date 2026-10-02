"""Synthetic source12 regressions for host binding, YAML validity and branch queries."""
import builtins
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/skill-smith/scripts"
sys.path[:0] = [str(ROOT / "tools"), str(SCRIPTS)]
from make_fixtures import review12_frontmatter_cases, review12_remote_fixture, review12_skill


def module(name):
    spec = importlib.util.spec_from_file_location(name + "_review12", SCRIPTS / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@pytest.mark.parametrize("tool", ["set_repo_metadata", "check_remote_conformance"])
@pytest.mark.parametrize("host", review12_remote_fixture()["hosts"])
def test_remote_metadata_targets_github_with_inherited_host(monkeypatch, tool, host):
    target = module(tool)
    fixture = review12_remote_fixture()
    original = {"SYNTHETIC_KEEP": "preserved"}
    if host is not None:
        original["GH_HOST"] = host
    monkeypatch.setattr(target.os, "environ", dict(original))
    monkeypatch.setattr(target.shutil, "which", lambda name: "synthetic-gh")
    monkeypatch.setattr(target, "load_plugin", lambda path: {
        "name": fixture["repo"], "homepage": fixture["homepage"],
        "description": fixture["description"], "keywords": ["synthetic", "skill"],
    })
    monkeypatch.setattr(sys, "argv", [tool, "unused"])
    calls = []
    def transport(args, **kwargs):
        environment = kwargs.get("env", os.environ)
        assert environment.get("GH_HOST") == "github.com"
        assert [key for key in environment if key.upper() == "GH_HOST"] == ["GH_HOST"]
        calls.append(args)
        response = {"repositoryTopics": target.BASE9 + ["synthetic"],
                    "description": fixture["description"], "homepageUrl": fixture["homepage"]}
        return SimpleNamespace(returncode=0, stdout=json.dumps(response), stderr="")
    monkeypatch.setattr(target.subprocess, "run", transport)
    assert target.main() == 0
    assert len(calls) == (3 if tool == "set_repo_metadata" else 1)
    assert dict(os.environ) == original
    assert all(fixture["owner"] + "/" + fixture["repo"] in str(args) for args in calls)


@pytest.mark.parametrize("case", list(review12_frontmatter_cases()))
def test_frontmatter_validates_complete_safe_yaml_mapping(case):
    target = module("budget_check")
    fixture = review12_frontmatter_cases()[case]
    assert target.parse_frontmatter(fixture["text"]) == fixture["expected"]


@pytest.mark.parametrize("case", list(review12_frontmatter_cases()))
def test_invalid_frontmatter_cannot_enter_g6_or_inventory(tmp_path, case):
    conformance = module("check_conformance")
    budget = module("budget_check")
    path = review12_skill(tmp_path, case)
    name, description = review12_frontmatter_cases()[case]["expected"]
    measured = conformance.check_skill_md_content(str(tmp_path))
    valid_g6 = name is not None and description is not None
    assert (str(path) in measured) is valid_g6
    assert len(conformance.results) == 1
    assert conformance.results[0][1] is valid_g6
    rows, problems = budget.skill_directory_rows(str(tmp_path / "skills"), lambda path: budget.LOCAL)
    assert len(rows) == (1 if description is not None else 0)
    assert bool(problems) is (description is None)


def test_missing_yaml_never_certifies_metadata(tmp_path, monkeypatch):
    target = module("budget_check")
    conformance = module("check_conformance")
    path = review12_skill(tmp_path, "plain")
    original_import = builtins.__import__
    def without_yaml(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("Synthetic unavailable YAML parser")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", without_yaml)
    assert target.parse_frontmatter(path.read_text(encoding="utf-8")) == (None, None)
    assert conformance.check_skill_md_content(str(tmp_path)) == {}
    assert any(ok is False for _, ok, _ in conformance.results)
    rows, problems = target.skill_directory_rows(str(tmp_path / "skills"), lambda path: target.LOCAL)
    assert not rows and problems


@pytest.mark.parametrize("branch", review12_remote_fixture()["branches"])
def test_default_branch_query_preserves_complete_ci_inventory(monkeypatch, branch):
    fleet = module("fleet_check")
    fixture = review12_remote_fixture()
    slug = fixture["owner"] + "/" + fixture["repo"]
    calls = []
    def transport(args, **kwargs):
        endpoint = args[2]
        calls.append(endpoint)
        if endpoint == "repos/" + slug:
            return 0, branch + "\n", ""
        parsed = urlsplit(endpoint)
        assert parsed.path == "repos/" + slug + "/contents/.github/workflows"
        if parse_qs(parsed.query) == {"ref": [branch]} and not parsed.fragment:
            return 0, "\n".join(fixture["workflows"]), ""
        return 0, "\n".join(fixture["workflows"][:-1]), ""
    monkeypatch.setattr(fleet, "run", transport)
    monkeypatch.setattr(fleet.shutil, "which", lambda name: "synthetic-gh")
    monkeypatch.setattr(fleet, "remote_guard_coverage",
                        lambda *args: (list(fleet.GUARD_WORKFLOWS), ""))
    oracle = SimpleNamespace(error="", map={slug: "PUBLIC"}, _mapped=lambda slug: "PUBLIC",
                             prefetch=lambda slugs: None, visibility=lambda slug: ("PUBLIC", ""))
    observed = fleet.check_workflow("unused", {slug: "unused"}, "unused",
                                    timeout=1, oracle=oracle)
    assert observed.all_remote_workflows == {slug: sorted(fixture["workflows"])}
    targets = fleet.ci_targets(observed, "unused", {slug: "unused"}, 1)
    assert targets == [(slug, sorted(fixture["workflows"]), "", "PUBLIC")]
    assert len(calls) == 2


@pytest.mark.parametrize("tool", ["set_repo_metadata", "check_remote_conformance"])
@pytest.mark.parametrize("owner,repo,accepted", review12_remote_fixture()["explicit_targets"])
def test_explicit_repository_arguments_cannot_select_a_foreign_host(
        monkeypatch, tool, owner, repo, accepted):
    target = module(tool)
    fixture = review12_remote_fixture()
    monkeypatch.setattr(target, "load_plugin", lambda path: {})
    monkeypatch.setattr(target.shutil, "which", lambda name: "synthetic-gh")
    monkeypatch.setattr(sys, "argv", [tool, "--owner=" + owner, "--repo=" + repo])
    calls = []
    def transport(args, **kwargs):
        calls.append(args)
        response = {"repositoryTopics": target.BASE9 + ["synthetic"],
                    "description": fixture["description"], "homepageUrl": fixture["homepage"]}
        return SimpleNamespace(returncode=0, stdout=json.dumps(response), stderr="")
    monkeypatch.setattr(target.subprocess, "run", transport)
    assert target.main() == (0 if accepted else 2)
    assert bool(calls) is accepted


def test_frontmatter_block_delimiter_cannot_supply_g6_instruction_body(tmp_path):
    target = module("check_conformance")
    review12_skill(tmp_path, "description_delimiter", include_body=False)
    assert target.check_skill_md_content(str(tmp_path)) == {}
    assert len(target.results) == 1 and target.results[0][1] is False


def test_trim_uses_the_same_frontmatter_boundary():
    target = module("trim_descriptions")
    fixture = review12_frontmatter_cases()["description_delimiter"]
    name, description = fixture["expected"]
    target.validate_replacement(fixture["text"], name, description)
