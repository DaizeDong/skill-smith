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
import stat
import sys
import tempfile

from config_runtime import ConfigRuntime, env_var

GITIGNORE = """\
# Default credential exclusions; selected PRIVATE backup files may be tracked explicitly.
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
# secrets/ and private backups

Default ignore rules prevent accidental staging (see ../.gitignore). Keep real credentials out of
the public tool repository. Before storing them here, verify that this separate companion and
every effective push destination are PRIVATE.

Choose a separate backup or deliberately include selected credentials in this PRIVATE versioned
companion. Retain the default ignore rules for unselected files and document the chosen backup
and restore procedure here. Ignore rules do not prevent explicit tracking. The generic doctor
checks those rules, not tracked contents or repository visibility. Committed credentials remain
in history; rotate the credential itself when required. Never echo values in logs or reports.

Per tool, create `secrets/<slug>.env` with the KEY=VALUE pairs its `tools/<slug>/env.template` lists.
Files MUST be UTF-8 without BOM.
"""


def checked_destination(path):
    """Reject linked files and redirected parents without following their aliases."""
    path = Path(os.path.abspath(path))
    for node in (*reversed(path.parents), path):
        try:
            info = node.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 1024:
            raise ValueError("Generated config destination contains a link or reparse alias: %s" % node)
        if node == path:
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("Generated config destination is not a file: %s" % node)
            if info.st_nlink != 1:
                raise ValueError("Generated config destination contains a hardlink alias: %s" % node)
        elif not stat.S_ISDIR(info.st_mode):
            raise ValueError("Generated config parent is not a directory: %s" % node)
    return path


def write(path, content, force):
    path = checked_destination(path)
    if path.exists() and not force:
        print("  SKIP (exists): %s" % path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    checked_destination(path)
    temporary, identity = None, None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         prefix=".init-config-", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            info = os.fstat(stream.fileno())
            identity = info.st_dev, info.st_ino
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        checked_destination(temporary)
        current = temporary.stat()
        if (current.st_dev, current.st_ino) != identity:
            raise ValueError("Generated config temporary changed ownership")
        checked_destination(path)
        if path.exists() and not force:
            print("  SKIP (exists): %s" % path)
            return
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            checked_destination(temporary)
            current = temporary.stat()
            if (current.st_dev, current.st_ino) != identity:
                raise ValueError("Refusing to remove another writer's config temporary")
            temporary.unlink()
    print("  wrote: %s" % path)


def validate_destinations(root, paths, runtime):
    """Check every physical destination and parent before creating or replacing files."""
    root = Path(root).resolve()
    for path in paths:
        target = checked_destination(path)
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
    print("     secrets/<slug>.env with real values (ignored by default; see secrets/README.md).")
    print("  2) export %s=%s   (or use the default path)" % (env_var(skill), out))
    print("  3) python scripts/verify_config.py   # doctor: checks config shape; add a tool-specific exercise")
    return 0


if __name__ == "__main__":
    sys.exit(main())
