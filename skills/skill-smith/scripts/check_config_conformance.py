#!/usr/bin/env python3
"""Config-bearing skill gate (Acceptance Gate G8). See ../reference/config-spec.md.

Auto-detects whether a skill repo is *config-bearing* (ships a companion config / secrets template /
registry.json / init+verify scripts / a README Config section). If it is,
enforces the eight-element standard E1-E8 with PASS/FAIL/NOT_RUN per element. E4 runs deterministic generation;
E5 checks explicitly supplied, already configured A/B directories with the repo's doctor.
Blank generated templates are not functional-readiness evidence.
Tools that only declare runtime storage validate E8; settings elements E1-E7 are not applicable.

Usage:
  python check_config_conformance.py <repo_dir> [--no-run] [--config-a DIR --config-b DIR]
--no-run skips the dynamic E4/E5 subprocess tests (static checks only).
Exit 0 = applicable elements passed (or none apply); 1 = failed; 2 = incomplete or usage error.
Stdlib only. Never echoes secrets.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import shutil
import stat
import importlib.util

import storage_contract

PASS, FAIL = "PASS", "FAIL"


def read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None


def path_mode(path, *, follow_symlinks=True):
    """Treat an absent optional path separately from a path we cannot inspect."""
    try:
        return os.stat(path, follow_symlinks=follow_symlinks).st_mode
    except FileNotFoundError:
        return 0


def find_script(root, *names):
    for n in names:
        p = os.path.join(root, "scripts", n)
        if stat.S_ISREG(path_mode(p)):
            return p
    return None


def plugin_name(root):
    pj = read(os.path.join(root, ".claude-plugin", "plugin.json"))
    if pj:
        try:
            return json.loads(pj).get("name")
        except Exception:
            pass
    return os.path.basename(os.path.abspath(root))


def collect_text(root):
    """README + CN + CONFIG.md + SKILL.md(s) concatenated, for documentation heuristics."""
    parts = []
    for rel in ("README.md", "README_CN.md", "CONFIG.md"):
        t = read(os.path.join(root, rel))
        if t:
            parts.append((rel, t))
    sk = os.path.join(root, "skills")
    if stat.S_ISDIR(path_mode(sk)):
        for d in os.listdir(sk):
            t = read(os.path.join(sk, d, "SKILL.md"))
            if t:
                parts.append(("skills/%s/SKILL.md" % d, t))
    if stat.S_ISREG(path_mode(os.path.join(root, "SKILL.md"))):
        t = read(os.path.join(root, "SKILL.md"))
        if t:
            parts.append(("SKILL.md", t))
    return parts


def is_config_bearing(root, texts):
    """Heuristic detection (config-spec): any strong signal that the skill needs companion config."""
    signals = []
    if find_script(root, "init_config.py", "init-config.py"):
        signals.append("scripts/init_config.py")
    if find_script(root, "verify_config.py", "verify-config.py"):
        signals.append("scripts/verify_config.py")
    if stat.S_ISREG(path_mode(os.path.join(root, "CONFIG.md"))):
        signals.append("CONFIG.md")
    blob = "\n".join(t for _, t in texts)
    if "## Config" in blob or "## 配置" in blob:
        signals.append("README Config section")
    if "registry.json" in blob:
        signals.append("registry.json reference")
    if "companion config" in blob.lower() or "companion-config" in blob.lower():
        signals.append("companion-config reference")
    if "_CONFIG" in blob and ("env var" in blob.lower() or "environment variable" in blob.lower()
                              or "discovery" in blob.lower()):
        signals.append("discovery env var")
    return signals


def run(args, env=None, cwd=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run([sys.executable] + args, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120, env=e, cwd=cwd)


def tree_snapshot(d):
    """Map relpath -> bytes for every file under d (for deterministic diffing)."""
    out = {}
    for base, _, files in os.walk(d):
        for fn in files:
            p = os.path.join(base, fn)
            rel = os.path.relpath(p, d).replace("\\", "/")
            with open(p, "rb") as f:
                out[rel] = f.read()
    return out


def doctor_selected_root(output, requested):
    """Compare the complete canonical root reported by the generated doctor's stable line."""
    reported = []
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("resolved via ") and " -> " in line:
            reported.append(line.split(" -> ", 1)[1].strip())
        elif line.startswith("RESOLVED:"):
            reported.append(line[len("RESOLVED:"):].strip())
    if len(reported) != 1 or not os.path.isabs(reported[0]):
        return False
    canonical = lambda path: os.path.normcase(os.path.realpath(os.path.expanduser(path)))
    return canonical(reported[0]) == canonical(requested)


def storage_contract_result(root):
    """Validate the source declaration without inspecting runtime companion contents."""
    try:
        storage_contract.validate_contract(root)
    except (OSError, ValueError) as exc:
        return False, str(exc)
    return True, ""


def check_config(root, no_run, config_a=None, config_b=None):
    name = plugin_name(root)
    env_var = (name or "skill").upper().replace("-", "_") + "_CONFIG"
    texts = collect_text(root)
    blob = "\n".join(t for _, t in texts)

    signals = is_config_bearing(root, texts)
    print("Config-bearing gate (G8): %s" % root)
    print("skill=%s  env var=%s" % (name, env_var))
    print("-" * 64)
    if not signals:
        if path_mode(os.path.join(root, "storage.contract.json"), follow_symlinks=False):
            print("  [NOT_APPLICABLE] E1-E7 settings configuration (no configuration signals)")
            ok, detail = storage_contract_result(root)
            line = "  [%s] E8 main-repo storage.contract.json is valid" % (PASS if ok else FAIL)
            print(line + ("  -> " + detail if detail else ""))
            print("Storage declaration %s; configuration conformance and readiness were not measured."
                  % ("passed" if ok else "failed"))
            return 0 if ok else 1
        print("  NOT config-bearing (no companion-config signals) -> G8 not applicable.")
        print("-" * 64)
        print("NOT_APPLICABLE: no configuration conformance or readiness was measured.")
        return 0
    print("  config-bearing signals: %s" % ", ".join(signals))
    print("-" * 64)

    results = []

    def check(tag, ok, detail=""):
        results.append((tag, ok, detail))

    config_md = read(os.path.join(root, "CONFIG.md")) or ""
    readme = read(os.path.join(root, "README.md")) or ""
    readme_cn = read(os.path.join(root, "README_CN.md")) or ""

    # E1, schema documented
    schema_doc = ("schema_version" in config_md and "registry.json" in config_md) or \
                 ("schema_version" in blob and "## Config" in readme)
    check("E1 schema documented (fields/types in CONFIG.md or README)", schema_doc,
          "need registry.json schema_version + fields in CONFIG.md or README Config section")

    # E2, discovery convention documented (env var + fallback path, ordered)
    e2 = (env_var in blob) and (("~/.%s-config" % name) in blob or "~/.config/" in blob) \
        and ("CONFIG_DIR" in blob or "fallback" in blob.lower() or "order" in blob.lower()
             or "discovery" in blob.lower())
    check("E2 discovery convention documented (env var + fallback)", e2,
          "document %s + ~/.%s-config fallback order" % (env_var, name))

    # E3, init + verify scripts present
    init = find_script(root, "init_config.py", "init-config.py")
    verify = find_script(root, "verify_config.py", "verify-config.py")
    check("E3 init + verify scripts present", bool(init and verify),
          "need scripts/init_config.py + scripts/verify_config.py")

    # E6, secrets isolation (skill repo .gitignore blocks secrets)
    gi = read(os.path.join(root, ".gitignore")) or ""
    runtime = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "config", "config_runtime.py"))
    spec = importlib.util.spec_from_file_location("_skill_smith_ignore_rules", runtime)
    if spec is None or spec.loader is None:
        raise RuntimeError("Required config ignore checker is unavailable")
    rules = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rules)
    ignore_problems = rules.secrets_ignore_problems(gi)
    # Inspect present files only; this does not establish what Git tracks or retains in history.
    leaked = []
    sdir = os.path.join(root, "secrets")
    if os.path.isdir(sdir):
        for b, _, fs in os.walk(sdir):
            for fn in fs:
                if fn.endswith(".env") and not fn.endswith(".template"):
                    leaked.append(os.path.relpath(os.path.join(b, fn), root))
    check("E6 root ignore rules exclude representative secret paths; no local secrets/*.env",
          not ignore_problems and not leaked,
          "; ".join(ignore_problems + (["local secret files: %s" % leaked] if leaked else [])))

    # E7, README Config section (EN + CN) with mount + first-time + switch
    def has_config_section(t, cn=False):
        head = "## 配置" if cn else "## Config"
        if head not in t:
            return False
        seg = t[t.find(head):]
        return (env_var in seg) and ("init_config" in seg) and \
               ("switch" in seg.lower() or "swap" in seg.lower() or "切换" in seg)
    e7 = has_config_section(readme) and has_config_section(readme_cn, cn=True)
    check("E7 README Config section (EN+CN: mount+first-time+switch)", e7,
          "both README.md and README_CN.md need a Config/配置 section w/ env var + init + switch")

    # E8 validates the source contract; inspecting the PRIVATE companion is a separate check.
    check("E8 main-repo storage.contract.json is valid", *storage_contract_result(root))

    # ---- dynamic E4 (deterministic) + E5 (hot-swap), via the repo's own scripts ----
    if no_run:
        check("E4 deterministic generation (init x2 identical)", None, "static_not_executed")
        check("E5 configured hot-swap (two configs, env-var switch verifies)", None, "static_not_executed")
    elif not (init and verify):
        check("E4 deterministic generation (init x2 identical)", False, "init/verify missing")
        check("E5 hot-swap (two configs, env-var switch verifies)", False, "init/verify missing")
    else:
        tmp = tempfile.mkdtemp(prefix="cfgconf_")
        try:
            a_dir = os.path.join(tmp, "A")
            b_dir = os.path.join(tmp, "B")
            r1 = run([init, "--out", a_dir], cwd=root)
            r2 = run([init, "--out", b_dir], cwd=root)
            ok_init = r1.returncode == 0 and r2.returncode == 0
            # E4: byte-identical trees (path-independent content) => template-driven determinism
            a_template, b_template = tree_snapshot(a_dir), tree_snapshot(b_dir)
            same = ok_init and bool(a_template) and a_template == b_template
            check("E4 deterministic generation (init x2 identical)", same,
                  "init failed" if not ok_init else "generated templates are empty or differ")

            # Template validation and configured readiness are separate lifecycle stages.
            if ok_init:
                if config_a is None and config_b is None:
                    check("E5 configured hot-swap (two configs, env-var switch verifies)", None,
                          "configuration_required: fill two generated synthetic configs, then supply --config-a and --config-b; blank templates do not establish readiness")
                elif not config_a or not config_b:
                    check("E5 configured hot-swap (two configs, env-var switch verifies)", False,
                          "both --config-a and --config-b are required")
                else:
                    a_config = os.path.realpath(os.path.expanduser(config_a))
                    b_config = os.path.realpath(os.path.expanduser(config_b))
                    if os.path.normcase(a_config) == os.path.normcase(b_config) or not all(os.path.isdir(path) for path in (a_config, b_config)):
                        check("E5 configured hot-swap (two configs, env-var switch verifies)", False,
                              "two distinct existing config directories are required")
                    else:
                        v_a = run([verify], env={env_var: a_config}, cwd=root)
                        v_b = run([verify], env={env_var: b_config}, cwd=root)
                        resolves_a = v_a.returncode == 0 and doctor_selected_root(v_a.stdout, a_config)
                        resolves_b = v_b.returncode == 0 and doctor_selected_root(v_b.stdout, b_config)
                        check("E5 configured hot-swap (two configs, env-var switch verifies)",
                              resolves_a and resolves_b,
                              "configured doctor must resolve+validate both selected roots; functional journey evidence is separate")
            else:
                check("E5 hot-swap (two configs, env-var switch verifies)", False, "init failed")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # report
    n_fail = sum(1 for _, ok, _ in results if ok is False)
    n_missing = sum(1 for _, ok, _ in results if ok is None)
    for tag, ok, detail in results:
        line = "  [%s] %s" % (PASS if ok else "NOT_RUN" if ok is None else FAIL, tag)
        if detail and ok is not True:
            line += "  -> %s" % detail
        print(line)
    print("-" * 64)
    total = len(results)
    if n_fail:
        print("%d/%d elements pass  (%d FAIL, %d NOT_RUN) -> REJECT: config checks failed."
              % (total - n_fail - n_missing, total, n_fail, n_missing))
        return 1
    if n_missing:
        print("%d/%d elements pass (%d NOT_RUN) -> INCOMPLETE: static/template checks do not establish G8."
              % (total - n_missing, total, n_missing))
        return 2
    print("%d/%d elements pass -> ACCEPT (config standard met)." % (total, total))
    return 0


def main(root, no_run, config_a=None, config_b=None):
    root = os.path.abspath(os.path.expanduser(root))
    try:
        if not stat.S_ISDIR(path_mode(root)):
            print("FAIL: G8 target must be an existing directory: %s" % root)
            return 1
        # Applicability is a result of inspection, never a fallback for failed access.
        os.listdir(root)
        return check_config(root, no_run, config_a, config_b)
    except (OSError, UnicodeError) as exc:
        print("FAIL: G8 target could not be inspected (%s); applicability is unknown."
              % type(exc).__name__)
        return 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--no-run", action="store_true")
    ap.add_argument("--config-a", help="first already configured synthetic companion directory")
    ap.add_argument("--config-b", help="second already configured synthetic companion directory")
    a = ap.parse_args()
    sys.exit(main(a.repo, a.no_run, a.config_a, a.config_b))
