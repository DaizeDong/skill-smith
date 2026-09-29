"""Generate synthetic acceptance-contract fixtures; never imports runtime data."""
import hashlib
import json
import argparse
from pathlib import Path
import subprocess
import sys


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def acceptance_bundle(root, candidate_sha256):
    """A simulated measurement bundle for gate tests, not evidence of real skill quality."""
    root = Path(root)
    task_ids = [f"synthetic-task-{i}" for i in range(4)]
    task_hashes = {task: hashlib.sha256(task.encode()).hexdigest() for task in task_ids}
    queries = [{"id": f"synthetic-query-{i}", "expected": i % 2 == 0,
                "query_sha256": hashlib.sha256(f"synthetic query {i}".encode()).hexdigest()}
               for i in range(6)]
    policy = {"schema": 1, "brief": {"task": "Transform synthetic records", "inputs": ["synthetic JSON"],
              "deliverables": ["validated JSON"], "platforms": ["test harness"], "proof_tasks": task_ids},
              "min_lift": 0.05, "trigger_threshold": 0.9, "queries": queries,
              "training_query_sha256": [], "proof_task_sha256": task_hashes, "not_applicable": []}
    policy_sha = write_json(root / "policy.json", policy)
    common = {"schema": 1, "candidate_sha256": candidate_sha256, "policy_sha256": policy_sha,
              "measurement": "measured", "provenance": {"evaluator": "synthetic-evaluator",
              "request_id": "synthetic-request", "backend": "synthetic-backend", "fixture": True}}
    g1 = dict(common, pairs=[{"id": task, "input_sha256": task_hashes[task],
                             "without_skill": 0.25, "with_skill": 0.75} for task in task_ids])
    g2 = dict(common, held_out=True, trials=[dict(q, triggered=q["expected"]) for q in queries])
    gates = {}
    for gate in ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G6b"):
        body = dict(g1 if gate == "G1" else g2 if gate == "G2" else common,
                    gate=gate, status="passed", exit_code=0)
        filename = gate + ".json"
        gates[gate] = {"path": filename, "sha256": write_json(root / filename, body)}
    manifest = {"schema": 1, "candidate_sha256": candidate_sha256, "policy_sha256": policy_sha, "gates": gates}
    write_json(root / "manifest.json", manifest)
    return policy, manifest, policy_sha


def config_lifecycle(root):
    """Generate an offline skill whose blank template honestly fails readiness."""
    root = Path(root)
    write_json(root / '.claude-plugin/plugin.json', {'name': 'acme-config-tool'})
    texts = {
        '.gitignore': 'secrets/\n*.env\n',
        'CONFIG.md': 'registry.json: schema_version int, required_root string required.\n',
        'README.md': '## Config\n',
        'README_CN.md': '## 配置\n',
        'scripts/init_config.py': '''import argparse, json
from pathlib import Path
parser = argparse.ArgumentParser()
parser.add_argument('--out', required=True)
root = Path(parser.parse_args().out)
root.mkdir(parents=True, exist_ok=True)
(root / 'registry.json').write_text(json.dumps({'schema_version': 1, 'required_root': ''}) + '\\n', encoding='utf-8')
''',
        'scripts/verify_config.py': '''import json, os, sys
from pathlib import Path
root = Path(os.environ['ACME_CONFIG_TOOL_CONFIG']).resolve()
print('RESOLVED:', root)
data = json.loads((root / 'registry.json').read_text(encoding='utf-8'))
source = data.get('required_root', '')
if not source or not (Path(source) / 'source.txt').is_file():
    print('NOT READY: fill required_root with a synthetic source directory')
    sys.exit(1)
print('READY: synthetic source verified')
''',
        'scripts/exercise.py': '''import json, os
from pathlib import Path
root = Path(os.environ['ACME_CONFIG_TOOL_CONFIG'])
data = json.loads((root / 'registry.json').read_text(encoding='utf-8'))
print((Path(data['required_root']) / 'source.txt').read_text(encoding='utf-8'))
''',
    }
    discovery = ('ACME_CONFIG_TOOL_CONFIG env var; discovery order ~/.acme-config-tool-config fallback. '
                 'init_config.py then fill required_root, verify; switch configs.\n')
    for name in ('README.md', 'README_CN.md'):
        texts[name] += discovery
    for relative, content in texts.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
    return root


def config_probe(root, kind="directory"):
    """Generate a config-free target or ordinary file for applicability checks."""
    root = Path(root)
    if kind == "file":
        root.write_text("Synthetic ordinary file.\n", encoding="utf-8")
    elif kind == "directory":
        root.mkdir(parents=True)
        (root / "README.md").write_text("Synthetic standalone tool.\n", encoding="utf-8")
    return root


def ci_execution_fixture(scenario="executed", conclusion="success"):
    """Generate GitHub-shaped CI evidence, including missing execution cases."""
    run = {"conclusion": conclusion, "status": "completed", "databaseId": 41,
           "headSha": "a" * 40, "headBranch": "main", "createdAt": "2000-01-01T00:00:00Z"}
    step = {"number": 1, "status": "completed", "conclusion": "success"}
    jobs = {"jobs": [{"steps": [step], "runner_name": "synthetic-runner", "runner_id": 1}]}
    if scenario == "not_started":
        jobs = {"jobs": [{"steps": [], "runner_name": "", "runner_id": None}]}
    elif scenario == "empty":
        jobs = {"jobs": []}
    elif scenario == "skipped":
        step["conclusion"] = "skipped"
    elif scenario == "malformed_jobs":
        jobs = {"jobs": [None]}
    elif scenario == "missing_run_id":
        run.pop("databaseId")
    return [run], jobs


def scaffold_name_cases():
    """Synthetic display names with one hand-specified canonical identity."""
    return [("Acme Tool", "acme-tool"), ('Acme "Tool"', "acme-tool")]


def malformed_ci_run_listings():
    """Synthetic top-level schema violations for unobservable CI replies."""
    return [None, {"status": "completed"}, [None]]


def ci_step_evidence_cases(workflow_conclusion="success"):
    """Generate valid and invalid step status/conclusion combinations."""
    cases = []

    def add(name, status, conclusion, expected, omit=False, mixed=False):
        runs, jobs = ci_execution_fixture(conclusion=workflow_conclusion)
        step = {"number": 1, "status": status, "conclusion": conclusion}
        if omit:
            step.pop("conclusion")
        if mixed:
            step["number"] = 2
            jobs["jobs"][0]["steps"].append(step)
        else:
            jobs["jobs"][0]["steps"] = [step]
        cases.append((name, runs, jobs, expected))

    add("completed-missing", "completed", None, "unknown", omit=True)
    for name, value in (("null", None), ("object", {}), ("list", []), ("number", 1),
                        ("boolean", True), ("empty", ""), ("unknown", "synthetic-result")):
        add("completed-" + name, "completed", value, "unknown")
    for status in ("queued", "in_progress"):
        add(status + "-terminal-conclusion", status, "success", "unknown")
        add(status + "-missing", status, None, "unknown", omit=True)
        add(status + "-null", status, None, "executed" if status == "in_progress" else "unknown")
    for conclusion in ("success", "failure", "neutral", "cancelled", "timed_out", "action_required"):
        add("completed-" + conclusion, "completed", conclusion, "executed")
    add("completed-skipped", "completed", "skipped", "unknown")
    add("valid-and-malformed", "completed", {}, "unknown", mixed=True)
    return cases


def ci_branch_evidence_cases(workflow_conclusion="success"):
    """Generate absent, malformed or contradictory branch provenance."""
    cases = []
    for name, value in (("missing", None), ("null", None), ("object", {}), ("list", []),
                        ("number", 1), ("boolean", True), ("empty", ""),
                        ("topic", "synthetic-development"), ("case", "Main"), ("padded", "main ")):
        runs, jobs = ci_execution_fixture(conclusion=workflow_conclusion)
        if name == "missing":
            runs[0].pop("headBranch")
        else:
            runs[0]["headBranch"] = value
        cases.append((name, runs, jobs))
    return cases


def config_companion(root, skill="acme-cold-tool", label="sibling", proven=True):
    """Generate a complete synthetic config shape, optionally with sibling ownership proof."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    write_json(root / "registry.json", {"schema_version": 1, "skill": skill, "tools": [], "fixture_id": label})
    (root / "tools").mkdir(exist_ok=True)
    (root / "secrets").mkdir(exist_ok=True)
    (root / ".gitignore").write_text("secrets/*\n*.env\n", encoding="utf-8")
    if proven:
        (root / ".companion").write_text(skill + "\n", encoding="utf-8")
    return root


def config_cold_start(root, topology):
    """Scaffold actual config assets into ordinary or linked synthetic Git worktrees."""
    root = Path(root)
    name = "acme-cold-tool"
    seed = root / "source location" / name
    seed.mkdir(parents=True)

    def git(cwd, *args):
        return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, timeout=60)

    git(seed, "init", "-q")
    (seed / ".fixture-seed").write_text("Synthetic cold-start seed.\n", encoding="utf-8")
    git(seed, "add", ".fixture-seed")
    git(seed, "-c", "user.name=Synthetic Fixture", "-c", "user.email=user1@example.com",
        "commit", "-m", "Initialize synthetic fixture")
    consumer = seed
    if topology == "linked":
        consumer = root / "linked location" / name
        consumer.parent.mkdir()
        git(seed, "worktree", "add", "--detach", str(consumer))
    elif topology != "ordinary":
        raise ValueError("Unsupported synthetic topology")
    scaffold = Path(__file__).resolve().parents[1] / "skills/skill-smith/scripts/scaffold_skill.py"
    subprocess.run([sys.executable, str(scaffold), name, "--with-config", "--force", "--out-dir", str(consumer.parent)],
                   cwd=root, check=True, capture_output=True, timeout=120)
    companion = config_companion(consumer.parent / (name + "-config"))
    caller = root / "unrelated caller"
    write_json(caller / ".claude-plugin/plugin.json", {"name": "synthetic-decoy"})
    return {"consumer": consumer, "companion": companion, "caller": caller, "name": name}


def config_legacy_decoy(consumer, companion):
    """Generate an obsolete resolver that must never replace a missing pinned kit."""
    path = Path(consumer) / "tools/datadir.py"
    path.parent.mkdir(exist_ok=True)
    path.write_text("def resolve_companion_root(skill):\n    return " + repr(str(companion)) + "\n", encoding="utf-8")
    return path


def fleet_writer_layout(root, topology):
    """Generate a Git consumer and companion for default report discovery."""
    import shutil
    from datetime import datetime, timezone

    root = Path(root)
    seed = root / "source" / "skill-smith"
    seed.mkdir(parents=True)

    def git(cwd, *args):
        return subprocess.run(["git", *args], cwd=cwd, check=True,
                              capture_output=True, timeout=60)

    git(seed, "init", "-q")
    (seed / "synthetic.txt").write_text("Generated fixture.\n", encoding="utf-8")
    git(seed, "add", "synthetic.txt")
    git(seed, "-c", "user.name=Synthetic Fixture", "-c", "user.email=user1@example.com",
        "commit", "-qm", "Initialize synthetic fixture")
    consumer = seed
    if topology == "linked":
        consumer = root / "linked" / "skill-smith"
        consumer.parent.mkdir()
        git(seed, "worktree", "add", "--detach", str(consumer))
    elif topology != "ordinary":
        raise ValueError("Unsupported synthetic topology")
    scripts = consumer / "skills/skill-smith/scripts"
    scripts.mkdir(parents=True)
    kit = consumer / "guards"
    (kit / "tools").mkdir(parents=True)
    (kit / ".git").write_text("gitdir: ../synthetic-kit-metadata\n", encoding="utf-8")
    shutil.copyfile(Path(__file__).resolve().parents[1] / "guards/tools/datadir.py",
                    kit / "tools/datadir.py")
    companion = consumer.parent / "skill-smith-config"
    (companion / "data").mkdir(parents=True)
    git(companion, "init", "-q")
    git(companion, "remote", "add", "origin", "https://github.com/AcmeCorp/skill-smith-config.git")
    (companion / ".companion").write_text("skill-smith\n", encoding="utf-8")
    visibility = root / "visibility.json"
    write_json(visibility, {"_refreshed": datetime.now(timezone.utc).isoformat(),
                            "AcmeCorp/skill-smith-config": "PRIVATE"})
    home = root / "home"
    home.mkdir()
    return {"consumer": consumer, "companion": companion, "scripts": scripts,
            "visibility": visibility, "home": home}


def conformance_scanner(root, case):
    """Generate scanner stand-ins to exercise the report wrapper, not PII detection."""
    cases = {
        "clean": ("pii_guard: clean (tree+history)", "", 0),
        "warn_stdout": ("WARN synthetic warning on stdout", "", 0),
        "warn_stderr": ("pii_guard: no blocking findings", "WARNING synthetic warning on stderr", 0),
        "cross_repo": ("CROSS-REPO synthetic-owner/synthetic-tool", "", 0),
        "history_debt": ("HISTORY-DEBT synthetic history finding", "", 0),
        "failure_stdout": ("BLOCK synthetic blocking finding", "", 7),
        "failure_empty": ("", "", 8),
    }
    stdout, stderr, code = cases[case]
    path = Path(root) / "guards/tools/pii_guard.py"
    path.write_text("import sys\nprint(" + repr(stdout) + ")\nprint(" + repr(stderr)
                    + ", file=sys.stderr)\nsys.exit(" + str(code) + ")\n", encoding="utf-8")
    return {"stdout": stdout, "stderr": stderr, "exit_code": code}


def config_schema_cases():
    """Generate declared-schema and malformed-input controls without real configuration."""
    marker = "synthetic-sensitive-marker"
    registry = {"schema_version": 1, "skill": "acme-cold-tool", "tools": []}
    member = {"slug": "example-tool", "installed": True}
    cases = []

    def add(name, value, field, valid=False):
        cases.append({"name": name, "raw": (json.dumps(value) + "\n").encode("utf-8"),
                      "field": field, "valid": valid, "marker": marker})

    for name, value in (("array", []), ("null", None), ("string", marker), ("boolean", True)):
        add("root_" + name, value, "registry.json")
    for field, values in (
        ("schema_version", [True, 1.0, "1", 2, None, marker]),
        ("skill", [marker, None, 1, []]),
        ("tools", [None, {}, marker]),
    ):
        missing = dict(registry)
        missing.pop(field)
        add(field + "_missing", missing, field)
        for index, value in enumerate(values):
            add(field + "_invalid_" + str(index), dict(registry, **{field: value}), field)
    entries_only = dict(registry, entries=[])
    entries_only.pop("tools")
    add("entries_cannot_replace_tools", entries_only, "tools")
    for name, value in (("null", None), ("string", marker), ("array", [])):
        add("member_" + name, dict(registry, tools=[value]), "tools[0]")
    for field, values in (
        ("slug", ["", "UpperCase", "example_tool", "example--tool", marker + "/child", 42]),
        ("installed", [0, 1, "false", None]),
    ):
        missing = dict(member)
        missing.pop(field)
        add(field + "_missing", dict(registry, tools=[missing]), "tools[0]." + field)
        for index, value in enumerate(values):
            add(field + "_invalid_" + str(index),
                dict(registry, tools=[dict(member, **{field: value})]), "tools[0]." + field)
    for field, values in (("transport", [marker, 1, None]), ("notes", [7, [marker], None])):
        for index, value in enumerate(values):
            add(field + "_invalid_" + str(index),
                dict(registry, tools=[dict(member, **{field: value})]), "tools[0]." + field)
    add("later_invalid_member", dict(registry, tools=[member, dict(member, notes={marker: True})]), "tools[1].notes")
    malformed = {
        "empty": b"",
        "truncated": b'{"schema_version": 1,',
        "invalid_utf8": b'{"schema_version": "\xff"}',
        "nonstandard_constant": b'{"schema_version": 1, "skill": "acme-cold-tool", "tools": [], "extra": NaN}',
        "duplicate_field": b'{"schema_version": 2, "schema_version": 1, "skill": "acme-cold-tool", "tools": []}',
        "trailing_content": (json.dumps(registry) + " " + marker).encode("utf-8"),
        "integer_limit": b'{"schema_version": ' + b"9" * 5000 + b', "skill": "acme-cold-tool", "tools": []}',
        "deep_nesting": b"[" * 1100 + b"0" + b"]" * 1100,
    }
    for name, raw in malformed.items():
        cases.append({"name": name, "raw": raw, "field": "registry.json", "valid": False, "marker": marker})
    add("valid_empty", registry, "", valid=True)
    add("valid_minimal_member", dict(registry, tools=[dict(member, installed=False)]), "", valid=True)
    for transport in ("stdio", "http", "sse", "rest", "python-lib"):
        add("valid_" + transport, dict(registry, tools=[dict(member, transport=transport, notes=marker)]), "", valid=True)
    add("valid_multiple_members", dict(registry, tools=[member, {"slug": "example2", "installed": False, "notes": ""}]), "", valid=True)
    return cases


def config_schema_companion(root, case):
    """Write one generated registry input into a complete synthetic companion shape."""
    root = config_companion(root)
    (root / "registry.json").write_bytes(case["raw"])
    return root


def config_resource_cases():
    """Synthetic configured resources; their location is not a generic schema restriction."""
    return [
        ("windows", "C:/Synthetic Resources/reference", None),
        ("windows_backslashes", "C:\\Synthetic Resources\\reference", None),
        ("linux_home", "/home/example/resources", None),
        ("mac_home", "/Users/example/resources", None),
        ("root_home", "/root/synthetic/resources", None),
        ("existing", None, None),
        ("missing", None, None),
        ("consumer_resource", None, None),
        ("opaque_extra", 42, None),
        ("invalid_version", "/home/example/resources", "schema_version"),
        ("invalid_notes", "/home/example/resources", "tools[0].notes"),
    ]


def config_resource_companion(root, consumer, case):
    """Create actual synthetic resources/configs without asserting private visibility."""
    root = config_companion(root)
    name, resource, invalid_field = case
    if name in ("existing", "missing", "consumer_resource"):
        resource_path = (Path(consumer) / "reference/synthetic resource" if name == "consumer_resource"
                         else root.parent / "synthetic resource")
        if name != "missing":
            resource_path.mkdir(parents=True, exist_ok=True)
            (resource_path / "source.txt").write_text("Synthetic read-only resource.\n", encoding="utf-8")
        resource = str(resource_path.resolve())
    registry = {"schema_version": 1, "skill": "acme-cold-tool", "tools": [], "resource_root": resource}
    if invalid_field == "schema_version":
        registry["schema_version"] = True
    elif invalid_field:
        registry["tools"] = [{"slug": "example", "installed": False, "notes": False}]
    write_json(root / "registry.json", registry)
    return root, resource


def config_template_path_control(root):
    """A generated negative control for detecting baked-in paths in initializer output."""
    return config_resource_companion(root, root, config_resource_cases()[0])[0]


def config_template_url_control(root):
    """Public documentation URLs are valid template text, not machine drive paths."""
    root = config_companion(root)
    (root / "secrets/README.md").write_text("See https://example.com/resources for setup.\n", encoding="utf-8")
    return root


def workflow_visibility_fixture(root, cached="PRIVATE", age_days=0):
    """Generate a visibility cache for live-first workflow/CI integration cases."""
    from datetime import datetime, timedelta, timezone

    root = Path(root)
    slug = "acmecorp/generated-tool"
    path = root / "visibility.json"
    write_json(path, {"_refreshed": (datetime.now(timezone.utc) - timedelta(days=age_days)).isoformat(),
                      slug: cached})
    return {"slug": slug, "cache": path, "slugs": {slug: str(root / "generated-tool")},
            "workflows": ["business.yml"]}


def fleet_inventory_fixture(root):
    """Generate ordinary/linked repositories and invalid Git markers without networking."""
    root = Path(root)
    fleet = root / "fleet"
    seed = fleet / "alpha"
    seed.mkdir(parents=True)

    def git(cwd, *args):
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=True, timeout=60)

    git(seed, "init", "-q")
    (seed / "synthetic.txt").write_text("Generated repository inventory.\n", encoding="utf-8")
    git(seed, "add", "synthetic.txt")
    git(seed, "-c", "user.name=Synthetic Fixture", "-c", "user.email=user1@example.com",
        "commit", "-qm", "Initialize synthetic inventory")
    git(seed, "remote", "add", "origin", "https://github.com/AcmeCorp/generated-tool.git")
    linked = fleet / "beta"
    git(seed, "worktree", "add", "--detach", str(linked))
    for name, marker in (("empty-marker", None), ("invalid-marker", "not a gitdir\n"),
                         ("missing-gitdir", "gitdir: ../missing\n")):
        folder = fleet / name
        folder.mkdir()
        if marker is None:
            (folder / ".git").mkdir()
        else:
            (folder / ".git").write_text(marker, encoding="utf-8")
    return {"fleet": fleet, "ordinary": seed, "linked": linked, "slug": "acmecorp/generated-tool"}


def directory_link(link, target):
    """Generate a real Windows junction or POSIX directory symlink for containment tests."""
    import os

    link, target = Path(link), Path(target)
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def config_initializer_destination(root, consumer, child="secrets", contained=False):
    """Generate a selected config with a linked child and sentinel files to preserve."""
    selected = Path(root) / "selected config"
    selected.mkdir(parents=True)
    write_json(selected / "registry.json", {"synthetic_sentinel": "preserve before preflight"})
    target = selected / "contained storage" if contained else Path(consumer) / "generated escape target"
    target.mkdir(exist_ok=True)
    (target / "README.md").write_text("Synthetic existing resource.\n", encoding="utf-8")
    directory_link(selected / child, target)
    return selected, target


def trim_companion_fixture(root):
    """Create a synthetic PRIVATE repository and offline visibility for trim CLI tests."""
    from datetime import datetime, timezone
    root = Path(root)
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "remote", "add", "origin",
                    "https://github.com/AcmeCorp/trim-config.git"], check=True, capture_output=True)
    home = root / "home"
    write_json(home / ".pii-guard/visibility.json", {
        "_refreshed": datetime.now(timezone.utc).isoformat(), "acmecorp/trim-config": "PRIVATE"})
    return home


def library_inventory_fixture(root, scenario="distinct"):
    """Generate a user/active-plugin inventory for library acceptance regressions."""
    from make_library_fixtures import library_inventory_fixture as generate
    return generate(root, scenario)


def storage_review_fixture(root):
    """Generate inert paths and observations for remote/storage regression tests."""
    root = Path(root)
    tool = root / "tool"
    data = root / "companion" / "data"
    home = root / "home"
    for path in (tool / "skills/skill-smith/scripts", tool / "guards/tools", data, home / ".ssh"):
        path.mkdir(parents=True)
    resolver = tool / "guards/tools/datadir.py"
    resolver.write_text("def resolve_data_dir(name, create=False):\n    return None\n", encoding="utf-8")
    (home / ".ssh/config").write_text(
        "Host acme-code\n    HostName github.com\n    User git\n", encoding="utf-8")
    library = root / "library" / "acme-report"
    library.mkdir(parents=True)
    descriptor = library / "SKILL.md"
    descriptor.write_text("---\nname: acme-report\ndescription: " + "research " * 30 + "\n---\n", encoding="utf-8")
    return {"tool": tool, "data": data, "home": home, "resolver": resolver,
            "library": library.parent, "descriptor": descriptor,
            "origin": "https://github.com/AcmeCorp/skill-smith-config.git",
            "slug": "acmecorp/skill-smith-config",
            "bad_origins": ["https://mirror.example.com/AcmeCorp/skill-smith-config.git",
                            "git@unverified-host:AcmeCorp/skill-smith-config.git",
                            "file:///AcmeCorp/skill-smith-config.git",
                            "https://github.com/extra/AcmeCorp/skill-smith-config.git",
                            "https://user1@example.com/AcmeCorp/skill-smith-config.git"],
            "git_errors": ["fatal: detected dubious ownership in repository",
                           "fatal: cannot change to missing: No such file or directory",
                           "fatal: permission denied", "fatal: unknown probe failure"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    write_json(Path(args.out) / "fleet-check-status.json.example", {
        "tool": "fleet_check", "schema": 2, "utc": "2000-01-01T00:00:00Z", "duration_s": 0,
        "exit": 0, "verdict": "GREEN", "digest": "Synthetic schema example; no fleet was inspected",
        "coverage": {"evaluated": 0, "not_evaluated": 1},
        "totals": {"pass": 0, "fail": 0, "warn": 0, "skip": 0, "unknown": 1},
        "checks": {}, "failures": [], "unobserved": ["synthetic: not observed"],
        "warnings": [], "ci_execution": {}})
    description = "Use to summarize synthetic report records and return a concise evidence table."
    write_json(Path(args.out) / "worklist.json.example", [{
        "path": "<absolute-path-to-synthetic-skill>/SKILL.md", "name": "acme-report",
        "cap": 60, "old": description, "old_len": len(description), "new": ""}])


if __name__ == "__main__":
    main()
