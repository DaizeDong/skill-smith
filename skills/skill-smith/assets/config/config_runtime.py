"""Bind emitted config commands to their consumer and its pinned guard resolver."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess


class ConfigError(RuntimeError):
    """Config discovery cannot safely identify its consumer or destination."""


def env_var(skill):
    return skill.upper().replace("-", "_") + "_CONFIG"


def _git(root, *args):
    try:
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ConfigError("Cannot verify consumer Git state: %s" % exc) from exc
    if result.returncode:
        raise ConfigError("Cannot verify consumer Git state (%s): %s" %
                          (" ".join(args), result.stderr.strip() or "exit %d" % result.returncode))
    return result.stdout.strip()


class ConfigRuntime:
    """A separate resolver instance for one emitted consumer, including linked worktrees."""

    def __init__(self, requested_skill=None):
        self.consumer = Path(__file__).resolve().parent.parent
        actual_root = Path(_git(self.consumer, "rev-parse", "--show-toplevel")).resolve()
        if actual_root != self.consumer:
            raise ConfigError("Config commands must live in the consumer's scripts/ directory.")
        try:
            plugin = json.loads((self.consumer / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ConfigError("Cannot read the consuming plugin identity: %s" % exc) from exc
        self.skill = plugin.get("name") if isinstance(plugin, dict) else None
        if not isinstance(self.skill, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", self.skill):
            raise ConfigError("The consuming plugin.json must declare a kebab-case skill name.")
        if requested_skill and requested_skill != self.skill:
            raise ConfigError("--skill must match the consuming plugin identity: %s" % self.skill)

        kit = self.consumer / "guards"
        resolver = kit / "tools/datadir.py"
        if not (kit / ".git").is_file() or not resolver.is_file():
            raise ConfigError("Pinned guards resolver missing; run git submodule update --init --recursive guards.")
        gitlink = _git(self.consumer, "ls-files", "--stage", "--", "guards").split()
        if len(gitlink) != 4 or gitlink[0] != "160000" or gitlink[2:] != ["0", "guards"]:
            raise ConfigError("The consumer must track guards as a pinned submodule.")
        if Path(_git(kit, "rev-parse", "--show-toplevel")).resolve() != kit:
            raise ConfigError("The guards worktree is not the consumer's pinned kit.")
        if _git(kit, "rev-parse", "--verify", "HEAD") != gitlink[1]:
            raise ConfigError("guards HEAD differs from the consumer gitlink; restore the pinned kit.")
        _git(kit, "ls-files", "--error-unmatch", "--", "tools/datadir.py")
        _git(kit, "diff", "--exit-code", "HEAD", "--", "tools/datadir.py")
        module_name = "_config_datadir_" + hashlib.sha256(str(self.consumer).encode()).hexdigest()
        spec = importlib.util.spec_from_file_location(module_name, resolver)
        if spec is None or spec.loader is None:
            raise ConfigError("Cannot load the consumer's pinned guards resolver.")
        self.resolver = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.resolver)
        for name in ("resolve_companion_root", "assert_outside_own_repo", "_own_repo_root"):
            if not callable(getattr(self.resolver, name, None)):
                raise ConfigError("Pinned guards resolver lacks %s; update the kit deliberately." % name)
        # The pinned helper skips .git files, including linked consumer worktrees. Bind only
        # this private module instance so discovery and containment share the verified consumer.
        self.resolver._own_repo_root = lambda: str(self.consumer)

    def _destination(self, value):
        root = Path(value).expanduser().resolve()
        self.resolver.assert_outside_own_repo(root, self.skill)
        return str(root)

    def discover(self, override=None, initialize=False):
        """Explicit config selections never fall through; defaults use the pinned resolver."""
        if override:
            return self._destination(override), "explicit CLI path"
        for variable in (env_var(self.skill), env_var(self.skill) + "_DIR"):
            value = os.environ.get(variable)
            if value:
                return self._destination(value), "env:%s" % variable
        root = self.resolver.resolve_companion_root(self.skill)
        if root is not None:
            return self._destination(root), "consumer guards/tools/datadir.py"
        if initialize:
            return self._destination("~/.%s-config" % self.skill), "new home config skeleton"
        return None, None
