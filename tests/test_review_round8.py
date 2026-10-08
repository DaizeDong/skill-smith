"""Generated regressions for visibility consumers, worktrees and emitted command safety."""
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/skill-smith/scripts"
sys.path.insert(0, str(ROOT / "tools"))
from make_fixtures import (config_initializer_destination, fleet_inventory_fixture,
                           workflow_visibility_fixture, write_json)
from test_review_round4 import consumer, config_env, invoke

spec = importlib.util.spec_from_file_location("fleet_revision8_test", SCRIPTS / "fleet_check.py")
fc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fc)


def observe(monkeypatch, fixture, live):
    calls = {"visibility": [], "listing": []}

    def visibility(self, slug):
        calls["visibility"].append(slug)
        return live, "synthetic live observation" if live else "synthetic outage"

    def listing(slug, *args, **kwargs):
        calls["listing"].append(slug)
        return fixture["workflows"], ""

    monkeypatch.setattr(fc.VisibilityOracle, "_ask_gh", visibility)
    monkeypatch.setattr(fc, "remote_workflow_files", listing)
    monkeypatch.setattr(fc, "remote_guard_coverage", lambda *a: ([], ""))
    return calls


def test_live_public_reaches_workflow_and_ci_despite_private_cache(tmp_path, monkeypatch):
    fixture = workflow_visibility_fixture(tmp_path)
    calls = observe(monkeypatch, fixture, "PUBLIC")
    workflow = fc.check_workflow(str(fixture["cache"]), fixture["slugs"], str(tmp_path))
    assert [(state, name) for state, name, detail in workflow.rows] == [(fc.FAIL, fixture["slug"])]
    write_json(fixture["cache"], {fixture["slug"]: "PRIVATE"})
    targets = fc.ci_targets(workflow, str(fixture["cache"]), fixture["slugs"], 5)
    assert targets == [(fixture["slug"], fixture["workflows"], "", "PUBLIC")]
    assert calls == {"visibility": [fixture["slug"]], "listing": [fixture["slug"]]}


def test_live_private_avoids_public_policy_and_stays_private_for_ci(tmp_path, monkeypatch):
    fixture = workflow_visibility_fixture(tmp_path, "PUBLIC")
    calls = observe(monkeypatch, fixture, "PRIVATE")
    workflow = fc.check_workflow(str(fixture["cache"]), fixture["slugs"], str(tmp_path))
    assert workflow.count(fc.FAIL) == 0
    targets = fc.ci_targets(workflow, str(fixture["cache"]), fixture["slugs"], 5)
    assert targets == [(fixture["slug"], fixture["workflows"], "", "PRIVATE")]
    assert calls["visibility"] == [fixture["slug"]]


@pytest.mark.parametrize("cache_mode", ["expired", "missing", "unlisted"])
def test_unknown_visibility_stays_visible_and_ci_still_observes(tmp_path, monkeypatch, cache_mode):
    fixture = workflow_visibility_fixture(tmp_path, "PRIVATE", age_days=30)
    if cache_mode == "missing":
        fixture["cache"].unlink()
    elif cache_mode == "unlisted":
        write_json(fixture["cache"], {})
    observe(monkeypatch, fixture, None)
    workflow = fc.check_workflow(str(fixture["cache"]), fixture["slugs"], str(tmp_path))
    assert any(state == fc.UNKNOWN and name == fixture["slug"] for state, name, _ in workflow.rows)
    targets = fc.ci_targets(workflow, str(fixture["cache"]), fixture["slugs"], 5)
    assert targets == [(fixture["slug"], fixture["workflows"], "", "UNKNOWN")]


@pytest.mark.parametrize("cached", ["PUBLIC", "PRIVATE"])
def test_recent_offline_fallback_preserves_visibility_without_observing_remote(tmp_path, cached):
    fixture = workflow_visibility_fixture(tmp_path, cached)
    workflow = fc.check_workflow(str(fixture["cache"]), fixture["slugs"], str(tmp_path), offline=True)
    targets = fc.ci_targets(workflow, str(fixture["cache"]), fixture["slugs"], 5, offline=True)
    assert len(targets) == 1 and targets[0][0] == fixture["slug"] and targets[0][3] == cached
    assert targets[0][1] is None
    assert workflow.count(fc.PASS) == 0


def test_inventory_includes_genuine_linked_worktrees_and_excludes_false_markers(tmp_path):
    fixture = fleet_inventory_fixture(tmp_path)
    repos = fc.local_repos(str(fixture["fleet"]))
    assert repos == {"alpha": str(fixture["ordinary"]), "beta": str(fixture["linked"])}
    assert fc.repo_slugs(repos) == {fixture["slug"]: str(fixture["ordinary"])}
    assert fc.repo_slugs({"beta": repos["beta"]}) == {fixture["slug"]: str(fixture["linked"])}


def file_snapshot(root):
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("child", ["secrets", "tools"])
@pytest.mark.parametrize("force", [False, True])
def test_initializer_rejects_child_escape_before_any_write(consumer, config_env, tmp_path, child, force):
    selected, target = config_initializer_destination(tmp_path, consumer["consumer"], child)
    selected_before, target_before = file_snapshot(selected), file_snapshot(target)
    result = invoke(consumer, "init_config.py", config_env, "--out", str(selected), *(["--force"] if force else []))
    assert result.returncode != 0, result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr
    assert file_snapshot(selected) == selected_before
    assert file_snapshot(target) == target_before


def test_initializer_rejects_contained_child_alias_before_any_write(consumer, config_env, tmp_path):
    selected, target = config_initializer_destination(tmp_path, consumer["consumer"], contained=True)
    selected_before, target_before = file_snapshot(selected), file_snapshot(target)
    result = invoke(consumer, "init_config.py", config_env, "--out", str(selected), "--force")
    assert result.returncode != 0, result.stdout + result.stderr
    assert "link or reparse alias" in result.stdout + result.stderr
    assert file_snapshot(selected) == selected_before
    assert file_snapshot(target) == target_before


def test_scaffold_emitted_validator_commands_run_from_documented_caller(consumer):
    result = subprocess.run([sys.executable, str(SCRIPTS / "scaffold_skill.py"), consumer["name"],
                             "--with-config", "--force", "--out-dir", str(consumer["consumer"].parent)],
                            cwd=SCRIPTS.parent, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    commands = [re.sub(r"^\d+\w?\)\s*", "", line.strip()) for line in result.stdout.splitlines()
                if re.search(r"python .*check_(?:config_)?conformance\.py", line)]
    assert len(commands) == 2, result.stdout
    for command in commands:
        argv = shlex.split(command)
        assert Path(argv[2]) == consumer["consumer"], command
        expected_tail = [] if Path(argv[1]).name == "check_config_conformance.py" else ["--stage", "draft"]
        assert argv[3:] == expected_tail, command
        executed = subprocess.run([sys.executable, *argv[1:]], cwd=SCRIPTS.parent,
                                  capture_output=True, text=True, encoding="utf-8", timeout=120)
        output = executed.stdout + executed.stderr
        assert "can't open file" not in output and "Traceback" not in output, output
        if Path(argv[1]).name == "check_config_conformance.py":
            assert executed.returncode == 2 and "static_not_executed" in output, output
            assert "[NOT_RUN] E3" in output and "[NOT_RUN] E4" in output and "[NOT_RUN] E5" in output
        else:
            assert executed.returncode in (0, 1) and "conformance:" in output.lower(), output
