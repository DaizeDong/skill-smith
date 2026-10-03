"""Generate synthetic acceptance-contract fixtures; never imports runtime data."""
import hashlib
import json
import os
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
    return [("Acme Tool", "acme-tool"), ('Acme "Tool"', "acme-tool"),
            ("Acme - Tool", "acme-tool"), ("acme--tool", "acme-tool")]


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
    (data.parent / ".git").mkdir()
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


def output_proof_fixture(root):
    """Generate real Git worktrees and fresh synthetic visibility for writer controls."""
    from datetime import datetime, timezone
    layout = storage_review_fixture(root)
    private = layout["data"].parent
    public = Path(root) / "public-companion"
    public.mkdir()
    public_slug = "acmecorp/synthetic-public-companion"
    for path, origin in ((private, layout["origin"]),
                         (public, "https://github.com/" + public_slug + ".git")):
        subprocess.run(["git", "-C", str(path), "init", "-q"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(path), "remote", "add", "origin", origin],
                       check=True, capture_output=True)
    visibility = layout["home"] / ".pii-guard/visibility.json"
    write_json(visibility, {"_refreshed": datetime.now(timezone.utc).isoformat(),
                            layout["slug"]: "PRIVATE", public_slug: "PUBLIC"})
    consumer = Path(root) / "audited-tool"
    review15_plugin_metadata(consumer, "synthetic-tool")
    resolver = consumer / "guards/tools/datadir.py"
    resolver.parent.mkdir(parents=True)
    resolver.write_text("from pathlib import Path\ndef resolve_data_dir(skill, create=False):\n"
                        "    return Path(%r)\n" % str(layout["data"]), encoding="utf-8")
    return {**layout, "private": private, "public": public, "visibility": visibility,
            "consumer": consumer,
            "ssh_origin": "git@github.com:AcmeCorp/skill-smith-config.git",
            "ssh_override": "ssh -o HostName=example.com",
            "changed_signature": "synthetic-changed-configuration",
            "replacement": "Summarize synthetic records.",
            "counts": {key: 0 for key in ("pass", "fail", "warn", "skip", "unknown")},
            "incompatible_api": "def prove_private_companion(destination):\n    return None\n"}


def review10_library(root, scenario="kept"):
    """Generate listing identities and Unicode descriptions without reading live state."""
    root = Path(root)
    fixture = library_inventory_fixture(root)
    listing = root / "listing.txt"
    lines = ["- invoice-reader: Reconcile synthetic invoices.",
             "- shapes@example-market:polygon-renderer: Render synthetic shapes."]
    if scenario == "lost":
        lines[1] = "- shapes@example-market:polygon-renderer"
    elif scenario == "unseen":
        lines.pop()
    elif scenario == "mismatched":
        lines = ["- unrelated: A synthetic unrelated entry."]
    elif scenario == "unusable":
        lines = ["Synthetic capture without listing rows."]
    elif scenario in ("chinese", "chinese-distinct", "unmeasurable"):
        shared = "提取发票总额并核对供应商付款。"
        distinct = "绘制彩色多边形并生成几何图像。"
        fixture["shared"] = shared if scenario != "unmeasurable" else "!!!"
        for name, path in fixture["paths"].items():
            desc = distinct if scenario == "chinese-distinct" and name == "polygon-renderer" else fixture["shared"]
            path.write_text("---\nname: %s\ndescription: %s\n---\nSynthetic instructions.\n"
                            % (name, json.dumps(desc, ensure_ascii=False)), encoding="utf-8")
    if scenario != "missing":
        listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    fixture["listing"] = listing
    return fixture


def review10_namespaced_rows():
    """Return synthetic identities, including two same-name plugin installations."""
    return [("alpha@example-market", "search"), ("beta@example-market", "search")]


def review10_listing_identities(mode="canonical", reversed_order=False):
    """Return supplied identity observations, with no order-based ownership assumption."""
    keys = {"canonical": ["alpha@example-market:search", "beta@example-market:search"],
            "short_plugin": ["alpha:search", "beta:search"],
            "ambiguous": ["search"], "foreign": ["other:search"]}[mode]
    entries = [(key, index == 0) for index, key in enumerate(keys)]
    return dict(reversed(entries) if reversed_order else entries)


def review10_replacements():
    """YAML string cases include implicit scalars and escaped control characters."""
    return {"plain": "Summarize synthetic records.", "colon": "Summarize: synthetic records.",
            "multiline": "Summarize records.\nRetain evidence.", "boolean": "true",
            "numeric": "123", "null": "null", "quoted": 'Render "synthetic" records.',
            "tab": "Summarize\trecords.", "unicode": "汇总合成记录。"}


def review10_budget_digest(kind):
    """Generate internally contradictory and complete budget transport observations."""
    fields = {"complete": (0, "complete", 0), "lost": (1, "complete", 0),
              "unmeasured": (0, "not_supplied", 0), "incomplete": (0, "incomplete", 1),
              "missing": (0, None, 0)}
    lost, measurement, unresolved = fields[kind]
    text = "BUDGET: OK total=100 capacity=1000 overflow=0 trim_headroom=0 min_lost=%d cap_over_ours=0 plugins=1 lever=n/a fp=abcdef12 unresolved=%d" % (lost, unresolved)
    return text + (" measurement=" + measurement if measurement else "") + "\n"


def review10_legacy_budget_digest(state, **overrides):
    """Preserve legacy budget controls while declaring their measurement scope."""
    fields = {"total": 1000, "capacity": 21565, "overflow": 0, "trim_headroom": 0,
              "min_lost": 0, "cap_over_ours": 0, "plugins": 0, "lever": "n/a",
              "fp": "aaaaaaaa", "unresolved": 0,
              "measurement": "not_supplied" if state == "BLOCKED" else "complete"}
    fields.update(overrides)
    return "  STATUS: %s\n  BUDGET: %s %s\n" % (
        state, state, " ".join("%s=%s" % item for item in fields.items()))


def review10_trim(root, replacement, malformed=False):
    """Generate a reviewed worklist and its original descriptor for serialization tests."""
    root = Path(root)
    path = root / "skills/acme-report/SKILL.md"
    path.parent.mkdir(parents=True)
    old = "Summarize synthetic invoice records and render an evidence table."
    body = "---\nname: acme-report\ndescription: %s\n%s---\nSynthetic body.\n" % (
        old, "invalid metadata line\n" if malformed else "")
    path.write_text(body, encoding="utf-8")
    worklist = root / "data/worklist.json"
    write_json(worklist, [{"path": str(path), "name": "acme-report", "old": old,
                          "old_len": len(old), "new": replacement, "cap": 180}])
    return {"path": path, "worklist": worklist, "backup": root / "data/backups", "before": body}


def review10_ignore(root, scenario):
    """Generate active, overridden and inert ignore policies for synthetic secret paths."""
    patterns = {
        "active": "secrets/*\n!secrets/.gitkeep\n*.env\n!.env.template\n",
        "absent": "build/\n",
        "comments": "# secrets/\n# *.env\n",
        "negated": "!secrets/\n!*.env\n",
        "reopened": "secrets/*\n*.env\n!secrets/*\n!*.env\n",
        "restored": "!secrets/*\n!*.env\nsecrets/*\n*.env\n",
        "parent_excluded": "secrets/\n!secrets/fixture-secret.txt\n*.env\n",
        "root_only_env": "secrets/\n/*.env\n",
        "nested_reopened": "secrets/*\n*.env\n!config/*.env\n",
    }
    root = Path(root)
    for child in ("tools", "secrets"):
        (root / child).mkdir(parents=True)
    write_json(root / "registry.json", {"schema_version": 1, "skill": "acme-tool", "tools": []})
    (root / ".gitignore").write_text(patterns[scenario], encoding="utf-8")
    (root / "CONFIG.md").write_text("registry.json schema_version\n", encoding="utf-8")
    return root


def review10_routes(scenario="private"):
    """Generate exact Git query responses; unknown commands fail instead of borrowing a URL."""
    private = "https://github.com/AcmeCorp/private-config.git"
    public = "https://github.com/AcmeCorp/public-tool.git"
    routes = {"origin": [private], "publish": [private]}
    config = {}
    if scenario == "public_push":
        routes["origin"] = [public]
    elif scenario == "unknown_push":
        routes["origin"] = ["https://mirror.example.com/AcmeCorp/private-config.git"]
    elif scenario == "multiple_push":
        routes["origin"] = [private, public]
    elif scenario in ("push_default", "branch_push", "branch_remote"):
        config[{"push_default": "remote.pushdefault", "branch_push": "branch.main.pushremote",
                "branch_remote": "branch.main.remote"}[scenario]] = "publish"
        routes["publish"] = [public]
    elif scenario == "missing_route":
        config["remote.pushdefault"] = "missing"
    elif scenario == "local_route":
        config["branch.main.remote"] = "."
    elif scenario == "private_override":
        config.update({"remote.pushdefault": "publish", "branch.main.pushremote": "origin"})
        routes["publish"] = [public]
    elif scenario == "config_failure":
        config = None
    return {"origin": private, "routes": routes, "config": config,
            "visibility": {"acmecorp/private-config": "PRIVATE", "acmecorp/public-tool": "PUBLIC"}}


def review10_route_query(fixture, args):
    """Answer only modeled local Git inspection commands; never spawn Git."""
    args = list(args)
    query = args[3:] if len(args) > 2 and args[1] == "-C" else args[1:]
    if query == ["remote", "get-url", "origin"]:
        return 0, fixture["origin"], ""
    if query == ["symbolic-ref", "--quiet", "--short", "HEAD"]:
        return 0, "main\n", ""
    if query[:3] == ["config", "--null", "--get-all"]:
        if fixture["config"] is None:
            return 128, "", "synthetic config failure"
        value = fixture["config"].get(query[3].lower())
        return (0, value + "\0", "") if value is not None else (1, "", "")
    if query[:4] == ["remote", "get-url", "--push", "--all"]:
        urls = fixture["routes"].get(query[4])
        return (0, "\n".join(urls) + "\n", "") if urls else (2, "", "synthetic missing remote")
    raise AssertionError("unmodeled synthetic Git query: %r" % query)


def materialize_output_routes(layout, scenario):
    """Materialize the generated fetch/push case for the actual shared verifier."""
    fixture = review10_routes(scenario)
    if scenario == "private_multiple":
        fixture["routes"]["origin"].append("git@github.com:AcmeCorp/private-backup.git")
        fixture["visibility"]["acmecorp/private-backup"] = "PRIVATE"
    elif scenario == "unknown_visibility":
        fixture["routes"]["origin"].append("git@github.com:AcmeCorp/unknown-config.git")
    elif scenario == "public_origin":
        fixture["origin"] = "https://github.com/AcmeCorp/public-tool.git"
    root = layout["private"]

    def git(*args):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)

    git("symbolic-ref", "HEAD", "refs/heads/main")
    git("remote", "set-url", "origin", fixture["origin"])
    for remote, urls in fixture["routes"].items():
        if remote != "origin":
            git("remote", "add", remote, urls[0])
        for url in urls:
            git("config", "--add", "remote." + remote + ".pushurl", url)
    if fixture["config"] is None:
        (root / ".git/config").write_text("[synthetic-invalid-section\n", encoding="utf-8")
    else:
        for key, value in fixture["config"].items():
            git("config", key, value)
    states = json.loads(layout["visibility"].read_text(encoding="utf-8"))
    states.update(fixture["visibility"])
    write_json(layout["visibility"], states)
    return fixture


def review10_storage_query(layout, args, nested=None):
    """Extend the source9 storage transport with explicit effective routing responses."""
    target = Path(args[args.index("-C") + 1])
    if "rev-parse" in args:
        return 0, str(nested if nested is not None and target == nested else layout["data"].parent), ""
    route = review10_routes()
    origin = "https://github.com/AcmeCorp/public-backups.git" if nested is not None and target == nested else layout["origin"]
    route["origin"] = origin
    route["routes"] = {"origin": [origin]}
    return review10_route_query(route, args)


def review10_hook(root, hook, source_body, target_kind):
    """Generate a consumer forwarder and an inert delegated guard for native hook checks."""
    root = Path(root)
    path = root / ".githooks" / hook
    path.parent.mkdir(parents=True)
    path.write_bytes(source_body)
    target = root / "guards/hooks" / hook
    target.parent.mkdir(parents=True)
    if target_kind == "directory":
        target.mkdir()
    elif target_kind != "missing":
        body = ("#!/bin/sh\nprintf '%s\\n' synthetic-guard-ran\nprintf 'arg:%s\\n' \"$@\"\n"
                "while IFS= read -r line; do printf 'stdin:%s\\n' \"$line\"; done\n"
                f"exit {7 if target_kind == 'failure' else 0}\n")
        target.write_text("" if target_kind == "empty" else body, encoding="utf-8", newline="\n")
    args = ["synthetic-first", "synthetic two words", "synthetic\\path"]
    stdin = "synthetic input\nsynthetic\\input\n"
    expected = ("synthetic-guard-ran\n" + "".join("arg:%s\n" % arg for arg in args)
                + "".join("stdin:%s\n" % line for line in stdin.splitlines()))
    return {"path": path, "args": args, "stdin": stdin, "expected_stdout": expected,
            "expected_exit": 7 if target_kind == "failure" else 0 if target_kind == "valid" else 1}


def review11_conformance(case):
    """Generate measured, contradictory and missing conformance subprocess evidence."""
    clean = "  [PASS] synthetic first\n  [PASS] synthetic second\n2/2 passed\n"
    cases = {
        "clean": (0, clean, "", "PASS"),
        "empty": (0, "", "", "UNKNOWN"),
        "zero": (0, "0/0 passed\n", "", "UNKNOWN"),
        "summary_only": (0, "2/2 passed\n", "", "UNKNOWN"),
        "rows_only": (0, "  [PASS] synthetic first\n", "", "UNKNOWN"),
        "count_mismatch": (0, clean.replace("2/2", "3/3"), "", "UNKNOWN"),
        "contradictory": (0, clean.replace("2/2", "1/2"), "", "UNKNOWN"),
        "malformed": (0, clean.replace("2/2 passed", "2/2 passed (nonsense)"), "", "UNKNOWN"),
        "duplicate_summary": (0, clean + "2/2 passed\n", "", "UNKNOWN"),
        "duplicate_rows": (0, clean.replace("synthetic second", "synthetic first"), "", "UNKNOWN"),
        "fail_stdout": (0, "  [FAIL] synthetic failure\n0/1 passed (1 FAIL)\n", "", "FAIL"),
        "fail_stderr": (0, clean, "  [FAIL] synthetic stderr failure\n", "FAIL"),
        "warn_stdout": (0, "  [WARN] synthetic warning\n0/1 passed (1 WARN)\n", "", "WARN"),
        "warn_stderr": (0, clean, "  [WARN] synthetic stderr warning\n", "WARN"),
        "plain_warning": (0, clean, "WARNING: synthetic stderr warning\n", "WARN"),

        "plain_stdout_warning": (0, clean + "WARNING: synthetic stdout warning\n", "", "WARN"),
        "bare_fail": (0, clean + "[FAIL]\n", "", "FAIL"),
        "bare_warn": (0, clean + "[WARN]\n", "", "WARN"),
        "malformed_row": (0, clean + "[PASS]\n", "", "UNKNOWN"),
        "unexplained_stderr": (0, clean, "synthetic unexplained diagnostic", "UNKNOWN"),
        "timeout": (None, "", "synthetic timeout", "UNKNOWN"),
        "nonzero": (7, "", "synthetic nonzero", "FAIL"),
    }
    return cases[case]


def review11_metadata_cases():
    """Generate explicit GitHub targets and lookalike/ambiguous URL counterexamples."""
    return {
        "https": ("https://github.com/AcmeCorp/synthetic-tool", ("AcmeCorp", "synthetic-tool")),
        "trailing_slash": ("https://github.com/AcmeCorp/synthetic-tool/", ("AcmeCorp", "synthetic-tool")),
        "host_case": ("https://GITHUB.COM/AcmeCorp/synthetic-tool", ("AcmeCorp", "synthetic-tool")),
        "git_suffix": ("https://github.com/AcmeCorp/synthetic-tool.git", ("AcmeCorp", "synthetic-tool")),
        "lookalike": ("https://notgithub.com/AcmeCorp/synthetic-tool", None),
        "foreign_path": ("https://example.com/github.com/AcmeCorp/synthetic-tool", None),
        "subdomain": ("https://github.com.example.com/AcmeCorp/synthetic-tool", None),
        "userinfo": ("https://example.com@github.com/AcmeCorp/synthetic-tool", None),
        "foreign_userinfo": ("https://github.com@elsewhere.example.com/AcmeCorp/synthetic-tool", None),
        "missing_scheme": ("github.com/AcmeCorp/synthetic-tool", None),
        "http": ("http://github.com/AcmeCorp/synthetic-tool", None),
        "port": ("https://github.com:443/AcmeCorp/synthetic-tool", None),
        "deep_path": ("https://github.com/AcmeCorp/synthetic-tool/issues", None),
        "query": ("https://github.com/AcmeCorp/synthetic-tool?target=other", None),
        "fragment": ("https://github.com/AcmeCorp/synthetic-tool#other", None),
        "encoded_separator": ("https://github.com/AcmeCorp/synthetic%2ftool", None),
        "control": ("https://github.com/AcmeCorp/synthetic\ntool", None),
        "leading_nul": ("\x00https://github.com/AcmeCorp/synthetic-tool", None),
        "leading_del": ("\x7fhttps://github.com/AcmeCorp/synthetic-tool", None),
        "dot_repo": ("https://github.com/AcmeCorp/..", None),
        "empty": ("", None),
        "wrong_type": (["https://github.com/AcmeCorp/synthetic-tool"], None),
    }


def review11_layout(root):
    """Generate only synthetic files needed to reach fleet transport seams."""
    root = Path(root)
    consumer = root / "consumer"
    write_json(consumer / ".claude-plugin/plugin.json", {"name": "synthetic-tool"})
    resolver = consumer / "guards/tools/datadir.py"
    resolver.parent.mkdir(parents=True)
    resolver.write_text("# Synthetic resolver; tests replace its loader.\n", encoding="utf-8")
    data = root / "private-config/data"
    data.mkdir(parents=True)
    return {"consumer": consumer, "data": data}


def review11_skill(root, case, root_layout=False):
    """Generate a complete synthetic G6 input; scanner programs are inert placeholders."""
    root = Path(root)
    name = "synthetic-tool"
    write_json(root / ".claude-plugin/plugin.json", {
        "name": name, "version": "0.0.1", "author": {"name": "DaizeDong"},
        "license": "MIT", "homepage": "https://github.com/DaizeDong/" + name,
        "keywords": ["synthetic", "skill"],
    })
    files = {rel: "Synthetic fixture.\n" for rel in (
        "LICENSE", "guards/tools/pii_guard.py", "guards/tools/test_pii_guard.py",
        "guards/hooks/pre-commit", "guards/hooks/pre-push", ".github/workflows/pii-guard.yml",
        ".pii-allow", "guards/tools/data_boundary.py", "guards/tools/datadir.py",
        ".dataclass.json", "style/tools/dash_guard.py", ".github/workflows/dash-guard.yml",
    )}
    badge = "Claude%20Code-Skill-orange License-MIT-blue Languages-EN%20%2F%20CN-blue Roadmap-v0.0.1-purple\n"
    files.update({
        "README.md": badge + "## \u2b50 Read this first\nSynthetic instructions.\n[English](README.md) [CN](README_CN.md)\n",
        "README_CN.md": badge + "## \u2b50\nSynthetic instructions.\n",
        "ROADMAP.md": "Current: **v0.0.1**\n",
        "CHANGELOG.md": "## [0.0.1] - 2000-01-01\nSynthetic release.\n",
    })
    header = "---\nname: synthetic-tool\ndescription: Summarize synthetic records.\n---\n"
    texts = {
        "valid": header + "Read the synthetic input and return a concise table.\n",
        "empty": "", "whitespace": " \n\t\n",
        "no_frontmatter": "Read the synthetic input and return a concise table.\n",
        "missing_name": "---\ndescription: Summarize synthetic records.\n---\nRead input.\n",
        "missing_description": "---\nname: synthetic-tool\n---\nRead input.\n",
        "empty_description": "---\nname: synthetic-tool\ndescription: \"\"\n---\nRead input.\n",
        "collection": "---\nname: synthetic-tool\ndescription: [synthetic, records]\n---\nRead input.\n",
        "duplicate": "---\nname: synthetic-tool\nname: duplicate\ndescription: Synthetic.\n---\nRead input.\n",
        "no_body": header, "blank_body": header + " \n\t",
        "comment_body": header + "<!-- synthetic placeholder -->\n",
        "unclosed": header.replace("---\nRead", "Read")[:-4],
        "quoted": "---\nname: 'synthetic-tool'\ndescription: \"Summarize synthetic records.\"\n---\nRead input.\n",
        "block": "---\nname: synthetic-tool\ndescription: >\n  Summarize synthetic\n  records.\n---\nRead input.\n",
        "unreadable": header + "Read input.\n",
    }
    rel = "SKILL.md" if root_layout else "skills/synthetic-tool/SKILL.md"
    files[rel] = texts[case]
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return root / rel


def instruction_scan_case(root, root_layout=False, with_marker=False):
    """Generate readable instruction targets for scan coverage and read-fault tests."""
    skill = review11_skill(root, "valid", root_layout)
    reference = skill.parent / "reference" / "scan.md"
    reference.parent.mkdir()
    reference.write_text(
        "Phase 2 adds a generated validation rule.\n" if with_marker else
        "Validate the generated input and return its field names.\n", encoding="utf-8")
    return {"skill": skill, "reference": reference}


def review11_thresholds():
    """Generate supported endpoints and invalid floating-point configurations."""
    return {"valid": ["0", "0.4", "1"], "invalid": ["nan", "inf", "-inf", "-0.1", "1.01"]}



def review12_frontmatter_cases():
    """Generate complete YAML documents using synthetic metadata only."""
    name = "synthetic-tool"
    description = "Summarize synthetic records."
    base = "name: " + name + "\ndescription: " + description + "\n"
    fields = {
        "plain": (base, (name, description)),
        "ancillary_delimiter": (base + "metadata: |\n  ---\n  Synthetic.\n", (name, description)),
        "invalid_after_delimiter": (base + "metadata: |\n  ---\n  Synthetic.\nbroken: [one, two\n", (None, None)),
        "description_delimiter": ("name: synthetic-tool\ndescription: |\n  Read input.\n  ---\n  Return output.\n", (name, "Read input.\n---\nReturn output.\n")),
        "ancillary_mapping": (base + "metadata:\n  owner: AcmeCorp\n  flags: [one, two]\n", (name, description)),
        "ancillary_sequence": (base + "allowed-tools:\n  - Read\n  - Write\n", (name, description)),
        "ancillary_scalar_types": (base + "metadata: {enabled: true, count: 2, missing: null}\n", (name, description)),
        "ancillary_anchor": (base + "metadata: &metadata {owner: AcmeCorp}\ncopy: *metadata\n", (name, description)),
        "ancillary_merge": (base + "defaults: &defaults {owner: AcmeCorp}\nmetadata:\n  <<: *defaults\n  owner: example-employer.com\n", (name, description)),
        "quoted_keys": ('"name": synthetic-tool\n"description": Summarize synthetic records.\n', (name, description)),
        "yaml_escape": ('name: synthetic-tool\ndescription: "Read\\tinput"\n', (name, "Read\tinput")),
        "literal": ("name: synthetic-tool\ndescription: |\n  Read input.\n  Return output.\n", (name, "Read input.\nReturn output.\n")),
        "folded": ("name: synthetic-tool\ndescription: >-\n  Read synthetic\n  input.\n", (name, "Read synthetic input.")),
        "missing_name": ("description: " + description + "\n", (None, description)),
        "quoted_boolean": ('name: "on"\ndescription: "true"\n', ("on", "true")),
        "bad_flow_sequence": (base + "metadata: [one, two\n", (None, None)),
        "bad_flow_mapping": (base + "metadata: {owner: AcmeCorp\n", (None, None)),
        "bad_quote": (base + 'metadata: "unfinished\n', (None, None)),
        "bad_indent": (base + "metadata:\n  owner: AcmeCorp\n value: invalid\n", (None, None)),
        "unknown_alias": (base + "metadata: *missing\n", (None, None)),
        "unsafe_tag": (base + "metadata: !!python/object:builtins.object {}\n", (None, None)),
        "duplicate_name": (base + '"name": different-tool\n', (None, None)),
        "duplicate_description": (base + '"description": Different synthetic records.\n', (None, None)),
        "duplicate_nested": (base + "metadata: {owner: AcmeCorp, owner: duplicate}\n", (None, None)),
        "non_mapping": ("- name: synthetic-tool\n- description: Synthetic.\n", (None, None)),
        "null_name": ("name: null\ndescription: Synthetic.\n", (None, None)),
        "boolean_name": ("name: on\ndescription: Synthetic.\n", (None, None)),
        "empty_description": ('name: synthetic-tool\ndescription: "  "\n', (None, None)),
        "boolean_description": ("name: synthetic-tool\ndescription: on\n", (None, None)),
        "numeric_description": ("name: synthetic-tool\ndescription: 1\n", (None, None)),
        "date_description": ("name: synthetic-tool\ndescription: 2000-01-01\n", (None, None)),
        "mapping_description": ("name: synthetic-tool\ndescription: {text: Synthetic.}\n", (None, None)),
        "sequence_description": ("name: synthetic-tool\ndescription: [Synthetic.]\n", (None, None)),
    }
    return {case: {"text": "---\n" + body + "---\nRead the synthetic input.\n",
                   "expected": expected} for case, (body, expected) in fields.items()}


def review12_skill(root, case, include_body=True):
    """Materialize one generated metadata input for G6 and library inventory."""
    root = Path(root)
    path = root / "skills/synthetic-tool/SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = review12_frontmatter_cases()[case]["text"]
    if not include_body:
        text = text.removesuffix("Read the synthetic input.\n")
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def review12_remote_fixture():
    """Synthetic host and workflow records for transport interception."""
    return {
        "owner": "AcmeCorp", "repo": "synthetic-tool",
        "homepage": "https://github.com/AcmeCorp/synthetic-tool",
        "description": "Summarize synthetic records.",
        "hosts": [None, "", "github.example.com", "GITHUB.COM"],
        "explicit_targets": [
            ("AcmeCorp", "synthetic-tool", True), ("AcmeCorp", "synthetic-tool.v2", True),
            ("github.example.com/AcmeCorp", "synthetic-tool", False),
            ("AcmeCorp/subgroup", "synthetic-tool", False),
            ("AcmeCorp", "synthetic-tool/extra", False),
            ("Acme Corp", "synthetic-tool", False),
            ("AcmeCorp", ".", False), ("-AcmeCorp", "synthetic-tool", False),
        ],
        "branches": ["main", "release/synthetic", "release&extra=value", "release#section",
                     "release+candidate", "release%2Fsynthetic", "release=synthetic"],
        "workflows": ["pii-guard.yml", "dash-guard.yml", "extra-check.yml"],
    }




def review15_duplicated_prose():
    return ("the ratchet only turns one way and a grandfather clause without an expiry date is a "
             "permanent exemption wearing a reassuring name which is the defect this whole file "
             "exists to prevent from recurring quietly in the dark ") * 6


def review15_plugin_metadata(root, name):
    """Generate authoritative plugin identity for an initialized synthetic skill."""
    return write_json(Path(root) / ".claude-plugin/plugin.json", {"name": name})


def review15_snapshot_files(root):
    root = Path(root)
    paths = {}
    for name in ("requested", "foreign"):
        repo = root / name
        repo.mkdir(parents=True)
        (repo / "code.py").write_bytes(b"VALUE = 1\n")
        paths[name] = repo
    paths["changed_payload"] = b"VALUE = 2\n"
    return paths


def review15_git_selectors(foreign):
    foreign = Path(foreign)
    return [
        ("repository", {"GIT_DIR": str(foreign / ".git"), "GIT_WORK_TREE": str(foreign)}),
        ("index", {"GIT_INDEX_FILE": str(foreign / ".git/index")}),
        ("objects", {"GIT_OBJECT_DIRECTORY": str(foreign / ".git/objects"),
                     "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(foreign / ".git/objects")}),
        ("config", {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.worktree",
                    "GIT_CONFIG_VALUE_0": str(foreign)}),
    ]


def review15_doctor_layout(root):
    root = Path(root)
    tool = config_lifecycle(root / "tool")
    configs = [root / "config-a", root / "config-b"]
    for config in configs:
        config.mkdir()
        write_json(config / "registry.json", {"schema_version": 1, "required_root": "synthetic"})
    return {"tool": tool, "configs": configs, "template": b'{"schema_version":1}\n'}


def review15_doctor_reports(root):
    root = Path(root)
    exact = str(root)
    prefixed = str(root) + "-different"
    return [
        ("current-exact", "  resolved via environment -> " + exact + "\n", True),
        ("legacy-exact", "RESOLVED: " + exact + "\n", True),
        ("current-prefix", "  resolved via environment -> " + prefixed + "\n", False),
        ("legacy-prefix", "RESOLVED: " + prefixed + "\n", False),
        ("prose-only", "The requested root was " + exact + "\n", False),
        ("ambiguous", "RESOLVED: " + exact + "\nRESOLVED: " + prefixed + "\n", False),
    ]


def review15_budget_records():
    description = "Synthetic inventory processing and validation. " * 7
    return [{"tier": "local", "name": "synthetic-%03d" % i, "desc": description,
             "path": "synthetic/skill-%03d/SKILL.md" % i, "owner": None}
            for i in range(100)]


def review15_listing(records, missing=False):
    result = {row["name"]: True for row in records}
    if missing:
        result[records[-1]["name"]] = False
    return result


def review15_inverse_layout(root, checkout="renamed-checkout"):
    root = Path(root)
    consumer = root / checkout
    review15_plugin_metadata(consumer, "acme-synthetic-tool")
    resolver = consumer / "guards/tools/datadir.py"
    resolver.parent.mkdir(parents=True)
    resolver.write_text("# Synthetic resolver; regression replaces only its loader.\n", encoding="utf-8")
    data = root / "synthetic-config/data"
    data.mkdir(parents=True)
    return {"consumer": consumer, "data": data, "skill": "acme-synthetic-tool"}


def review15_metadata_failures():
    return [("missing", None), ("malformed", "{"), ("no-name", "{}"),
            ("wrong-type", '{"name": 7}'), ("invalid-name", '{"name": "../wrong"}')]


def review15_tree(admin, files):
    """Build only synthetic loose tree objects; no commit command or real repository input."""
    tree = {}
    for relative, payload in files.items():
        parts = relative.split("/")
        node = tree
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = payload

    def render(node):
        records = []
        for name, value in sorted(node.items(), key=lambda item: item[0] + ("/" if isinstance(item[1], dict) else "")):
            if isinstance(value, dict):
                mode, digest = b"40000", render(value)
            else:
                mode, digest = b"100644", review14_git_object(admin, "blob", value)
            records.append(mode + b" " + name.encode("utf-8") + b"\0" + bytes.fromhex(digest))
        return review14_git_object(admin, "tree", b"".join(records))

    return render(tree)


def review15_kit_layout(root):
    """A complete synthetic guards submodule with an extra trusted helper blob."""
    root = Path(root)
    dest = root / "guards"
    admin = root / ".git/modules/guards"
    files = {
        "hooks/pre-commit": b"#!/bin/sh\nexit 1\n",
        "hooks/pre-push": b"#!/bin/sh\nexit 1\n",
        "tools/pii_guard.py": b"VALUE = 'synthetic guard'\n",
        "tools/data_boundary.py": b"VALUE = 'synthetic boundary'\n",
        "tools/datadir.py": b"VALUE = 'synthetic resolver'\n",
        "tools/nested_helper.py": b"VALUE = 'synthetic helper'\n",
        "ci/pii-guard/action.yml": b"name: synthetic-guard\n",
    }
    for gitdir in (root / ".git", admin):
        (gitdir / "objects").mkdir(parents=True)
        (gitdir / "refs/heads").mkdir(parents=True)
        (gitdir / "HEAD").write_text("ref: refs/heads/main\n", encoding="ascii")
    (root / ".git/config").write_text("[core]\n\trepositoryformatversion = 0\n\tbare = false\n\tautocrlf = false\n", encoding="ascii")
    (admin / "config").write_text(
        "[core]\n\trepositoryformatversion = 0\n\tbare = false\n\tautocrlf = false\n"
        "\tworktree = ../../../guards\n[remote \"origin\"]\n"
        "\turl = https://github.com/DaizeDong/fleet-guards.git\n", encoding="ascii")
    for relative, payload in files.items():
        path = dest / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    (dest / ".git").write_text("gitdir: ../.git/modules/guards\n", encoding="ascii")
    (root / ".gitmodules").write_text(
        '[submodule "guards"]\n\tpath = guards\n'
        '\turl = https://github.com/DaizeDong/fleet-guards.git\n', encoding="ascii")
    tree = review15_tree(admin, files)
    commit = ("tree %s\nauthor Fixture User <user1@example.com> 946684800 +0000\n"
              "committer Fixture User <user1@example.com> 946684800 +0000\n\n"
              "Synthetic kit fixture.\n") % tree
    revision = review14_git_object(admin, "commit", commit.encode("ascii"))
    (admin / "refs/heads/main").write_text(revision + "\n", encoding="ascii")
    return {"root": root, "dest": dest, "revision": revision,
            "changed_payload": b"VALUE = 'synthetic modified payload'\n"}


def review15_capacity_policy():
    """Explicit synthetic policy for legacy overflow and pricing controls."""
    return 21565


def review20_config_layout(root, assets, resolver_text):
    """Generate an emitted consumer around inspected TOOL code and a synthetic Git object tree."""
    import shutil
    root = Path(root) / "acme-fixture"
    layout = review15_kit_layout(root)
    (layout["dest"] / "tools/datadir.py").write_text(resolver_text, encoding="utf-8", newline="\n")
    revision = review14_guard_revision(root / ".git/modules/guards", resolver_text)
    review14_plugin_identity(root)
    scripts = root / "scripts"
    scripts.mkdir()
    for name in ("config_runtime.py", "init_config.py", "verify_config.py"):
        shutil.copyfile(Path(assets) / name, scripts / name)
    return {**layout, "revision": revision, "initializer": scripts / "init_config.py",
            "sentinel": b'{"synthetic_sentinel":"preserve outside selected root"}\n',
            "replacement": '{"synthetic_candidate":"complete new template"}\n',
            "generated": ["registry.json", ".gitignore", "tools/.gitkeep",
                          "secrets/README.md", "secrets/.gitkeep"]}


def review20_config_destination(layout, case):
    root = layout["root"].parent / case.replace("/", "-")
    root.mkdir()
    outside = root.parent / (root.name + "-outside.json")
    outside.write_bytes(layout["sentinel"])
    relative = "registry.json" if case == "ordinary" else case
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if case == "ordinary":
        target.write_bytes(layout["sentinel"])
    else:
        os.link(outside, target)
    return {"root": root, "outside": outside, "target": target, "relative": relative}


def review20_ssh_configs():
    """SSH config controls use invented routing values and never execute a transport."""
    return [
        ("missing", None, True),
        ("unmodified", "Host github.com\n  HostName github.com\n", True),
        ("identity_only", "Host github.com\n  User git\n  IdentityFile synthetic-key\n", True),
        ("rewritten", "Host github.com\n  HostName mirror.example.com\n", False),
        ("proxy", "Host github.com\n  HostName github.com\n  ProxyCommand synthetic-transport %h\n", False),
        ("jump", "Host *\n  ProxyJump mirror.example.com\n", False),
        ("canonical", "Host github.com\n  CanonicalizeHostname yes\n", False),
        ("first_hostname", "Host *\n  HostName mirror.example.com\nHost github.com\n  HostName github.com\n", False),
        ("later_hostname", "Host github.com\n  HostName github.com\nHost *\n  HostName mirror.example.com\n", True),
        ("bad_port", "Host github.com\n  HostName github.com\n  Port 2222\n", False),
        ("negated", "Host * !github.com\n  ProxyCommand synthetic-transport %h\n", True),
    ]


def review20_inventory_layout(root, config, *, url_form="scp"):
    root = Path(root)
    home = root / "home"
    (home / ".ssh").mkdir(parents=True)
    if config is not None:
        (home / ".ssh/config").write_text(config, encoding="utf-8")
    repository = root / "repos/synthetic-tool"
    repository.mkdir(parents=True)
    slug = "example/synthetic-tool"
    urls = {"scp": "git@github.com:Example/synthetic-tool.git",
            "ssh": "ssh://git@github.com/Example/synthetic-tool.git",
            "https": "https://github.com/Example/synthetic-tool.git"}
    return {"home": home, "repository": repository, "slug": slug, "url": urls[url_form]}


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


def review13_publication_cases():
    """Synthetic identity/routing and diagnostic compatibility inputs."""
    return {
        "repo_path": "/synthetic/private-companion",
        "fetch": "acmecorp/synthetic-fetch",
        "selected": "mirror",
        "routes": {
            "origin": ["acmecorp/synthetic-fetch", "acmecorp/synthetic-origin-push"],
            "mirror": ["acmecorp/synthetic-default-push"],
        },
        "visibility": ["PRIVATE", "PUBLIC", "UNKNOWN"],
        "timeouts": [1, 20, 0.5],
        "missing_identities": [None, ""],
        "how": "synthetic visibility",
        "helper_failure": "Synthetic publication helper failure",
    }

def materialize_review13_repositories(layout):
    """Use native Git to materialize every generated fetch and push identity."""
    case = review13_publication_cases()
    root = layout["private"]

    def git(*args):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)

    def url(slug):
        return "https://github.com/" + slug + ".git"

    git("remote", "set-url", "origin", url(case["fetch"]))
    for remote, targets in case["routes"].items():
        if remote != "origin":
            git("remote", "add", remote, url(targets[0]))
        for slug in targets:
            git("config", "--add", "remote." + remote + ".pushurl", url(slug))
    git("config", "remote.pushDefault", case["selected"])
    states = json.loads(layout["visibility"].read_text(encoding="utf-8"))
    identities = sorted({case["fetch"], *(slug for values in case["routes"].values() for slug in values)})
    states.update({slug: "PRIVATE" for slug in identities})
    write_json(layout["visibility"], states)
    return {**case, "identities": identities}


# Source14 author inputs: every record and Git object is synthetic.
def review14_resolver(marker="base"):
    return ("MARKER = %r\n"
            "def resolve_companion_root(name):\n    return None\n"
            "def assert_outside_own_repo(path, name):\n    return None\n"
            "def _own_repo_root():\n    return 'synthetic'\n") % marker


def review14_trim_layout(root, collision=False):
    import json
    root = Path(root)
    paths = ([root / "library/a_b/SKILL.md", root / "library/a/b_SKILL.md"]
             if collision else [root / "library/alpha/SKILL.md", root / "library/beta/SKILL.md"])
    rows, originals, metadata = [], {}, {}
    for i, path in enumerate(paths):
        path.parent.mkdir(parents=True, exist_ok=True)
        old = "Synthetic original description %d." % i
        name = "acme-fixture-%d" % i
        before = "---\nname: %s\ndescription: %s\n---\nSynthetic body %d.\n" % (name, old, i)
        path.write_text(before, encoding="utf-8")
        originals[str(path)] = before
        new = "Reviewed synthetic description %d." % i
        after = before.replace("description: " + old, "description: " + json.dumps(new))
        for text, description in ((before, old), (after, new)):
            metadata[text] = (name, description)
            metadata[text.split("---\n", 2)[0] + "---\n" + text.split("---\n", 2)[1] + "---\n"] = (name, description)
        rows.append({"path": str(path), "name": name, "old": old,
                     "new": "Reviewed synthetic description %d." % i, "cap": 100})
    worklist = root / "worklist.json"
    worklist.write_text(json.dumps(rows), encoding="utf-8")
    return {"worklist": worklist, "backup": root / "backups",
            "paths": paths, "originals": originals, "metadata": metadata}


def review14_git_object(admin, kind, payload):
    """Write a synthetic loose object using stored DEFLATE blocks, without a commit command."""
    import hashlib
    raw = ("%s %d\0" % (kind, len(payload))).encode("ascii") + payload
    digest = hashlib.sha1(raw).hexdigest()
    compressed = bytearray(b"\x78\x01")
    for start in range(0, len(raw), 65535):
        block = raw[start:start + 65535]
        compressed.append(1 if start + len(block) == len(raw) else 0)
        compressed.extend(len(block).to_bytes(2, "little"))
        compressed.extend((len(block) ^ 65535).to_bytes(2, "little"))
        compressed.extend(block)
    a, b = 1, 0
    for value in raw:
        a = (a + value) % 65521
        b = (b + a) % 65521
    compressed.extend(((b << 16) | a).to_bytes(4, "big"))
    path = Path(admin) / "objects" / digest[:2] / digest[2:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(compressed)
    return digest


def review14_guard_revision(admin, resolver_text):
    blob = review14_git_object(admin, "blob", resolver_text.encode("utf-8"))
    tools_tree = review14_git_object(admin, "tree", b"100644 datadir.py\0" + bytes.fromhex(blob))
    tree = review14_git_object(admin, "tree", b"40000 tools\0" + bytes.fromhex(tools_tree))
    commit = ("tree %s\nauthor Fixture User <user1@example.com> 946684800 +0000\n"
              "committer Fixture User <user1@example.com> 946684800 +0000\n\n"
              "Synthetic resolver fixture.\n") % tree
    revision = review14_git_object(admin, "commit", commit.encode("ascii"))
    path = Path(admin) / "refs/heads/main"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(revision + "\n", encoding="ascii")
    return revision


def review14_repository_config(repo, visibility):
    slug = "synthetic-private" if visibility == "PRIVATE" else "synthetic-public"
    text = ("[core]\n\trepositoryformatversion = 0\n\tbare = false\n"
            "[remote \"origin\"]\n\turl = https://github.com/AcmeCorp/%s.git\n") % slug
    (Path(repo) / ".git/config").write_text(text, encoding="utf-8")
    return "acmecorp/" + slug

def review14_existing_backup(backup):
    root = Path(backup) / "desc-trim-20010101-000000-generated-run"
    root.mkdir(parents=True)
    sentinel = root / "sentinel.txt"
    value = "synthetic existing backup\n"
    sentinel.write_text(value, encoding="utf-8")
    return sentinel, value


def review14_plugin_identity(consumer):
    path = Path(consumer) / ".claude-plugin/plugin.json"
    path.parent.mkdir()
    path.write_text('{"name":"acme-fixture"}\n', encoding="utf-8")


def review14_visibility(slug):
    value = ("PRIVATE" if slug == "acmecorp/synthetic-private" else
             "PUBLIC" if slug == "acmecorp/synthetic-public" else "UNKNOWN")
    return value, "synthetic"


def materialize_review14_repositories(layout):
    """Configure the native output fixture for the physical-repository regressions."""
    states = json.loads(layout["visibility"].read_text(encoding="utf-8"))
    for key, visibility in (("private", "PRIVATE"), ("public", "PUBLIC")):
        slug = review14_repository_config(layout[key], visibility)
        states[slug] = visibility
    write_json(layout["visibility"], states)


def review14_routing_scenarios(private, public):
    return [
        ("private", private, {}, True),
        ("public", public, {}, False),
        ("borrowed-repository", public,
         {"GIT_DIR": str(private / ".git"), "GIT_WORK_TREE": str(private)}, False),
        ("borrowed-url", public,
         {"GIT_CONFIG_COUNT": "1",
          "GIT_CONFIG_KEY_0": "url.https://github.com/AcmeCorp/synthetic-private.git.insteadOf",
          "GIT_CONFIG_VALUE_0": "https://github.com/AcmeCorp/synthetic-public.git"}, False),
        ("effective-public-push", private,
         {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "remote.origin.pushurl",
          "GIT_CONFIG_VALUE_0": "https://github.com/AcmeCorp/synthetic-public.git"}, False),
    ]


def review16_budget_inputs():
    """Synthetic inventory and explicit policy for projection/observation regressions."""
    return {
        "records": review15_budget_records(),
        "argv": ["budget_check", "--skills-dir", "synthetic", "--code-root", "synthetic",
                 "--installed-plugins", "synthetic"],
        "listing": "synthetic-listing",
        "capacity": 1,
        "fleet_arguments": ("synthetic", "synthetic", 5),
    }


def review16_git_verification_inputs():
    """Repository selectors and config injection must not reach kit verification."""
    return {
        "root": "synthetic-repository",
        "args": ("rev-parse", "--verify", "HEAD"),
        "stdout": "synthetic-pinned-object\n",
        "environment": {
            "PATH": "synthetic-path",
            "SYNTHETIC_KEEP": "yes",
            "GIT_DIR": "synthetic/foreign/.git",
            "git_work_tree": "synthetic/foreign",
            "GIT_COMMON_DIR": "synthetic/common",
            "GIT_INDEX_FILE": "synthetic/index",
            "GIT_OBJECT_DIRECTORY": "synthetic/objects",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES": "synthetic/alternate",
            "GIT_NAMESPACE": "synthetic-namespace",
            "GIT_REPLACE_REF_BASE": "refs/synthetic-replacements/",
            "GIT_NO_REPLACE_OBJECTS": "0",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.worktree",
            "GIT_CONFIG_VALUE_0": "synthetic/foreign",
            "GIT_CONFIG_PARAMETERS": "'core.worktree=synthetic/foreign'",
            "GIT_CONFIG_GLOBAL": "synthetic/global-config",
            "GIT_CONFIG_SYSTEM": "synthetic/system-config",
        },
    }


def review17_git_mutation_inputs(kits):
    """Synthetic selector injection plus the restricted offline mirror transport."""
    inputs = review16_git_verification_inputs()
    transport = [("protocol.file.allow", "always")]
    transport.extend(("url.file:///synthetic/mirrors/%s.insteadOf" % path, url)
                     for url, path in kits)
    untrusted = [
        ("core.autocrlf", "true"),
        ("core.worktree", "synthetic/foreign"),
        ("core.hooksPath", "synthetic/foreign-hooks"),
        ("url.https://example.com/synthetic-mirror.git.insteadOf", kits[0][0]),
        ("url.file://example.invalid/synthetic-mirror.git.insteadOf", kits[0][0]),
        ("url.file:////example.invalid/synthetic-mirror.git.insteadOf", kits[0][0]),
        ("url.file:///%2Fexample.invalid/synthetic-mirror.git.insteadOf", kits[0][0]),
        ("url.file:///%5Cexample.invalid/synthetic-mirror.git.insteadOf", kits[0][0]),
    ]
    environment = inputs["environment"]
    environment["GIT_ALLOW_PROTOCOL"] = "file"
    environment["GIT_CONFIG_COUNT"] = str(len(transport) + len(untrusted))
    for index, (key, value) in enumerate(transport + untrusted):
        environment["GIT_CONFIG_KEY_%d" % index] = key
        environment["GIT_CONFIG_VALUE_%d" % index] = value
    expected_transport = [("core.autocrlf", "false"), *transport]
    expected = {"PATH": environment["PATH"], "SYNTHETIC_KEEP": environment["SYNTHETIC_KEEP"],
                "GIT_NO_REPLACE_OBJECTS": "1", "GIT_ALLOW_PROTOCOL": "file",
                "GIT_CONFIG_COUNT": str(len(expected_transport))}
    for index, (key, value) in enumerate(expected_transport):
        expected["GIT_CONFIG_KEY_%d" % index] = key
        expected["GIT_CONFIG_VALUE_%d" % index] = value
    inputs["expected_mutation_environment"] = expected
    inputs["name"] = "synthetic-tool"
    return inputs


def review17_invalid_transport_cases():
    return [
        {"id": "invalid-count", "updates": {"GIT_CONFIG_COUNT": "synthetic-invalid"}, "remove": []},
        {"id": "missing-value", "updates": {}, "remove": ["GIT_CONFIG_VALUE_0"]},
    ]


def review17_budget_cases():
    """Cover each red reason independently and together under nontrimmable capacity."""
    cases = []
    for cap, missing in ((False, False), (False, True), (True, False), (True, True)):
        inputs = review16_budget_inputs()
        if cap:
            inputs["records"][0]["tier"] = "ours"
        inputs.update({"id": "cap-%d-missing-%d" % (cap, missing),
                       "listing_rows": review15_listing(inputs["records"], missing),
                       "expected_cap_over_ours": int(cap), "expected_min_lost": int(missing)})
        cases.append(inputs)
    return cases


def review18_kit_payload(directory, required, *, omitted=None, mode="100644",
                         object_format="sha1"):
    """Generate a kit working tree and independent synthetic Git tree response."""
    import hashlib

    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    rows = []
    for name in required:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = ("# synthetic kit member: %s\n" % name).encode("utf-8")
        path.write_bytes(payload)
        path.chmod(0o755 if mode == "100755" else 0o644)
        if name != omitted:
            framed = b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload
            digest = hashlib.new(object_format, framed).hexdigest()
            rows.append("%s blob %s\t%s" % (mode, digest, name))
    if omitted:
        payload = (omitted + "\n").encode("utf-8")
        (root / ".gitignore").write_bytes(payload)
        framed = b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload
        rows.append("100644 blob %s\t.gitignore" % hashlib.new(object_format, framed).hexdigest())
    return {"root": root, "revision": "synthetic-pinned-revision",
            "entries": "\0".join(rows) + "\0", "required": list(required)}


def review19_checkout_layout(directory, kits, required_files):
    """Synthetic local mirrors and an ordinary global CRLF checkout preference."""
    root = Path(directory)
    home = root / "home"
    template = root / "empty-git-template"
    repository = root / "scaffold"
    for path in (home, template, repository):
        path.mkdir(parents=True)
    global_config = home / ".gitconfig"
    global_bytes = ("[core]\n\tautocrlf = true\n\thooksPath = %s\n"
                    "[init]\n\ttemplateDir = %s\n") % (template.as_posix(), template.as_posix())
    global_bytes = global_bytes.encode("utf-8")
    with global_config.open("xb") as stream:
        stream.write(global_bytes)
    # The inherited conflict must be discarded before the owned checkout option is added.
    transport = [("core.autocrlf", "true"), ("protocol.file.allow", "always")]
    mirrors = {}
    for url, kit in kits:
        mirror = root / "mirrors" / kit
        admin = mirror / ".git"
        (admin / "objects").mkdir(parents=True)
        (admin / "refs/heads").mkdir(parents=True)
        payloads = {}
        for relative in required_files[kit]:
            payload = ("# synthetic checkout member: %s\n# stable LF blob\n" % relative).encode("utf-8")
            path = mirror / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(payload)
            payloads[relative] = payload
        tree = review15_tree(admin, payloads)
        commit = ("tree %s\nauthor Fixture User <user1@example.com> 946684800 +0000\n"
                  "committer Fixture User <user1@example.com> 946684800 +0000\n\n"
                  "Synthetic checkout fixture.\n") % tree
        revision = review14_git_object(admin, "commit", commit.encode("ascii"))
        for relative, payload in {
            "HEAD": b"ref: refs/heads/main\n",
            "config": b"[core]\n\trepositoryformatversion = 0\n\tbare = false\n\tautocrlf = false\n",
            "refs/heads/main": (revision + "\n").encode("ascii"),
        }.items():
            with (admin / relative).open("xb") as stream:
                stream.write(payload)
        transport.append(("url.%s.insteadOf" % mirror.as_uri(), url))
        mirrors[kit] = {"mirror": mirror, "revision": revision, "payloads": payloads}
    environment = {"HOME": str(home), "USERPROFILE": str(home),
                   "GIT_ALLOW_PROTOCOL": "file", "GIT_CONFIG_COUNT": str(len(transport))}
    for index, (key, value) in enumerate(transport):
        environment["GIT_CONFIG_KEY_%d" % index] = key
        environment["GIT_CONFIG_VALUE_%d" % index] = value
    return {"root": repository, "environment": environment, "mirrors": mirrors,
            "global_config": global_config, "global_bytes": global_bytes,
            "name": "synthetic-checkout-tool", "changed_member": "tools/pii_guard.py",
            "changed_payload": b"# synthetic genuine edit\n"}
