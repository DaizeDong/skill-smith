"""Legacy launch defaults and views over a single catalog snapshot."""
import json


def library_request(skills_dir, code_root=None, installed_plugins=None, settings_path=None, max_depth=1):
    request = {"skill_roots": [{"path": str(skills_dir), "namespace": "user-skills",
                               "client": "claude", "scope": "user", "max_depth": max_depth}]}
    if code_root:
        request["approved_roots"] = [str(code_root)]
    if installed_plugins:
        registry = {"path": str(installed_plugins), "client": "claude", "scope": "user"}
        if settings_path:
            registry["settings_path"] = str(settings_path)
        request["plugin_registries"] = [registry]
    return request


def load_snapshot(path):
    with open(path, encoding="utf-8-sig") as stream:
        snapshot = json.load(stream)
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1:
        raise ValueError("unsupported catalog schema")
    if not isinstance(snapshot.get("records"), list) or not isinstance(snapshot.get("coverage"), dict):
        raise ValueError("invalid catalog snapshot")
    return snapshot


def skill_entries(snapshot):
    """Yield installed metadata; disabled or unresolved records cannot add cost."""
    for record in snapshot["records"]:
        if record["status"]["resolved"] != "yes" or record["status"]["enabled"] == "no":
            continue
        for entry in record["entrypoints"]:
            if entry["kind"] == "skill" and entry["status"]["installed"] == "yes":
                yield record, entry


def problems(snapshot, stages=("skill_roots", "plugin_registries")):
    records = {r["source_id"]: r for r in snapshot["records"]}
    messages = []
    for issue in snapshot["problems"]:
        if issue["stage"] not in stages:
            continue
        record = records.get(issue.get("source_id"), {})
        label = record.get("registry_key") or record.get("name") or issue.get("path") or issue["stage"]
        scope = " [%s/%s]" % (record["client"], record["scope"]) if record.get("registry_key") else ""
        messages.append("%s%s: %s" % (label, scope, issue["reason"]))
    return messages
