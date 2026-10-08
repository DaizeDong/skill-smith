#!/usr/bin/env python3
"""G8: explicit applicability, static contracts, and opt-in synthetic lifecycle proof.

Exit 0 means applicable measured checks passed; 1 is failed/unknown; 2 is incomplete.
Neither static declarations nor synthetic doctor checks establish live functionality.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

import config_contract
import storage_contract

PASS, FAIL, NOT_RUN, NOT_APPLICABLE = "PASS", "FAIL", "NOT_RUN", "NOT_APPLICABLE"
LABELS = {
    1: "schema and required fields documented",
    2: "discovery precedence and aliases documented",
    3: "native initializer/doctor and blank-required rejection",
    4: "deterministic generation (two nonempty identical templates)",
    5: "configured A/B roots resolve and validate",
    6: "public source excludes representative secret paths",
    7: "EN/CN configuration setup and switching documentation",
    8: "main-repo storage.contract.json is valid",
}


def read(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def path_mode(path, *, follow_symlinks=True):
    try:
        return os.stat(path, follow_symlinks=follow_symlinks).st_mode
    except FileNotFoundError:
        return 0


def run(args, env=None, cwd=None, timeout=30):
    """Run reviewed native fixture entrypoints with a bounded wait and clean env."""
    if Path(args[0]).suffix == ".ps1":
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if not shell:
            raise ValueError("native PowerShell interpreter is unavailable")
        command = [shell, "-NoProfile", "-NonInteractive", "-File", *args]
    else:
        command = [sys.executable, *args]
    return subprocess.run(command, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, env=env, cwd=cwd)


def synthetic_environment(scratch, environment, selected, home=None):
    # Preserve platform executables, never inherit credentials, aliases or user config.
    allowed = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    home = Path(home) if home else Path(scratch) / "home"
    home.mkdir(exist_ok=True)
    env.update(HOME=str(home), USERPROFILE=str(home), APPDATA=str(home / "appdata"),
               LOCALAPPDATA=str(home / "local"), XDG_CONFIG_HOME=str(home / "config"),
               TEMP=str(scratch), TMP=str(scratch), PYTHONIOENCODING="utf-8",
               PYTHONDONTWRITEBYTECODE="1", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_OPTIONAL_LOCKS="0", SKILL_SMITH_SYNTHETIC="1")
    env[environment] = str(selected)
    return env


def tree_snapshot(directory):
    """Bound template inspection and reject aliases rather than reading outside the fixture."""
    root = Path(directory)
    if not root.is_dir():
        return {}
    out, size = {}, 0
    for base, dirs, files in os.walk(root, followlinks=False):
        if Path(base) == root and ".git" in dirs:
            storage_contract.no_links(root / ".git")
            dirs.remove(".git")
        for name in [*dirs, *files]:
            if name.casefold() == ".git":
                raise ValueError("synthetic configs cannot use linked or nested Git administration")
            node = Path(base) / name
            storage_contract.no_links(node)
            info = node.stat()
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)) or (node.is_file() and info.st_nlink != 1):
                raise ValueError("synthetic template contains a special file or hardlink")
        for name in files:
            node = Path(base) / name
            size += node.stat().st_size
            if size > 8 * 1024 * 1024 or len(out) >= 1024:
                raise ValueError("synthetic template exceeds 1024 files or 8 MiB")
            out[node.relative_to(root).as_posix()] = node.read_bytes()
    return out


def doctor_observation(output):
    """Read explicit native readiness plus exact root, never infer readiness from exit zero."""
    roots, states = [], []
    try:
        payload = json.loads(output)
    except (json.JSONDecodeError, ValueError):
        payload = None
    if isinstance(payload, dict):
        for key in ("resolved_root", "config_root", "config_dir"):
            if key in payload:
                roots.append(payload[key])
        if roots and all(isinstance(root, str) and os.path.isabs(root) for root in roots):
            canonical = {os.path.normcase(os.path.realpath(root)) for root in roots}
            if len(canonical) == 1:
                roots = roots[:1]
        if type(payload.get("ready")) is bool:
            states.append(payload["ready"])
        status = payload.get("status")
        if isinstance(status, str) and status.lower().replace(" ", "_") in {"ready", "not_ready", "configuration_required"}:
            states.append(status.lower() == "ready")
    else:
        for raw in output.splitlines():
            line = raw.strip()
            if line.startswith("resolved via ") and " -> " in line:
                roots.append(line.split(" -> ", 1)[1].strip())
            elif line.startswith("RESOLVED:"):
                roots.append(line[len("RESOLVED:"):].strip())
            if line.startswith("NOT READY") or line.startswith("NOT_READY"):
                states.append(False)
            elif line == "READY" or line.startswith("READY:"):
                states.append(True)
    readiness = states[0] if states and all(item is states[0] for item in states) else None
    return roots, readiness


def doctor_selected_root(output, requested):
    roots, _ = doctor_observation(output)
    if len(roots) != 1 or not isinstance(roots[0], str) or not os.path.isabs(roots[0]):
        return False
    canonical = lambda value: os.path.normcase(os.path.realpath(os.path.expanduser(value)))
    return canonical(roots[0]) == canonical(requested)


def storage_contract_result(root):
    try:
        storage_contract.validate_contract(root)
    except (OSError, ValueError) as exc:
        return False, str(exc)
    return True, ""


def report(results):
    for number in range(1, 9):
        state, detail = results[number]
        print("  [%s] E%d %s%s" % (state, number, LABELS[number], " -> " + detail if detail else ""))
    failed = sum(state == FAIL for state, _ in results.values())
    missing = sum(state == NOT_RUN for state, _ in results.values())
    applicable = sum(state != NOT_APPLICABLE for state, _ in results.values())
    passed = sum(state == PASS for state, _ in results.values())
    if failed:
        print("%d/%d elements pass (%d FAIL, %d NOT_RUN) -> REJECT: config checks failed." % (passed, applicable, failed, missing))
        return 1
    if missing:
        print("%d/%d elements pass (%d NOT_RUN) -> INCOMPLETE: readiness was not fully measured." % (passed, applicable, missing))
        return 2
    print("%d/%d applicable elements pass; live functional readiness was not measured." % (passed, applicable))
    return 0


def secret_check(root):
    runtime = Path(__file__).resolve().parents[1] / "assets/config/config_runtime.py"
    spec = importlib.util.spec_from_file_location("_skill_smith_ignore_rules", runtime)
    if spec is None or spec.loader is None:
        raise RuntimeError("required config ignore checker is unavailable")
    rules = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rules)
    problems = rules.secrets_ignore_problems(read(Path(root) / ".gitignore") or "")
    secret_dir = Path(root) / "secrets"
    if secret_dir.exists():
        # Metadata only; do not print or load secret values.
        for base, dirs, files in os.walk(secret_dir, followlinks=False):
            for name in [*dirs, *files]:
                storage_contract.no_links(Path(base) / name)
            if any(name.endswith(".env") for name in files):
                problems.append("local secrets/*.env exists")
                break
    return not problems, "; ".join(problems)


def prepared_inputs(root, synthetic_root, template_a, template_b, synthetic_home, config_a, config_b):
    """Admit explicit fixture directories without creating or approving their Git repositories."""
    supplied = [path for path in (template_a, template_b, synthetic_home, config_a, config_b) if path]
    if not supplied:
        return
    if not synthetic_root or bool(template_a) != bool(template_b) or bool(config_a) != bool(config_b):
        raise ValueError("prepared fixtures require --synthetic-root and complete A/B pairs")
    scope = storage_contract.no_links(Path(synthetic_root)).resolve()
    source = Path(root).resolve()
    roots = [storage_contract.no_links(Path(path)).resolve() for path in supplied]
    if not scope.is_dir() or any(not path.is_dir() or path == scope or not path.is_relative_to(scope) for path in roots):
        raise ValueError("prepared fixture directories must be inside the reviewed synthetic root")
    for index, path in enumerate(roots):
        if path == source or path.is_relative_to(source) or source.is_relative_to(path):
            raise ValueError("prepared fixture directories must be separate from the source")
        if any(path == other or path.is_relative_to(other) or other.is_relative_to(path) for other in roots[:index]):
            raise ValueError("prepared fixture directories must not overlap")
    for path in (template_a, template_b):
        if path and (not (Path(path) / ".git").is_dir() or tree_snapshot(path)):
            raise ValueError("prepared template roots need ordinary Git administration and no working files")
    if synthetic_home:
        tree_snapshot(synthetic_home)


def run_lifecycle(root, settings, initializer, doctor, results, config_a, config_b, synthetic_root,
                  *, template_a=None, template_b=None, synthetic_home=None, subprocess_timeout=30):
    scratch = tempfile.mkdtemp(prefix="cfgconf_")
    try:
        if type(subprocess_timeout) is not int or not 1 <= subprocess_timeout <= 300:
            raise ValueError("synthetic subprocess timeout must be between 1 and 300 seconds")
        prepared_inputs(root, synthetic_root, template_a, template_b, synthetic_home, config_a, config_b)
        a = Path(template_a) if template_a else Path(scratch) / "A"
        b = Path(template_b) if template_b else Path(scratch) / "B"

        def execute(args, selected):
            environment = synthetic_environment(scratch, settings["environment"], selected, synthetic_home)
            return run(args, env=environment, cwd=root, timeout=subprocess_timeout)

        templates, generated = [], True
        for destination in (a, b):
            args = [arg.replace("{output}", str(destination)) for arg in initializer]
            execution = execute(args, destination)
            generated = generated and execution.returncode == 0
            templates.append(tree_snapshot(destination))
        deterministic = generated and bool(templates[0]) and templates[0] == templates[1]
        results[4] = (PASS if deterministic else FAIL, "template-only evidence" if deterministic else "initialization failed, emitted no files, or differed")
        if not generated:
            results[3] = (FAIL, "initializer failed; blank-required readiness not measured")
            results[5] = (NOT_RUN, "initialization_failed")
            return
        blank_before = tree_snapshot(a)
        blank = execute(doctor, a)
        _, readiness = doctor_observation(blank.stdout)
        fields = settings["required_fields"]
        diagnosed = any(field in blank.stdout for field in fields)
        blank_ok = (blank.returncode != 0 and readiness is False and doctor_selected_root(blank.stdout, a)
                    and diagnosed and tree_snapshot(a) == blank_before)
        if readiness is None and "TEMPLATE CONFORMS" in blank.stdout:
            results[3] = (NOT_RUN, "generic template verifier has no capability-specific readiness check")
        else:
            results[3] = (PASS if blank_ok else FAIL, "blank required fields rejected" if blank_ok else "blank doctor must resolve the selected root and diagnose required fields as NOT READY")
        if not config_a and not config_b:
            results[5] = (NOT_RUN, "configuration_required: provide two reviewed synthetic configs and --synthetic-root")
            return
        if not config_a or not config_b or not synthetic_root:
            results[5] = (FAIL, "both config roots and --synthetic-root are required")
            return
        scope = storage_contract.no_links(Path(synthetic_root)).resolve()
        roots = [storage_contract.no_links(Path(path)).resolve() for path in (config_a, config_b)]
        if (roots[0] == roots[1] or not scope.is_dir()
                or any(not path.is_dir() or path == scope or not path.is_relative_to(scope) for path in roots)):
            results[5] = (FAIL, "two distinct config directories must be inside the reviewed synthetic root")
            return
        ok = True
        for selected in roots:
            before = tree_snapshot(selected)
            execution = execute(doctor, selected)
            _, readiness = doctor_observation(execution.stdout)
            ok = ok and execution.returncode == 0 and readiness is True and doctor_selected_root(execution.stdout, selected)
            ok = ok and tree_snapshot(selected) == before
        results[5] = (PASS if ok else FAIL, "synthetic doctor only; functional journey evidence is separate" if ok else "doctor must explicitly report READY for each exact root without changing config")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        for number in (3, 4, 5):
            if results[number][0] == NOT_RUN:
                results[number] = (FAIL, "synthetic proof failed: " + type(exc).__name__)
    finally:
        shutil.rmtree(scratch)


def check_config(root, no_run, config_a=None, config_b=None, *, run_synthetic=False, synthetic_root=None,
                 template_a=None, template_b=None, synthetic_home=None, subprocess_timeout=30):
    print("Configuration gate (G8): " + str(root))
    results = {number: (FAIL, "applicability UNKNOWN") for number in range(1, 9)}
    try:
        declaration = config_contract.load(root)
    except (OSError, ValueError, UnicodeError) as exc:
        print("Applicability UNKNOWN: " + type(exc).__name__ + "; inspect config.contract.json")
        ok, detail = storage_contract_result(root)
        results[8] = (PASS if ok else FAIL, detail)
        return report(results)
    mode = declaration["configuration"]
    print("Declared repository_kind=%s configuration=%s" % (declaration["repository_kind"], mode))
    if mode != "settings":
        for number in range(1, 8):
            results[number] = (NOT_APPLICABLE, "source declares " + mode)
        if mode == "none" and not os.path.lexists(Path(root) / storage_contract.CONTRACT):
            results[8] = (NOT_APPLICABLE, "source declares no runtime storage")
        else:
            ok, detail = storage_contract_result(root)
            results[8] = (PASS if ok else FAIL, detail)
        return report(results)
    settings = declaration.get("settings", {})
    if not isinstance(settings, dict):
        settings = {}

    def measure(number, operation):
        try:
            ok, detail = operation()
            results[number] = (PASS if ok else FAIL, detail)
        except (OSError, ValueError, UnicodeError, TypeError) as exc:
            results[number] = (FAIL, type(exc).__name__ + ": invalid or missing source declaration/reference")

    def schema():
        document = config_contract.source_file(root, settings.get("schema_document")).read_text(encoding="utf-8")
        fields = config_contract.strings(settings.get("required_fields"), "required_fields")
        return bool(document.strip()) and bool(fields), "native schema reference; semantic field coverage requires review"

    def discovery():
        document = config_contract.source_file(root, settings.get("discovery_document")).read_text(encoding="utf-8")
        environment = settings.get("environment")
        if not isinstance(environment, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", environment):
            raise ValueError("environment must be an explicit variable name")
        aliases = config_contract.strings(settings.get("aliases"), "aliases", nonempty=False)
        if any(not re.fullmatch(r"[A-Z][A-Z0-9_]*", alias) or alias == environment for alias in aliases):
            raise ValueError("aliases must name distinct environment variables")
        config_contract.strings(settings.get("precedence"), "precedence")
        return all(name in document for name in [environment, *aliases]), "source declares precedence; docs must name primary and aliases"

    measure(1, schema)
    measure(2, discovery)
    initializer = doctor = None
    try:
        initializer = config_contract.command(root, settings.get("initializer"), initializer=True)
        doctor = config_contract.command(root, settings.get("doctor"))
        results[3] = (NOT_RUN, "native entrypoints present; blank-required readiness static_not_executed")
    except (OSError, ValueError, TypeError) as exc:
        results[3] = (FAIL, "native init/doctor unavailable: " + type(exc).__name__)
    measure(6, lambda: secret_check(root))

    def readmes():
        environment = settings.get("environment", "")
        for filename, heading in (("README.md", "## Config"), ("README_CN.md", "## 配置")):
            document = read(Path(root) / filename) or ""
            if heading not in document or not environment or environment not in document:
                return False, "EN/CN Config sections must name selection and explain native initialization and switching"
            if not any(word in document.lower() for word in ("switch", "swap", "切换")):
                return False, "EN/CN setup must explain switching"
        return True, "native lifecycle semantics require independent document review"

    measure(7, readmes)
    measure(8, lambda: storage_contract_result(root))
    for number in (4, 5):
        results[number] = (NOT_RUN, "static_not_executed" if no_run else "reviewed_synthetic_execution_required: pass --run-synthetic")
    if run_synthetic and not no_run:
        if initializer and doctor and all(results[number][0] == PASS for number in (1, 2)):
            run_lifecycle(root, settings, initializer, doctor, results, config_a, config_b, synthetic_root,
                          template_a=template_a, template_b=template_b, synthetic_home=synthetic_home,
                          subprocess_timeout=subprocess_timeout)
        else:
            results[4] = results[5] = (NOT_RUN, "native lifecycle/schema/discovery prerequisites failed")
    return report(results)


def main(root, no_run, config_a=None, config_b=None, *, run_synthetic=False, synthetic_root=None,
         template_a=None, template_b=None, synthetic_home=None, subprocess_timeout=30):
    root = os.path.abspath(os.path.expanduser(root))
    try:
        if not stat.S_ISDIR(path_mode(root)):
            raise ValueError("G8 target must be an existing directory")
        os.listdir(root)
        return check_config(root, no_run, config_a, config_b,
                            run_synthetic=run_synthetic, synthetic_root=synthetic_root,
                            template_a=template_a, template_b=template_b, synthetic_home=synthetic_home,
                            subprocess_timeout=subprocess_timeout)
    except (OSError, UnicodeError, ValueError) as exc:
        print("FAIL: G8 target could not be inspected (%s); applicability is UNKNOWN." % type(exc).__name__)
        return report({number: (FAIL, "inspection_failed") for number in range(1, 9)})


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("repo")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--no-run", action="store_true")
    mode.add_argument("--run-synthetic", action="store_true", help="run inspected native entrypoints only on reviewed synthetic fixtures")
    ap.add_argument("--config-a")
    ap.add_argument("--config-b")
    ap.add_argument("--synthetic-root", help="reviewed generated fixture directory containing both selected config roots")
    ap.add_argument("--template-a", help="prepared synthetic Git companion with no working files, for first initialization")
    ap.add_argument("--template-b", help="second independent prepared synthetic Git companion")
    ap.add_argument("--synthetic-home", help="generated HOME under --synthetic-root, including synthetic visibility receipts")
    ap.add_argument("--subprocess-timeout", type=int, default=30, help="native synthetic command timeout, 1 to 300 seconds (default 30)")
    a = ap.parse_args()
    sys.exit(main(a.repo, a.no_run, a.config_a, a.config_b,
                  run_synthetic=a.run_synthetic, synthetic_root=a.synthetic_root,
                  template_a=a.template_a, template_b=a.template_b, synthetic_home=a.synthetic_home,
                  subprocess_timeout=a.subprocess_timeout))
