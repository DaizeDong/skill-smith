"""Generate synthetic catalog inputs in a caller-owned test directory."""
import json
import os
from pathlib import Path


def text_file(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


def write_json(path, value):
    return text_file(path, json.dumps(value))


def skill(path, name="demo", description="Parse synthetic invoices and extract totals."):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    text_file(path / "SKILL.md",
        f"---\nname: {name}\ndescription: {description}\n---\nSynthetic skill.\n",
    )
    return path


def external(root):
    return {
        "profile_home": str(root),
        "external_skill_repos": write_json(root / "sources.json", {
            "skillRepoRoot": "repos",
            "repos": [{"dir": "demo-kit", "url": "https://example.com/acme/demo.git",
                       "branch": "main", "skills": [
                           {"name": "invoice-alias", "subPath": "skills/invoice"}]}],
            "vendoredRoot": "vendor",
            "vendored": [{"name": "local-copy", "upstream": "acme/toolkit",
                          "commit": "a" * 40, "subPath": "upstream/skill",
                          "vendored": "2026-01-01"}],
        }),
    }


def plugins(root):
    active = skill(root / "cache" / "market-a" / "1" / "skills" / "demo")
    other = skill(root / "cache" / "market-b" / "2" / "skills" / "demo")
    skill(root / "cache" / "market-a" / "99" / "skills" / "stale", "stale")
    registry = write_json(root / "installed.json", {"version": 2, "plugins": {
        "demo@market-a": [{"scope": "user", "version": "1", "installPath": str(active.parent.parent)}],
        "demo@market-b": [{"scope": "user", "version": "2", "installPath": str(other.parent.parent)}],
    }})
    settings = write_json(root / "settings.json", {"enabledPlugins": {
        "demo@market-a": False, "demo@market-b": True,
    }})
    return {"plugin_registries": [{"path": registry, "settings_path": settings,
                                    "client": "claude", "scope": "user",
                                    "approved_roots": [str(root / "cache")]}]}


def directory_link(link, target):
    """Create a synthetic junction on Windows or a directory symlink on POSIX."""
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)
    return link
