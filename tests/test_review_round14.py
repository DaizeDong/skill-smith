"""Source14 author counterexamples built only from deterministic generated inputs."""
import contextlib
import datetime
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(os.environ.get("SS_SOURCE", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT / "tools"))
from make_fixtures import (review14_guard_revision, review14_repository_config,
                           review14_resolver, review14_trim_layout, review14_existing_backup,
                           review14_plugin_identity, review14_visibility, review14_routing_scenarios)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def git(*args):
    result = subprocess.run(["git", *map(str, args)], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=30)
    if result.returncode:
        raise AssertionError("Synthetic Git setup failed: %s" % result.stderr)
    return result.stdout.strip()


class Source14Controls(unittest.TestCase):
    def setUp(self):
        self.area = Path(tempfile.mkdtemp(prefix="a"))
        self.scripts = ROOT / "skills/skill-smith/scripts"

    def trim(self, fixture):
        sys.path.insert(0, str(self.scripts))
        module = load(self.scripts / "trim_descriptions.py", "trim_author14")
        module._storage_path = lambda path, **kwargs: str(path)
        module._storage_module = lambda: types.SimpleNamespace(reject_output_aliases=lambda path: path)
        module.parse_frontmatter = lambda text: fixture["metadata"].get(text, (None, None))
        # The generated-only parser double does not validate YAML; original YAML tests are unchanged.
        def valid_generated(text, name, description):
            if module.parse_frontmatter(text) != (name, description):
                raise ValueError("generated metadata did not round-trip")
        module.validate_replacement = valid_generated
        return module

    def test_unique_original_backups(self):
        for collision in (False, True):
            with self.subTest(collision=collision):
                fixture = review14_trim_layout(self.area / ("collision" if collision else "unique"), collision)
                module = self.trim(fixture)
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(module.do_apply(str(fixture["worklist"]), False,
                                                     str(fixture["backup"])), 0)
                backups = [path.read_text(encoding="utf-8") for path in fixture["backup"].rglob("*")
                           if path.is_file()]
                self.assertCountEqual(backups, list(fixture["originals"].values()))
                for path in fixture["paths"]:
                    self.assertIn("Reviewed synthetic description", path.read_text(encoding="utf-8"))

    def test_existing_backup_run_is_refused_before_sources_change(self):
        fixture = review14_trim_layout(self.area / "existing")
        module = self.trim(fixture)
        fixed = datetime.datetime(2001, 1, 1)
        sentinel, sentinel_value = review14_existing_backup(fixture["backup"])
        with patch.object(module.datetime, "datetime", types.SimpleNamespace(now=lambda: fixed)), \
             patch.object(module.uuid, "uuid4", lambda: types.SimpleNamespace(hex="generated-run")), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises((FileExistsError, ValueError)):
                module.do_apply(str(fixture["worklist"]), False, str(fixture["backup"]))
        self.assertEqual(sentinel.read_text(encoding="utf-8"), sentinel_value)
        for path in fixture["paths"]:
            self.assertEqual(path.read_text(encoding="utf-8"), fixture["originals"][str(path)])

    def consumer(self, label):
        area = self.area / label
        consumer = area / "c"
        admin = area / "a/g"
        admin.parent.mkdir(parents=True)
        git("init", "--initial-branch", "main", consumer)
        git("init", "--initial-branch", "main", "--separate-git-dir", admin, consumer / "guards")
        resolver = consumer / "guards/tools/datadir.py"
        resolver.parent.mkdir()
        resolver.write_bytes(review14_resolver().encode("utf-8"))
        revision = review14_guard_revision(admin, review14_resolver())
        git("-C", consumer / "guards", "add", "--", "tools/datadir.py")
        git("-C", consumer, "update-index", "--add", "--cacheinfo", "160000,%s,guards" % revision)
        review14_plugin_identity(consumer)
        scripts = consumer / "scripts"
        scripts.mkdir()
        runtime_path = scripts / "config_runtime.py"
        shutil.copyfile(ROOT / "skills/skill-smith/assets/config/config_runtime.py", runtime_path)
        return load(runtime_path, "runtime_author14_" + label), consumer, resolver

    def test_index_flags_cannot_hide_changed_resolver_bytes(self):
        for flag in (None, "ordinary-edit", "--assume-unchanged", "--skip-worktree"):
            with self.subTest(flag=flag):
                module, consumer, resolver = self.consumer({None: "n", "ordinary-edit": "e", "--assume-unchanged": "a", "--skip-worktree": "s"}[flag])
                if flag and flag.startswith("--"):
                    git("-C", consumer / "guards", "update-index", flag, "--", "tools/datadir.py")
                if flag:
                    resolver.write_bytes(review14_resolver("changed").encode("utf-8"))
                    with self.assertRaises(module.ConfigError):
                        module.ConfigRuntime()
                else:
                    self.assertEqual(module.ConfigRuntime().resolver.MARKER, "base")

    def test_verified_bytes_are_the_bytes_executed(self):
        module, consumer, resolver = self.consumer("late")
        original = module.importlib.util.module_from_spec
        def replace_after_check(spec):
            value = original(spec)
            if str(getattr(spec, "origin", "")) == str(resolver):
                resolver.write_bytes(review14_resolver("late-change").encode("utf-8"))
            return value
        with patch.object(module.importlib.util, "module_from_spec", replace_after_check):
            self.assertEqual(module.ConfigRuntime().resolver.MARKER, "base")

    def repositories(self):
        private = self.area / "private"
        public = self.area / "public"
        for path, visibility in ((private, "PRIVATE"), (public, "PUBLIC")):
            git("init", "--initial-branch", "main", path)
            review14_repository_config(path, visibility)
        module = load(self.scripts / "fleet_check.py", "fleet_author14")
        module.HERE = str(self.area / "tool/skills/skill-smith/scripts")
        oracle = types.SimpleNamespace(visibility=review14_visibility)
        return module, private, public, oracle

    def test_private_approval_is_bound_to_physical_output_repository(self):
        module, private, public, oracle = self.repositories()
        scenarios = review14_routing_scenarios(private, public)
        for label, destination, environment, allowed in scenarios:
            with self.subTest(scenario=label), patch.dict(os.environ, environment):
                output = destination / "synthetic-status.json"
                if allowed:
                    path, proof = module.resolve_status_path(str(output), "unused", oracle=oracle)
                    self.assertEqual(path, str(output))
                    self.assertIn("PRIVATE", proof)
                else:
                    with self.assertRaises(ValueError):
                        module.resolve_status_path(str(output), "unused", oracle=oracle)
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
