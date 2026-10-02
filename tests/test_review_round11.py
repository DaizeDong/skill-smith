"""Synthetic source11 regressions for conformance, publication routes and input boundaries."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/skill-smith/scripts"
sys.path[:0] = [str(ROOT / "tools"), str(SCRIPTS)]
from make_fixtures import (
    review10_route_query, review10_routes, review11_conformance, review11_layout,
    review11_metadata_cases, review11_skill, review11_thresholds,
)


def module(name):
    spec = importlib.util.spec_from_file_location(name + "_review11", SCRIPTS / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@pytest.mark.parametrize("case", [
    "clean", "empty", "zero", "summary_only", "rows_only", "count_mismatch", "contradictory",
    "malformed", "duplicate_summary", "duplicate_rows", "fail_stdout", "fail_stderr",
    "warn_stdout", "warn_stderr", "plain_warning", "timeout", "nonzero",
    "plain_stdout_warning", "bare_fail", "bare_warn", "malformed_row", "unexplained_stderr",
])
def test_fleet_conformance_requires_measured_consistent_evidence(tmp_path, monkeypatch, case):
    fleet = module("fleet_check")
    layout = review11_layout(tmp_path)
    rc, stdout, stderr, expected = review11_conformance(case)
    monkeypatch.setattr(fleet, "run", lambda *args, **kwargs: (rc, stdout, stderr))
    result = fleet.check_conformance({"synthetic-tool": str(layout["consumer"])}, 1)
    assert [row[0] for row in result.rows] == [expected], result.rows
    if "fail_" in case or "warn_" in case or case == "plain_warning":
        assert "synthetic" in result.rows[0][2], result.rows
    if expected != "PASS":
        assert result.count("PASS") == 0


@pytest.mark.parametrize("scenario,allowed", [
    ("private", True), ("private_override", True), ("public_push", False),
    ("unknown_push", False), ("multiple_push", False), ("push_default", False),
    ("branch_push", False), ("branch_remote", False), ("missing_route", False),
    ("local_route", False), ("config_failure", False), ("private_multiple", True),
    ("unknown_visibility", False), ("public_origin", False),
])
def test_inverse_data_audit_checks_all_effective_publication_destinations(
        tmp_path, monkeypatch, scenario, allowed):
    fleet = module("fleet_check")
    layout = review11_layout(tmp_path)
    fixture = review10_routes(scenario)
    if scenario == "private_multiple":
        fixture["routes"]["origin"].append("git@github.com:AcmeCorp/private-backup.git")
        fixture["visibility"]["acmecorp/private-backup"] = "PRIVATE"
    elif scenario == "unknown_visibility":
        fixture["routes"]["origin"].append("git@github.com:AcmeCorp/unknown-config.git")
    elif scenario == "public_origin":
        fixture["origin"] = "https://github.com/AcmeCorp/public-tool.git"
    monkeypatch.setattr(fleet, "load_datadir", lambda *args: SimpleNamespace(
        resolve_data_dir=lambda name, create=False: layout["data"]))
    monkeypatch.setattr(fleet, "in_git_worktree", lambda path: (True, str(layout["data"].parent)))
    queries, prefetched, observed = [], [], []
    def query(args, **kwargs):
        queries.append(args)
        return review10_route_query(fixture, args)
    def visibility(slug):
        observed.append(slug)
        return fixture["visibility"].get(slug, "UNKNOWN"), "synthetic oracle"
    oracle = SimpleNamespace(error="", map_age=lambda: (0, None),
                             prefetch=lambda slugs: prefetched.extend(slugs), visibility=visibility)
    monkeypatch.setattr(fleet, "run", query)
    result = fleet.check_data_boundary("unused", {"synthetic-tool": str(layout["consumer"])},
                                       offline=True, timeout=1, oracle=oracle)
    assert [row[0] for row in result.rows] == ["PASS" if allowed else "FAIL"], result.rows
    if allowed:
        assert "PRIVATE" in result.rows[0][2] and "acmecorp/private-config" in result.rows[0][2]
        assert "push" in result.rows[0][2].lower()
        assert any("--push" in args for args in queries)
        assert set(observed) <= set(prefetched)
    else:
        assert result.count("PASS") == 0
    if scenario == "private_multiple":
        assert "acmecorp/private-backup" in observed


@pytest.mark.parametrize("tool", ["set_repo_metadata", "check_remote_conformance"])
@pytest.mark.parametrize("case", list(review11_metadata_cases()))
def test_metadata_homepage_is_an_explicit_supported_github_identity(tool, case):
    target = module(tool)
    homepage, expected = review11_metadata_cases()[case]
    assert target.owner_repo_from_homepage(homepage) == (expected or (None, None))


@pytest.mark.parametrize("tool", ["set_repo_metadata", "check_remote_conformance"])
@pytest.mark.parametrize("case", ["https", "lookalike", "foreign_path", "deep_path", "wrong_type"])
@pytest.mark.parametrize("explicit", [False, True])
def test_metadata_target_validation_precedes_remote_transport(monkeypatch, tool, case, explicit):
    target = module(tool)
    homepage, parsed = review11_metadata_cases()[case]
    monkeypatch.setattr(target, "load_plugin", lambda path: {
        "name": "synthetic-tool", "homepage": homepage, "description": "Synthetic records.",
        "keywords": ["synthetic", "skill"],
    })
    argv = [tool, "unused"]
    if explicit:
        argv += ["--owner", "AcmeCorp", "--repo", "explicit-tool"]
    monkeypatch.setattr(sys, "argv", argv)
    calls = []
    if tool == "set_repo_metadata":
        monkeypatch.setattr(target, "gh_path", lambda: "synthetic-gh")
        def transport(args, input_text=None):
            calls.append(args)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        monkeypatch.setattr(target, "run_gh", transport)
    else:
        def transport(owner, repo):
            calls.append((owner, repo))
            return {"topics": target.BASE9 + ["synthetic"], "description": "Synthetic records.",
                    "homepage": "https://github.com/%s/%s" % (owner, repo)}, None
        monkeypatch.setattr(target, "fetch_remote", transport)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        rc = target.main()
    expected_target = ("AcmeCorp", "explicit-tool") if explicit else parsed
    if expected_target is None:
        assert rc == 2 and not calls, (rc, calls)
    else:
        assert rc == 0 and calls, (rc, calls)
        if tool == "set_repo_metadata":
            slug = "/".join(expected_target)
            assert all(slug in str(args) for args in calls), calls
        else:
            assert calls == [expected_target]


@pytest.mark.parametrize("candidate", [False, True])
@pytest.mark.parametrize("threshold", review11_thresholds()["invalid"])
def test_dedup_rejects_invalid_threshold_before_inventory(monkeypatch, threshold, candidate, capsys):
    target = module("dedup_check")
    calls = []
    def inventory(*args):
        calls.append(args)
        return [SimpleNamespace(owner="", name=name, desc="Summarize synthetic financial records")
                for name in ("synthetic-first", "synthetic-second")], []
    monkeypatch.setattr(target, "library_inventory", inventory)
    argv = ["dedup_check", "--skills-dir", "unused", "--installed-plugins", "unused",
            "--threshold=" + threshold]
    if candidate:
        argv += ["--desc", "Summarize synthetic financial records"]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as failure:
        target.main()
    output = capsys.readouterr()
    assert failure.value.code == 2
    assert not calls and "threshold" in output.err and "DEDUP: OK" not in output.out


@pytest.mark.parametrize("candidate", [False, True])
@pytest.mark.parametrize("threshold", review11_thresholds()["valid"])
def test_dedup_supported_thresholds_keep_identical_overlap(monkeypatch, threshold, candidate, capsys):
    target = module("dedup_check")
    monkeypatch.setattr(target, "library_inventory", lambda *args: (
        [SimpleNamespace(owner="", name=name, desc="Summarize synthetic financial records")
         for name in ("synthetic-first", "synthetic-second")], []))
    argv = ["dedup_check", "--skills-dir", "unused", "--installed-plugins", "unused",
            "--threshold=" + threshold]
    if candidate:
        argv += ["--desc", "Summarize synthetic financial records"]
    monkeypatch.setattr(sys, "argv", argv)
    assert target.main() == 1
    assert "DEDUP: FAIL" in capsys.readouterr().out


@pytest.mark.parametrize("root_layout", [False, True])
@pytest.mark.parametrize("case", [
    "valid", "quoted", "block", "empty", "whitespace", "no_frontmatter", "missing_name",
    "missing_description", "empty_description", "collection", "duplicate", "no_body",
    "blank_body", "comment_body", "unclosed", "unreadable",
])
def test_g6_requires_readable_metadata_and_instruction_body(tmp_path, monkeypatch, case, root_layout):
    target = module("check_conformance")
    skill = review11_skill(tmp_path, case, root_layout)
    calls = []
    def scanner(args, **kwargs):
        assert Path(args[1]).name in ("pii_guard.py", "data_boundary.py", "dash_guard.py"), args
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="synthetic scanner clean", stderr="")
    monkeypatch.setattr(target.subprocess, "run", scanner)
    if case == "unreadable":
        real_read = target.read
        monkeypatch.setattr(target, "read", lambda path: None if Path(path) == skill else real_read(path))
    with contextlib.redirect_stdout(io.StringIO()):
        rc = target.main(str(tmp_path))
    assert len(calls) == 3
    valid = case in ("valid", "quoted", "block")
    assert rc == (0 if valid else 1), target.results
    content_rows = [(name, ok, detail) for name, ok, detail in target.results
                    if name.startswith("SKILL.md content")]
    assert len(content_rows) == 1 and content_rows[0][1] is valid, target.results
    if not valid:
        assert not any(ok is True and (name.startswith("SKILL.md size")
                                      or name.startswith("shard pointers"))
                       for name, ok, detail in target.results), target.results


@pytest.mark.parametrize("case", ["empty", "unreadable", "missing_description"])
@pytest.mark.parametrize("entry", ["check_skill_md_size", "check_shard_pointers"])
def test_direct_g6_cost_and_pointer_entrypoints_do_not_clear_unusable_skills(
        tmp_path, monkeypatch, case, entry):
    target = module("check_conformance")
    skill = review11_skill(tmp_path, case)
    if case == "unreadable":
        real_read = target.read
        monkeypatch.setattr(target, "read", lambda path: None if Path(path) == skill else real_read(path))
    getattr(target, entry)(str(tmp_path))
    assert any(ok is False for name, ok, detail in target.results), target.results
    assert not any(ok is True for name, ok, detail in target.results), target.results
