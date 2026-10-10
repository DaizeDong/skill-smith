"""Skill-root walks skip VCS/cache trees and observe each physical entry once.

A skill that is the root of its own repository used to have its whole .git
object store probed entry by entry, and the same target mounted under two
skill roots was probed twice. Inputs are generated synthetic trees.
"""
import json
import os
from collections import Counter
from pathlib import Path

import pytest

from skill_smith import catalog, paths
from tools.make_fixtures import skill, text_file

EXCLUDED = (".git", "node_modules", "__pycache__", ".venv", ".pytest_cache")


def _link_dir(link, target):
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


def _repo_root_skill(path):
    """A skill whose directory is also a repository root with bulky tool trees."""
    skill(path, name="alpha")
    skill(path / "nested" / "beta", name="beta")
    for bucket in ("aa", "bb", "cc"):
        for index in range(5):
            text_file(path / ".git" / "objects" / bucket / f"obj{index}", "synthetic\n")
    text_file(path / ".git" / "HEAD", "ref: refs/heads/main\n")
    # Decoys: a SKILL.md inside these trees is never an installed skill.
    skill(path / ".git" / "hooks" / "decoy", name="decoy-git")
    skill(path / "node_modules" / "pkg", name="decoy-node")
    skill(path / "__pycache__" / "cached", name="decoy-pycache")
    skill(path / ".venv" / "lib" / "tool", name="decoy-venv")
    text_file(path / ".pytest_cache" / "v" / "lastfailed", "{}\n")
    return path


def _probed_paths(monkeypatch):
    seen = []
    original = catalog.probe

    def recording(path, roots, **kwargs):
        seen.append(Path(path))
        return original(path, roots, **kwargs)

    monkeypatch.setattr(catalog, "probe", recording)
    return seen


def test_walk_never_enters_vcs_or_cache_directories(tmp_path, monkeypatch):
    _repo_root_skill(tmp_path / "skills" / "alpha")
    seen = _probed_paths(monkeypatch)
    snapshot = catalog.discover({"skill_roots": [
        {"path": str(tmp_path / "skills"), "client": "codex", "max_depth": 8}]})

    entered = sorted({str(p) for p in seen if set(p.parts) & set(EXCLUDED)})
    assert entered == [], "walk descended into excluded trees: " + json.dumps(entered[:5])
    names = sorted(r["name"] for r in snapshot["records"])
    assert names == ["alpha", "beta"]
    assert snapshot["coverage"]["skill_roots"]["status"] == "checked", snapshot["problems"]


def test_excluded_names_match_case_insensitively(tmp_path):
    root = tmp_path / "skills"
    skill(root / "gamma", name="gamma")
    skill(root / "gamma" / "Node_Modules" / "pkg", name="decoy-node")
    snapshot = catalog.discover({"skill_roots": [{"path": str(root), "max_depth": 4}]})
    assert sorted(r["name"] for r in snapshot["records"]) == ["gamma"]


def test_one_physical_target_is_observed_once_but_mounted_twice(tmp_path, monkeypatch):
    target = _repo_root_skill(tmp_path / "repos" / "alpha")
    first, second = tmp_path / "home" / "claude-skills", tmp_path / "home" / "agents-skills"
    _link_dir(first / "alpha", target)
    _link_dir(second / "alpha", target)
    calls = Counter()
    original = os.path.realpath

    def counting(path, *args, **kwargs):
        resolved = original(path, *args, **kwargs)
        calls[os.path.normcase(resolved)] += 1
        return resolved

    monkeypatch.setattr(os.path, "realpath", counting)
    request = {"approved_roots": [str(tmp_path)], "skill_roots": [
        {"path": str(first), "client": "claude", "namespace": "claude-user", "max_depth": 8},
        {"path": str(second), "client": "codex", "namespace": "shared-user", "max_depth": 8}]}
    snapshot = catalog.discover(request)

    physical = os.path.normcase(original(target))
    inside = {k: v for k, v in calls.items() if k != physical and k.startswith(physical + os.sep)}
    assert inside, "the walk observed nothing below the shared target"
    repeated = {k: v for k, v in inside.items() if v > 1}
    assert repeated == {}, "physical entries observed more than once: " + json.dumps(
        sorted(repeated.items())[:5])
    # Sharing the observation does not merge the two installations.
    mounts = sorted((m["client"], Path(m["path"]).relative_to(tmp_path / "home").as_posix())
                    for r in snapshot["records"] for m in r["mounts"])
    assert mounts == [
        ("claude", "claude-skills/alpha"), ("claude", "claude-skills/alpha/nested/beta"),
        ("codex", "agents-skills/alpha"), ("codex", "agents-skills/alpha/nested/beta")]
    for record in snapshot["records"]:
        assert record["status"]["resolved"] == "yes"
        assert record["resolved_path"] and os.path.normcase(record["resolved_path"]).startswith(physical)


@pytest.mark.parametrize("case", ["directory", "file", "missing", "escaping_link"])
def test_memoized_probe_matches_a_fresh_probe(tmp_path, case):
    approved = tmp_path / "approved"
    outside = skill(tmp_path / "outside" / "x")
    target = {"directory": skill(approved / "d"),
              "file": approved / "d" / "SKILL.md",
              "missing": approved / "absent",
              "escaping_link": approved / "link"}[case]
    skill(approved / "d")
    if case == "escaping_link":
        _link_dir(target, outside)
    memo = {}
    fresh = paths.probe(target, [str(approved)])
    first = paths.probe(target, [str(approved)], memo=memo, physical_key=("k", target.name))
    again = paths.probe(target, [str(approved)], memo=memo, physical_key=("k", target.name))
    assert fresh == first == again
    # Containment is never cached: a wider root sees the same facts differently.
    wider = paths.probe(target, [str(tmp_path)], memo=memo, physical_key=("k", target.name))
    assert wider == paths.probe(target, [str(tmp_path)])
