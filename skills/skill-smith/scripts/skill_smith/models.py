"""Version-one JSON record constructors and independent observation dimensions."""
import hashlib
import json

DIMENSIONS = ("declared", "enabled", "cached", "installed", "resolved", "discovered", "compatible")
STATES = {"yes", "no", "unknown", "not_applicable"}
STAGES = ("external_skill_repos", "skill_roots", "repo_roots", "plugin_registries",
          "private_bindings", "runtime_discovery", "workflow_roots", "plugin_descriptors")


def source_id(kind, *identity):
    payload = json.dumps([kind, *identity], ensure_ascii=True, separators=(",", ":"))
    return kind + ":" + hashlib.sha256(payload.encode()).hexdigest()


def observe(record, dimension, value, reason, timestamp):
    if value not in STATES:
        raise ValueError("invalid observation state")
    record["status"][dimension] = value
    record["evidence"][dimension] = {"reason": reason, "observed_at": timestamp}


def new_record(kind, identity, origin, relative_path, timestamp):
    record = {
        "source_id": source_id(kind, *identity), "kind": kind, "origin": origin,
        "registry_key": None, "relative_path": relative_path, "version": None,
        "source_hash": None, "entrypoints": [], "dependencies": [], "mounts": [], "status": {},
        "evidence": {}, "aliases": [], "candidates": [], "ownership": "unmanaged",
        "install_strategy": "unmanaged", "resolution": "unchecked",
        "path": None, "resolved_path": None, "direct_target": None,
    }
    for dimension in DIMENSIONS:
        observe(record, dimension, "unknown", "not observed", timestamp)
    return record
