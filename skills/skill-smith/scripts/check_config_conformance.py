#!/usr/bin/env python3
"""Config-bearing skill gate (Acceptance Gate G8). See ../reference/config-spec.md.

Auto-detects whether a skill repo is *config-bearing* (ships a companion config / secrets template /
registry.json / init+verify scripts / a README Config section). If it is, enforces the seven-element
standard E1-E7 with PASS/FAIL per element -- including a LIVE deterministic-generation test (E4) and a
hot-swap test (E5) by actually running the repo's own init_config.py / verify_config.py. A
config-bearing repo failing any element is a reject. A non-config-bearing repo is reported as such and
skips the gate (exit 0).

Usage:
  python check_config_conformance.py <repo_dir> [--no-run]
--no-run skips the dynamic E4/E5 subprocess tests (static checks only).
Exit 0 = pass (or not config-bearing); 1 = config-bearing and failing; 2 = usage error.
Stdlib only. Never echoes secrets.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import shutil

PASS, FAIL = "PASS", "FAIL"


def read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None


def find_script(root, *names):
    for n in names:
        p = os.path.join(root, "scripts", n)
        if os.path.isfile(p):
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
    if os.path.isdir(sk):
        for d in os.listdir(sk):
            t = read(os.path.join(sk, d, "SKILL.md"))
            if t:
                parts.append(("skills/%s/SKILL.md" % d, t))
    if os.path.isfile(os.path.join(root, "SKILL.md")):
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
    if os.path.isfile(os.path.join(root, "CONFIG.md")):
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


def main(root, no_run):
    root = os.path.abspath(os.path.expanduser(root))
    name = plugin_name(root)
    env_var = (name or "skill").upper().replace("-", "_") + "_CONFIG"
    texts = collect_text(root)
    blob = "\n".join(t for _, t in texts)

    signals = is_config_bearing(root, texts)
    print("Config-bearing gate (G8): %s" % root)
    print("skill=%s  env var=%s" % (name, env_var))
    print("-" * 64)
    if not signals:
        print("  NOT config-bearing (no companion-config signals) -> G8 not applicable.")
        print("-" * 64)
        print("SKIP: this skill does not bear config; gate passes vacuously.")
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
    e6_skill = ("secrets/" in gi) and ("*.env" in gi)
    # no committed real secrets in the skill repo
    leaked = []
    sdir = os.path.join(root, "secrets")
    if os.path.isdir(sdir):
        for b, _, fs in os.walk(sdir):
            for fn in fs:
                if fn.endswith(".env") and not fn.endswith(".template"):
                    leaked.append(os.path.relpath(os.path.join(b, fn), root))
    check("E6 secrets isolation (.gitignore blocks secrets, none committed)",
          e6_skill and not leaked,
          ("gitignore missing secrets/*+*.env; " if not e6_skill else "") +
          ("committed secrets: %s" % leaked if leaked else ""))

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

    # ---- dynamic E4 (deterministic) + E5 (hot-swap), via the repo's own scripts ----
    if no_run:
        print("  NOTE: --no-run -> E4 (deterministic) + E5 (hot-swap) not exercised this run.")
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
            same = ok_init and (tree_snapshot(a_dir) == tree_snapshot(b_dir))
            check("E4 deterministic generation (init x2 identical)", same,
                  "init failed" if not ok_init else "two inits differ -> not template-driven")

            # E5: verify each, then prove env-var switch resolves the pointed-at config
            if ok_init:
                v_a = run([verify], env={env_var: a_dir}, cwd=root)
                v_b = run([verify], env={env_var: b_dir}, cwd=root)
                resolves_a = v_a.returncode == 0 and a_dir.replace("\\", "/") in v_a.stdout.replace("\\", "/")
                resolves_b = v_b.returncode == 0 and b_dir.replace("\\", "/") in v_b.stdout.replace("\\", "/")
                # generated config self-contained (no abs-path leak), also enforced by verify itself
                check("E5 hot-swap (two configs, env-var switch verifies)",
                      resolves_a and resolves_b,
                      "verify did not resolve+validate the env-pointed config on both legs")
            else:
                check("E5 hot-swap (two configs, env-var switch verifies)", False, "init failed")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # report
    n_fail = sum(1 for _, ok, _ in results if not ok)
    for tag, ok, detail in results:
        line = "  [%s] %s" % (PASS if ok else FAIL, tag)
        if detail and not ok:
            line += "  -> %s" % detail
        print(line)
    print("-" * 64)
    total = len(results)
    if n_fail:
        print("%d/%d elements pass  (%d FAIL) -> REJECT: config-bearing skill is not configurable."
              % (total - n_fail, total, n_fail))
        return 1
    print("%d/%d elements pass -> ACCEPT (config standard met)." % (total, total))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--no-run", action="store_true")
    a = ap.parse_args()
    sys.exit(main(a.repo, a.no_run))
