"""Validate source-owned configuration applicability without guessing from prose."""
import json
import re
from pathlib import Path

import storage_contract

CONTRACT = "config.contract.json"


def source_file(root, relative):
    storage_contract.relative_path(relative)
    path = storage_contract.no_links(Path(root) / relative)
    if not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError("source reference must be an ordinary unlinked file: " + relative)
    return path


def strings(value, name, *, nonempty=True):
    if (not isinstance(value, list) or (nonempty and not value)
            or any(not isinstance(item, str) or not item.strip() for item in value)
            or len(value) != len(set(value))):
        raise ValueError(name + " must be a list of unique nonempty strings")
    return value


def load(root):
    value = json.loads(source_file(root, CONTRACT).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ValueError("config contract requires schema_version 1")
    if not isinstance(value.get("repository_kind"), str) or value["repository_kind"] not in {"skill", "software", "combined"}:
        raise ValueError("config contract requires explicit repository_kind")
    if not isinstance(value.get("configuration"), str) or value["configuration"] not in {"settings", "runtime-storage-only", "none"}:
        raise ValueError("config contract requires explicit configuration applicability")
    if not isinstance(value.get("rationale"), str) or not value["rationale"].strip():
        raise ValueError("config contract requires reviewed applicability rationale")
    for relative in strings(value.get("documentation"), "documentation"):
        if not source_file(root, relative).read_text(encoding="utf-8").strip():
            raise ValueError("applicability documentation is empty")
    if value["configuration"] != "settings" and "settings" in value:
        raise ValueError("non-settings applicability cannot declare a settings lifecycle")
    return value


def command(root, value, *, initializer=False):
    if not isinstance(value, dict):
        raise ValueError("native lifecycle command requires path and args")
    path = source_file(root, value.get("path"))
    if path.suffix not in {".py", ".ps1"}:
        raise ValueError("native lifecycle command must name an inspected Python or PowerShell entrypoint")
    args = value.get("args")
    if not isinstance(args, list) or any(not isinstance(arg, str) or "\x00" in arg for arg in args):
        raise ValueError("native lifecycle args must be a string array")
    placeholders = [part for arg in args for part in re.findall(r"\{[^{}]*\}", arg)]
    if placeholders != (["{output}"] if initializer else []):
        raise ValueError("initializer requires one {output}; doctor must select through the declared environment")
    return [str(path), *args]
