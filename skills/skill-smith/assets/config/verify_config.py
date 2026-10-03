#!/usr/bin/env python3
"""Check the discovered companion config's generic schema and directory shape.

Uses the emitted consumer identity and its pinned guards resolver, regardless of caller cwd.
Explicit --config-dir, CONFIG and CONFIG_DIR selections take precedence and never fall through.
Exit 0 means template conformance only, 1 means a failed check, 2 means a usage error.
Functional readiness requires the consuming skill's own checks and exercise.

Usage: python scripts/verify_config.py [--skill <consumer-name>] [--config-dir <dir>]
Stdlib only. Never echoes secret values.
"""
import argparse
import json
import os
import re
import sys

from config_runtime import ConfigRuntime, env_var, secrets_ignore_problems

PASS, FAIL = "PASS", "FAIL"


class RegistryFormatError(ValueError):
    """A JSON format error whose message contains no registry values."""


def registry_object(pairs):
    """Reject duplicate keys instead of silently accepting the last value."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise RegistryFormatError("duplicate object key")
        result[key] = value
    return result


def reject_constant(_value):
    raise RegistryFormatError("nonstandard JSON numeric constant")


def check_registry(data, skill, check):
    """Validate the published generic schema; report field paths, never input values."""
    check("registry.json is an object", isinstance(data, dict))
    if not isinstance(data, dict):
        return
    version = data.get("schema_version")
    check("registry.json.schema_version", type(version) is int and version == 1,
          "required integer equal to 1")
    owner = data.get("skill")
    check("registry.json.skill", isinstance(owner, str) and owner == skill,
          "required string matching the consuming plugin identity")
    tools = data.get("tools")
    check("registry.json.tools", isinstance(tools, list), "required array")
    if not isinstance(tools, list):
        return
    for index, tool in enumerate(tools):
        prefix = "registry.json.tools[%d]" % index
        check(prefix, isinstance(tool, dict), "required object")
        if not isinstance(tool, dict):
            continue
        slug = tool.get("slug")
        check(prefix + ".slug", isinstance(slug, str) and
              re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) is not None,
              "required kebab-case string")
        check(prefix + ".installed", isinstance(tool.get("installed"), bool), "required Boolean")
        if "transport" in tool:
            transport = tool["transport"]
            check(prefix + ".transport", isinstance(transport, str) and
                  transport in ("stdio", "http", "sse", "rest", "python-lib"),
                  "expected stdio, http, sse, rest or python-lib")
        if "notes" in tool:
            check(prefix + ".notes", isinstance(tool["notes"], str), "expected string")


def main():
    ap = argparse.ArgumentParser(description="Validate this skill's companion config.")
    ap.add_argument("--skill", default=None)
    ap.add_argument("--config-dir", default=None)
    a = ap.parse_args()

    try:
        runtime = ConfigRuntime(a.skill)
        cfg, how = runtime.discover(a.config_dir)
    except (OSError, ValueError, RuntimeError) as exc:
        print("ERROR: %s" % exc)
        return 1
    skill = runtime.skill
    print("Config doctor for skill '%s'" % skill)
    print("Discovery env var: %s (and %s_DIR)" % (env_var(skill), env_var(skill)))
    if not cfg:
        print("  [%s] config located -> none found." % FAIL)
        print("       Set %s=<dir> or run: python scripts/init_config.py" % env_var(skill))
        return 1
    print("  resolved via %s -> %s" % (how, cfg))
    print("-" * 60)

    results = []

    def check(name, ok, detail=""):
        results.append((name, ok, detail))

    check("config dir exists", os.path.isdir(cfg))

    reg = os.path.join(cfg, "registry.json")
    reg_ok = os.path.isfile(reg)
    check("registry.json present", reg_ok)
    if reg_ok:
        try:
            with open(reg, "r", encoding="utf-8-sig") as f:
                data = json.load(f, object_pairs_hook=registry_object, parse_constant=reject_constant)
        except RegistryFormatError as exc:
            check("registry.json valid JSON", False, str(exc))
        except json.JSONDecodeError as exc:
            check("registry.json valid JSON", False,
                  "invalid JSON at line %d, column %d" % (exc.lineno, exc.colno))
        except (OSError, ValueError, RecursionError) as exc:
            check("registry.json readable UTF-8 JSON", False, type(exc).__name__)
        else:
            check("registry.json valid JSON", True)
            check_registry(data, skill, check)

    check("tools/ dir present", os.path.isdir(os.path.join(cfg, "tools")))

    sec = os.path.join(cfg, "secrets")
    check("secrets/ dir present", os.path.isdir(sec))

    gi = os.path.join(cfg, ".gitignore")
    gi_ok = os.path.isfile(gi)
    check(".gitignore present", gi_ok)
    if gi_ok:
        try:
            with open(gi, "r", encoding="utf-8") as stream:
                problems = secrets_ignore_problems(stream.read())
        except (OSError, UnicodeError):
            problems = ["root .gitignore is unreadable"]
        check("root .gitignore excludes representative secret paths", not problems, "; ".join(problems))

    # report
    n_fail = sum(1 for _, ok, _ in results if not ok)
    for nm, ok, detail in results:
        line = "  [%s] %s" % (PASS if ok else FAIL, nm)
        if detail and not ok:
            line += "  -> %s" % detail
        print(line)
    print("-" * 60)
    if n_fail:
        print("NOT READY: %d check(s) failed. Fix the above (or re-run init_config.py)." % n_fail)
        return 1
    print("TEMPLATE CONFORMS: config at %s passes generic shape checks." % cfg)
    print("Configured and functional readiness require tool-specific checks and an exercise.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
