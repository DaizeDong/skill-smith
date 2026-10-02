#!/usr/bin/env python3
"""Initialize a deterministic companion config skeleton outside the consuming tool repo.

Uses the emitted consumer identity and its pinned guards resolver, regardless of caller cwd.
Explicit --out, CONFIG and CONFIG_DIR selections take precedence. Without a selection, reuse
an existing companion; create ~/.<skill>-config only when no companion exists.

Usage: python scripts/init_config.py [--skill <consumer-name>] [--out <dir>] [--force]
Stdlib only. Never writes secrets. A skeleton does not establish functional readiness.
"""
import argparse
import json
import os
from pathlib import Path
import sys

from config_runtime import ConfigRuntime, env_var

GITIGNORE = """\
# Secrets gate (config-spec E6 / Mode B) — real values never enter git.
secrets/*
!secrets/README.md
!secrets/.gitkeep
*.env
!*.env.template
!env.template
claude.json
.claude.json
*credentials*.json
*.key
*.pem
!*.key.template
!*.pem.template
"""

SECRETS_README = """\
# secrets/ — Mode B (gitignored)

Real secret values live here and are **gitignored** (see ../.gitignore). They never enter git.
Back them up out-of-band (cloud sync / encrypted drive). Restore on a new machine by copying the
`*.env` files back into this directory, then re-running the skill's verify script.

Active storage mode: **B** (gitignored + out-of-band backup).
Per tool, create `secrets/<slug>.env` with the KEY=VALUE pairs its `tools/<slug>/env.template` lists.
Files MUST be UTF-8 without BOM.
"""


def write(path, content, force):
    if os.path.exists(path) and not force:
        print("  SKIP (exists): %s" % path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print("  wrote: %s" % path)


def validate_destinations(root, paths, runtime):
    """Check every physical destination and parent before creating or replacing files."""
    root = Path(root).resolve()
    for path in paths:
        target = Path(path).resolve()
        runtime.resolver.assert_outside_own_repo(target, runtime.skill)
        if not target.is_relative_to(root):
            raise ValueError("Generated config destination escapes the selected root: %s" % path)
        if target.exists() and not target.is_file():
            raise ValueError("Generated config destination is not a file: %s" % path)
        parent = target.parent
        while not parent.exists():
            parent = parent.parent
        if not parent.is_dir():
            raise ValueError("Generated config parent is not a directory: %s" % path)


def main():
    ap = argparse.ArgumentParser(description="Stamp a spec-conformant companion config repo.")
    ap.add_argument("--skill", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--mode", default="B", choices=["A", "B"])
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    try:
        runtime = ConfigRuntime(a.skill)
        out, how = runtime.discover(a.out, initialize=True)
    except (OSError, ValueError, RuntimeError) as exc:
        print("ERROR: %s" % exc)
        return 1
    skill = runtime.skill
    print("Init config for skill '%s' (mode %s) at %s" % (skill, a.mode, out))
    print("Resolved via %s; discovery env var: %s" % (how, env_var(skill)))

    # registry.json, deterministic; no machine-specific content (E4/E5).
    registry = {"schema_version": 1, "skill": skill, "tools": []}
    generated = {
        "registry.json": json.dumps(registry, indent=2, ensure_ascii=False) + "\n",
        ".gitignore": GITIGNORE,
        "tools/.gitkeep": "",
        "secrets/README.md": SECRETS_README,
        "secrets/.gitkeep": "",
    }
    destinations = {os.path.join(out, name): content for name, content in generated.items()}
    try:
        validate_destinations(out, destinations, runtime)
        for path, content in destinations.items():
            write(path, content, a.force)
    except (OSError, ValueError, RuntimeError) as exc:
        print("ERROR: %s" % exc)
        return 1

    print("\nNext:")
    print("  1) For each tool: create tools/<slug>/{claude.json.template,env.template} and")
    print("     secrets/<slug>.env with real values (gitignored).")
    print("  2) export %s=%s   (or use the default path)" % (env_var(skill), out))
    print("  3) python scripts/verify_config.py   # doctor: checks config shape; add a tool-specific exercise")
    return 0


if __name__ == "__main__":
    sys.exit(main())
