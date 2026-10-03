"""Deterministic synthetic active-library inventories for budget and overlap tests."""
import json
from pathlib import Path


def library_inventory_fixture(root, scenario="distinct"):
    """Build only synthetic skills and return their explicit inventory paths."""
    root = Path(root)
    user = root / "user-skills"
    cache = root / "plugin-cache"
    code = root / "code"
    for directory in (user, cache, code):
        directory.mkdir(parents=True, exist_ok=True)
    manifest = root / "installed_plugins.json"
    active = cache / "active-v2"
    shared = "Extract invoice totals and reconcile supplier payments."
    distinct = "Render geometric sketches with colored polygons."
    paths = {}

    def skill(base, name, description):
        path = base / name / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\nname: %s\ndescription: %s\n---\nSynthetic instructions.\n"
                        % (name, description), encoding="utf-8")
        paths[name] = path
        return path

    plugins = {}
    if scenario != "empty":
        skill(user, "invoice-reader", shared)
    if scenario not in ("empty", "user_duplicate"):
        skill(active / "skills", "polygon-renderer", distinct)
        plugins["shapes@example-market"] = [{"installPath": str(active), "scope": "user"}]
    if scenario == "cross_duplicate":
        skill(active / "skills", "polygon-renderer", shared)
    elif scenario == "user_duplicate":
        skill(user, "payment-reader", shared)
    elif scenario == "plugin_duplicate":
        skill(active / "skills", "shape-copy", distinct)
    elif scenario == "stale_cache":
        skill(cache / "stale-v1" / "skills", "stale-copy", shared)
    elif scenario == "repeated_scope":
        plugins["shapes@example-market"].append({"installPath": str(active), "scope": "project"})
    elif scenario == "mixed_scopes":
        plugins["shapes@example-market"].append({"installPath": str(cache / "missing"), "scope": "project"})
    elif scenario == "conflicting_scopes":
        other = cache / "active-project"
        skill(other / "skills", "polygon-renderer", shared)
        plugins["shapes@example-market"].append({"installPath": str(other), "scope": "project"})
    elif scenario == "missing_user_root":
        user = root / "missing-user-skills"
    elif scenario == "missing_manifest":
        manifest = root / "missing-installed.json"
    elif scenario == "missing_install":
        plugins["shapes@example-market"] = [{"installPath": str(cache / "missing")}]
    elif scenario == "missing_user_skill":
        (user / "incomplete").mkdir()
    elif scenario == "missing_plugin_skill":
        (active / "skills" / "incomplete").mkdir()
    elif scenario == "command_only_plugin":
        active = cache / "commands-only"
        active.mkdir()
        plugins["shapes@example-market"] = [{"installPath": str(active)}]
    elif scenario == "overflow":
        skill(user, "invoice-reader", "invoice " * 80)
        plugins["missing@example-market"] = [{"installPath": str(cache / "missing")}]

    malformed = {
        "json_list": [], "json_null": None, "json_missing_plugins": {},
        "plugins_list": {"plugins": []}, "plugins_null": {"plugins": None},
        "records_empty": {"plugins": {"demo@example-market": []}},
        "record_scalar": {"plugins": {"demo@example-market": [7]}},
        "path_number": {"plugins": {"demo@example-market": [{"installPath": 7}]}},
        "path_relative": {"plugins": {"demo@example-market": [{"installPath": "relative"}]}},
        "path_nul": {"plugins": {"demo@example-market": [{"installPath": "bad\u0000path"}]}},
    }
    if scenario != "missing_manifest":
        manifest.write_text(json.dumps(malformed.get(scenario, {"version": 2, "plugins": plugins})),
                            encoding="utf-8")
    if scenario == "invalid_json":
        manifest.write_text("{invalid", encoding="utf-8")
    if scenario == "duplicate_json_key":
        manifest.write_text('{"plugins": {"demo": []}, "plugins": {}}', encoding="utf-8")
    if scenario == "invalid_manifest_utf8":
        manifest.write_bytes(b"\xff")
    bad_descriptions = {
        "missing_description": "---\nname: invoice-reader\n---\n",
        "empty_description": "---\nname: invoice-reader\ndescription: \n---\n",
        "unterminated_frontmatter": "---\nname: invoice-reader\ndescription: invoices\n",
        "list_description": "---\nname: invoice-reader\ndescription: [invoices, payments]\n---\n",
        "broken_quote": '---\nname: invoice-reader\ndescription: "invoices\n---\n',
        "null_description": "---\nname: invoice-reader\ndescription: null\n---\n",
        "duplicate_description": "---\nname: invoice-reader\ndescription: invoices\ndescription: payments\n---\n",
        "malformed_frontmatter_line": "---\nname: invoice-reader\ndescription: invoices\nnot a mapping\n---\n",
        "numeric_description": "---\nname: invoice-reader\ndescription: 123\n---\n",
    }
    if scenario in bad_descriptions:
        paths["invoice-reader"].write_text(bad_descriptions[scenario], encoding="utf-8")
    if scenario == "invalid_skill_utf8":
        paths["invoice-reader"].write_bytes(b"\xff")
    if scenario == "folded_description":
        paths["invoice-reader"].write_text("---\nname: invoice-reader\ndescription: >-\n  "
                                           + shared + "\n---\n", encoding="utf-8")
    return {"root": root, "user": user, "code": code, "manifest": manifest,
            "active": active, "paths": paths, "shared": shared, "distinct": distinct}
