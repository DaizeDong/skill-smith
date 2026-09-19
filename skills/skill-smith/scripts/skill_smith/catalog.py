"""Source resolution from explicit inputs, with optional bounded native capture.

See docs/catalog.md for the versioned request and result contract. The catalog
preserves evidence and uncertainty; selection and deployment belong to callers.
"""
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from .metadata import parse_frontmatter
from .models import DIMENSIONS, STAGES, STATES, new_record, observe
from .paths import join_relative, normalize, probe

MAX_INPUT_BYTES = 4 * 1024 * 1024
# This installer also provisions the runtime needed by the skill. A filesystem
# scan must never turn it into a generic junction installation instruction.
EXTERNAL_INSTALLERS = {"cc-setup": "external-installer"}


CONSUMER_FEATURES = {"workflow_roots", "plugin_descriptors", "plugin_metadata_paths"}


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if not isinstance(parsed, datetime) or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


class Discovery:
    def __init__(self, request, *, now=None):
        self.request = request
        self.now = timestamp(now if now is not None else datetime.now(timezone.utc)).isoformat()
        self.records = {}
        self.problems = []
        approved = request.get("approved_roots", [])
        self.approved_valid = self.valid_roots(approved)
        self.approved = list(approved) if self.approved_valid else []
        self.coverage = {
            stage: {"status": "unchecked", "observed_at": self.now, "reason": "input not configured"}
            for stage in STAGES
        }

    def problem(self, stage, reason, path=None, record=None):
        issue = {"stage": stage, "reason": reason, "path": str(path) if path is not None else None}
        if record is not None:
            issue["source_id"] = record["source_id"]
        self.problems.append(issue)
        self.coverage[stage].update(status="partial", reason="one or more inputs could not be resolved")

    def configured(self, stage):
        if stage not in self.request or self.request[stage] is None:
            return False
        if not self.approved_valid:
            self.problem(stage, "approved_roots must be a list of nonempty strings")
            return False
        self.coverage[stage].update(status="checked", reason="configured inputs inspected")
        return True

    @staticmethod
    def valid_roots(roots):
        return isinstance(roots, list) and all(isinstance(p, str) and p.strip() for p in roots)

    def collection(self, data, key, stage, required=()):
        items = data.get(key)
        if not isinstance(items, list):
            self.problem(stage, key + " must be a list")
            return []
        valid = []
        for item in items:
            if not isinstance(item, dict) or any(not isinstance(item.get(k), str) or not item[k] for k in required):
                self.problem(stage, "invalid " + key + " entry")
            else:
                valid.append(item)
        return valid

    def text_fields(self, data, fields, stage):
        if any(data.get(key) is not None and not isinstance(data[key], str) for key in fields):
            self.problem(stage, "identity and provenance fields must be strings")
            return False
        return True

    def read_json(self, path, stage):
        if not isinstance(path, (str, Path)):
            self.problem(stage, "input path must be a string")
            return None
        try:
            with open(path, "rb") as stream:
                raw = stream.read(MAX_INPUT_BYTES + 1)
            if len(raw) > MAX_INPUT_BYTES:
                raise ValueError("oversize input")
            data = json.loads(raw.decode("utf-8-sig"))
            if not isinstance(data, dict):
                raise ValueError("expected JSON object")
            return data
        except (OSError, ValueError, TypeError):
            self.problem(stage, "unreadable or invalid JSON object", path)
            return None

    def observe(self, record, dimension, value, reason):
        observe(record, dimension, value, reason, self.now)

    def add(self, record):
        existing = self.records.get(record["source_id"])
        if existing is None:
            self.records[record["source_id"]] = record
            return record
        for alias in record["aliases"]:
            if alias not in existing["aliases"]:
                existing["aliases"].append(alias)
        return existing

    def locate(self, record, path, roots, stage):
        observation = probe(path, roots)
        record.update({key: value for key, value in observation.items() if key != "resolved"})
        self.observe(record, "resolved", observation["resolved"], observation["resolution"])
        if observation["resolved"] != "yes":
            self.problem(stage, observation["resolution"], path, record)
            return False
        return True

    def entry(self, record, path, roots, stage, *, kind="skill", client=None, scope=None,
              installed="unknown", install_name=None, relative_path=None):
        observation = probe(path, roots)
        if observation["resolved"] != "yes":
            self.problem(stage, observation["resolution"], path, record)
            if record["kind"] != "plugin":
                self.observe(record, "resolved", observation["resolved"], observation["resolution"])
                record["resolution"] = observation["resolution"]
            return
        try:
            with open(path, "rb") as stream:
                raw = stream.read(MAX_INPUT_BYTES + 1)
            if len(raw) > MAX_INPUT_BYTES:
                raise ValueError("oversize entrypoint")
            name, description = parse_frontmatter(raw.decode("utf-8-sig"))
        except (OSError, ValueError):
            if record["kind"] != "plugin":
                self.observe(record, "resolved", "unknown", "entrypoint unreadable")
                record["resolution"] = "unreadable"
            self.problem(stage, "entrypoint unreadable", path, record)
            return
        if kind == "skill" and description is None:
            self.problem(stage, "skill metadata missing", path, record)
        declared_name = name
        name = name or (Path(path).parent.name if kind == "skill" else Path(path).stem)
        ep = {
            "source_id": record["source_id"], "kind": kind, "name": name,
            "description": description, "declared_name": declared_name, "path": str(path), "resolved_path": observation["resolved_path"],
            "client": client, "scope": scope, "install_name": install_name or name,
            "relative_path": relative_path,
            "source_hash": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "status": {"installed": installed, "discovered": "unknown", "compatible": "unknown"},
            "evidence": {},
        }
        self.observe(ep, "installed", installed, "filesystem observation")
        if not any((e["path"], e["client"], e["scope"]) == (ep["path"], client, scope)
                   for e in record["entrypoints"]):
            record["entrypoints"].append(ep)
        if record["kind"] == "skill":
            record["name"] = name
            record["source_hash"] = ep["source_hash"]
        if installed == "yes":
            self.observe(record, "installed", "yes", "entrypoint present in client root")

    def external(self):
        stage = "external_skill_repos"
        if not self.configured(stage):
            return
        data = self.read_json(self.request[stage], stage)
        if data is None:
            return
        home = self.request.get("profile_home")
        if not isinstance(home, str) or not home.strip():
            self.problem(stage, "profile_home must be a nonempty string for external sources")
            return
        for key, root_key in (("repos", "skillRepoRoot"), ("vendored", "vendoredRoot")):
            if key not in data:
                continue
            try:
                items = self.collection(data, key, stage)
                if not items:
                    continue
                root = join_relative(home, data[root_key])
            except (KeyError, TypeError, ValueError):
                self.problem(stage, "invalid external source root")
                continue
            self.approved.append(root)
            for item in items:
                if key == "repos":
                    if not self.external_fields(item, ("url", "dir"), ("branch", "commit"), stage):
                        continue
                    skills = self.collection(item, "skills", stage, ("name", "subPath"))
                    pairs = [(s, item) for s in skills]
                else:
                    if not self.external_fields(item, ("name", "subPath", "upstream"),
                                                ("commit", "vendored"), stage):
                        continue
                    pairs = [(item, None)]
                for skill, repo in pairs:
                    try:
                        self.external_skill(skill, repo, root, self.approved, stage)
                    except (KeyError, TypeError, ValueError):
                        self.problem(stage, "invalid external source declaration")
        if "repos" not in data and "vendored" not in data:
            self.problem(stage, "external manifest declares no source collections")

    def external_fields(self, data, required, optional, stage):
        if any(not isinstance(data.get(key), str) or not data[key].strip() for key in required):
            self.problem(stage, "external identity fields must be nonempty strings")
            return False
        return self.text_fields(data, optional, stage)

    def external_skill(self, skill, repo, root, roots, stage):
        name, relative = skill["name"], skill["subPath"]
        upstream = repo["url"] if repo is not None else skill["upstream"]
        relative = join_relative(".", relative).replace("\\", "/")
        origin = ({"type": "checkout", "url": upstream, "dir": repo["dir"], "branch": repo.get("branch")}
                  if repo is not None else
                  {"type": "vendored", "upstream": upstream, "vendored": skill.get("vendored"),
                   "commit": skill.get("commit"), "subPath": skill["subPath"]})
        record = new_record("skill", [upstream, relative], origin, relative, self.now)
        record["aliases"] = [name]
        record["ownership"] = "declared-source"
        record["install_strategy"] = "declared-source"
        record["version"] = repo.get("commit") if repo is not None else skill.get("commit")
        self.observe(record, "declared", "yes", "external source manifest")
        self.observe(record, "cached", "not_applicable", "not a plugin cache")
        path = (join_relative(root, repo["dir"], skill["subPath"]) if repo is not None else
                join_relative(root, name))
        previous = self.records.get(record["source_id"])
        if previous is not None and (
                previous["resolution"] == "ambiguous" or previous["version"] != record["version"]
                or normalize(previous["path"]) != normalize(path)):
            previous["resolution"] = "ambiguous"
            previous["entrypoints"] = []
            self.observe(previous, "resolved", "unknown", "conflicting source declarations")
            self.problem(stage, "conflicting paths or revisions for one source identity", path, previous)
            return
        record = self.add(record)
        if name in EXTERNAL_INSTALLERS:
            record["ownership"] = record["install_strategy"] = EXTERNAL_INSTALLERS[name]
        if self.locate(record, path, roots, stage):
            self.entry(record, Path(path) / "SKILL.md", roots, stage, install_name=name)

    def children(self, path, roots, stage, record=None):
        observation = probe(path, roots)
        if observation["resolved"] != "yes":
            self.problem(stage, observation["resolution"], path, record)
            return []
        try:
            return sorted(Path(path).iterdir(), key=lambda p: p.name)
        except OSError:
            self.problem(stage, "directory unreadable", path, record)
            return []

    def skill_roots(self):
        stage = "skill_roots"
        if not self.configured(stage):
            return
        for descriptor in self.collection(self.request, stage, stage, ("path",)):
            root = str(descriptor["path"])
            maximum = descriptor.get("max_depth", 1)
            if not isinstance(maximum, int) or isinstance(maximum, bool) or not 1 <= maximum <= 16:
                self.problem(stage, "max_depth must be an integer from 1 to 16", root)
                continue
            roots = self.approved + [root] + list(descriptor.get("approved_roots", []))
            if descriptor.get("include_root") is True:
                self.local_skill(Path(root), descriptor, roots, stage, depth=0)
            else:
                for child in self.children(root, roots, stage):
                    self.local_skill(child, descriptor, roots, stage, depth=1)

    def local_skill(self, path, descriptor, roots, stage, depth):
        observation = probe(path, roots)
        if observation["resolved"] == "yes" and not observation.get("is_directory"):
            return
        skill_observation = probe(path / "SKILL.md", roots) if observation["resolved"] == "yes" else None
        if observation["resolved"] == "yes" and depth < descriptor.get("max_depth", 1):
            for child in self.children(path, roots, stage):
                self.local_skill(child, descriptor, roots, stage, depth + 1)
        if skill_observation and skill_observation["resolution"] == "missing":
            return
        matches = [r for r in self.records.values() if r["kind"] == "skill"
                   and r["status"]["declared"] == "yes" and r["resolved_path"]
                   and observation["resolved_path"]
                   and normalize(r["resolved_path"]) == normalize(observation["resolved_path"])
                   and r["status"]["resolved"] == "yes"]
        if len(matches) == 1:
            record = matches[0]
        else:
            relative = path.relative_to(descriptor["path"]).as_posix()
            namespace = descriptor.get("namespace") or normalize(descriptor["path"])
            record = new_record("skill", ["local", namespace, relative],
                                {"type": "local", "namespace": namespace}, relative, self.now)
            record["aliases"] = [path.name]
            record = self.add(record)
        if path.name in EXTERNAL_INSTALLERS:
            record["ownership"] = record["install_strategy"] = EXTERNAL_INSTALLERS[path.name]
        mount = dict(observation, client=descriptor.get("client"), scope=descriptor.get("scope", "user"),
                     install_name=path.name)
        record["mounts"].append(mount)
        located = observation["resolved"] == "yes" if len(matches) == 1 else self.locate(record, path, roots, stage)
        if located:
            self.entry(record, path / "SKILL.md", roots, stage,
                       client=descriptor.get("client"), scope=descriptor.get("scope", "user"),
                       installed="yes", install_name=path.name,
                       relative_path=(path / "SKILL.md").relative_to(descriptor["path"]).as_posix())

    def repo_roots(self):
        stage = "repo_roots"
        if not self.configured(stage):
            return
        for descriptor in self.collection(self.request, stage, stage, ("path",)):
            root = str(descriptor["path"])
            roots = self.approved + [root] + list(descriptor.get("approved_roots", []))
            for path in self.children(root, roots, stage):
                observation = probe(path, roots)
                if observation["resolved"] != "yes":
                    self.problem(stage, observation["resolution"], path)
                    continue
                marker = probe(path / ".git", roots)
                if marker["resolved"] != "yes":
                    if marker["resolved"] == "unknown":
                        self.problem(stage, "git marker unreadable", path)
                    continue
                namespace = descriptor.get("namespace") or normalize(root)
                record = new_record("repository", [namespace, path.name],
                                    {"type": "repository", "namespace": namespace}, path.name, self.now)
                record["name"] = path.name
                record["git_kind"] = "directory" if marker.get("is_directory") else "linked_worktree"
                if self.locate(record, path, roots, stage):
                    self.add(record)

    def plugins(self):
        stage = "plugin_registries"
        registries = self.configured(stage)
        grouped = defaultdict(list)
        for descriptor in self.collection(self.request, stage, stage, ("path",)) if registries else []:
            if not self.text_fields(descriptor, ("client", "scope", "scope_path", "settings_path"), stage):
                continue
            data = self.read_json(descriptor["path"], stage)
            settings = (self.read_json(descriptor["settings_path"], stage)
                        if descriptor.get("settings_path") else None)
            if settings is not None and not isinstance(settings.get("enabledPlugins", {}), dict):
                self.problem(stage, "enabledPlugins must be an object", descriptor.get("settings_path"))
                settings = None
            if data is None:
                data = {"plugins": {}}
            if not isinstance(data.get("plugins"), dict):
                self.problem(stage, "registry plugins must be an object", descriptor["path"])
                continue
            registered = dict(data["plugins"])
            for key in (settings or {}).get("enabledPlugins", {}):
                registered.setdefault(key, [{}])
            for key, installations in sorted(registered.items()):
                if not isinstance(installations, list):
                    installations = [installations]
                if not installations:
                    self.problem(stage, "plugin registry key has no installations", descriptor["path"])
                    installations = [{}]
                for installation in installations:
                    if not isinstance(installation, dict) or "@" not in key:
                        self.problem(stage, "plugin requires full registry key and install record", descriptor["path"])
                        continue
                    if not self.text_fields(installation, ("scope", "projectPath", "installPath", "version", "gitCommitSha"), stage):
                        continue
                    client = descriptor.get("client", "claude")
                    scope = installation.get("scope", descriptor.get("scope", "user"))
                    scope_path = installation.get("projectPath")
                    if scope_path is None and scope == descriptor.get("scope", "user"):
                        scope_path = descriptor.get("scope_path")
                    identity = (key, client, scope, scope_path)
                    grouped[identity].append((installation, descriptor, settings))
        explicit_identities = set()
        if self.configured("plugin_descriptors"):
            for descriptor in self.collection(self.request, "plugin_descriptors", "plugin_descriptors", ("name", "path")):
                name, path = descriptor["name"], descriptor["path"]
                matches = [identity for identity, items in grouped.items()
                           if identity[1:3] == ("claude", "user") and identity[3] is None
                           and (identity[0] == name or identity[0].rsplit("@", 1)[0] == name)
                           and any(i.get("installPath") and normalize(i["installPath"]) == normalize(path)
                                   for i, _, _ in items)]
                if not matches:
                    matches = [identity for identity in grouped
                               if identity[1:3] == ("claude", "user") and identity[3] is None
                               and (identity[0] == name or identity[0].rsplit("@", 1)[0] == name)]
                if len(matches) > 1:
                    self.problem("plugin_descriptors", "ambiguous_plugin_identity", path)
                    continue
                if matches:
                    identity = matches[0]
                    if any(i.get("installPath") and not d.get("explicit_descriptor") for i, d, _ in grouped[identity]):
                        if not any(i.get("installPath") and normalize(i["installPath"]) == normalize(path)
                                   for i, _, _ in grouped[identity]):
                            self.problem("plugin_descriptors", "explicit path conflicts with registry installation", path)
                            continue
                        explicit_identities.add(identity)
                        continue
                    settings = grouped[identity][0][2]
                    grouped[identity] = [(i, d, s) for i, d, s in grouped[identity] if d.get("explicit_descriptor")]
                elif any(identity[0] == name for identity in grouped):
                    self.problem("plugin_descriptors", "non_user_plugin_installation", path)
                    continue
                elif "@" in name:
                    identity, settings = (name, "claude", "user", None), None
                else:
                    self.problem("plugin_descriptors", "ambiguous_plugin_identity", path)
                    continue
                explicit_identities.add(identity)
                grouped[identity].append(({"installPath": path},
                    {"path": path, "approved_roots": [path], "explicit_descriptor": True}, settings))
        for identity, candidates in sorted(grouped.items(), key=lambda item: str(item[0])):
            candidate_stage = ("plugin_descriptors" if all(d.get("explicit_descriptor")
                               for _, d, _ in candidates) else stage)
            self.plugin(identity, candidates, candidate_stage)
            if identity in explicit_identities:
                from .models import source_id
                self.records[source_id("plugin", *identity)]["explicit_selection"] = True

    def plugin(self, identity, candidates, stage):
        key, client, scope, scope_path = identity
        name, marketplace = key.rsplit("@", 1)
        record = new_record("plugin", list(identity),
                            {"type": "plugin", "marketplace": marketplace}, ".", self.now)
        record.update(registry_key=key, name=name, client=client, scope=scope, scope_path=scope_path,
                      ownership="plugin-manager", install_strategy="plugin-manager")
        self.add(record)
        self.observe(record, "declared", "yes", "explicit plugin descriptor" if stage == "plugin_descriptors"
                     else "plugin installation registry")
        enabled = set()
        for _installation, _descriptor, settings in candidates:
            if _descriptor.get("scope", "user") != scope:
                continue
            expected_path = _descriptor.get("scope_path")
            if ((expected_path is None) != (scope_path is None) or
                    expected_path is not None and normalize(expected_path) != normalize(scope_path)):
                continue
            value = (settings or {}).get("enabledPlugins", {}).get(key)
            enabled.add("yes" if value is True else "no" if value is False else "unknown")
        state = next(iter(enabled)) if len(enabled) == 1 else "unknown"
        self.observe(record, "enabled", state,
                     "exact registry key in supplied settings" if state != "unknown" else "enablement not established")
        choices = {(i.get("installPath"), i.get("version"), i.get("gitCommitSha")) for i, _, _ in candidates}
        if len(choices) != 1:
            record["resolution"] = "ambiguous"
            self.problem(stage, "conflicting selected installations for one plugin identity", record=record)
            return
        installation, descriptor, _settings = candidates[0]
        path = installation.get("installPath")
        record["version"] = installation.get("version")
        record["origin"]["commit"] = installation.get("gitCommitSha")
        record["registry_path"] = None if descriptor.get("explicit_descriptor") else str(descriptor["path"])
        if not path:
            record["resolution"] = "missing"
            self.observe(record, "resolved", "no", "registry has no installPath")
            self.problem(stage, "missing installPath", record=record)
            return
        roots = self.approved + list(descriptor.get("approved_roots", [str(Path(descriptor["path"]).parent)]))
        if not self.locate(record, path, roots, stage):
            self.observe(record, "cached", record["status"]["resolved"], record["resolution"])
            return
        self.observe(record, "cached", "yes", "selected installPath exists")
        self.observe(record, "installed", "yes", "selected installation path exists")
        self.plugin_entries(record, roots, stage)
        hashes = sorted((e["kind"], e["relative_path"], e["name"], e["source_hash"]) for e in record["entrypoints"])
        record["source_hash"] = "sha256:" + hashlib.sha256(json.dumps(hashes).encode()).hexdigest()
        self.plugin_bindings(record, roots, stage)

    def markdown_paths(self, path, roots, stage, depth=0, record=None):
        observation = probe(path, roots)
        if observation["resolution"] == "missing":
            if observation["is_link"]:
                self.problem(stage, "missing", path, record)
            return
        if observation["resolved"] != "yes":
            self.problem(stage, observation["resolution"], path, record)
            return
        if observation.get("is_directory"):
            if depth >= 8:
                self.problem(stage, "workflow_depth_exceeded", path, record)
                return
            for child in self.children(path, roots, stage, record):
                yield from self.markdown_paths(child, roots, stage, depth + 1, record)
        elif path.suffix.lower() == ".md":
            yield path

    def plugin_entries(self, record, roots, stage):
        root = Path(record["path"])
        references = {"skills": [root / "skills"], "commands": [root / "commands"],
                      "agents": [root / "agents"]}
        manifest = root / ".claude-plugin/plugin.json"
        observation = probe(manifest, roots)
        if observation["resolution"] != "missing":
            data = self.read_json(manifest, stage) if observation["resolved"] == "yes" else None
            if data is None:
                self.problem(stage, "invalid_or_unreadable_plugin_manifest", manifest, record)
                return
            for kind in references:
                extra = data.get(kind, [])
                extra = [extra] if isinstance(extra, str) else extra
                if not isinstance(extra, list) or any(not isinstance(p, str) for p in extra):
                    self.problem(stage, "invalid_or_unreadable_plugin_manifest", manifest, record)
                    return
                for value in extra:
                    value = value.replace("${CLAUDE_PLUGIN_ROOT}", str(root))
                    path = root / value
                    from .paths import within
                    if not within(path, root) or not within(path.resolve(), root):
                        self.problem(stage, "agent_reference_outside_plugin", manifest, record)
                        continue
                    references[kind].append(path)
        for folder, paths in references.items():
            kind = {"skills": "skill", "commands": "command", "agents": "agent_template"}[folder]
            for path in paths:
                if path not in {root / "skills", root / "commands", root / "agents"} and probe(path, roots)["resolved"] != "yes":
                    self.problem(stage, "declared_plugin_path_unavailable", path, record)
                    continue
                for entry in self.markdown_paths(path, roots, stage, record=record):
                    if kind == "skill" and entry.name != "SKILL.md":
                        continue
                    self.entry(record, entry, roots, stage, kind=kind,
                               client=record["client"], scope=record["scope"], installed="yes",
                               install_name=entry.parent.name if kind == "skill" else entry.stem,
                               relative_path=entry.relative_to(root).as_posix())

    def workflows(self):
        stage = "workflow_roots"
        if not self.configured(stage):
            return
        for descriptor in self.collection(self.request, stage, stage, ("path", "kind")):
            kind = descriptor["kind"]
            if kind not in ("command", "agent_template"):
                self.problem(stage, "invalid workflow kind", descriptor["path"])
                continue
            root = Path(descriptor["path"])
            roots = self.approved + [str(root)] + list(descriptor.get("approved_roots", []))
            if probe(root, roots)["resolved"] != "yes":
                self.problem(stage, "workflow_root_unavailable", root)
                continue
            for path in self.markdown_paths(root, roots, stage):
                relative = path.relative_to(root).as_posix()
                record = new_record(kind, [descriptor.get("namespace", normalize(root)), relative],
                                    {"type": "local", "root": str(root)}, relative, self.now)
                self.add(record)
                if self.locate(record, path, roots, stage):
                    self.entry(record, path, roots, stage, kind=kind, client=descriptor.get("client"),
                               scope=descriptor.get("scope", "user"), installed="yes",
                               install_name=path.stem, relative_path=relative)

    def plugin_bindings(self, plugin, roots, stage):
        path = Path(plugin["path"]) / ".mcp.json"
        observation = probe(path, roots)
        if observation["resolution"] == "missing":
            return
        if observation["resolved"] != "yes":
            self.problem(stage, observation["resolution"], path, plugin)
            return
        data = self.read_json(path, stage)
        if data is None:
            return
        servers = data.get("mcpServers", data)
        if not isinstance(servers, dict):
            self.problem(stage, "mcpServers must be an object", path, plugin)
            return
        for name, configuration in sorted(servers.items()):
            if not isinstance(configuration, dict):
                self.problem(stage, "invalid MCP server declaration", path, plugin)
                continue
            record = new_record("mcp_binding", [plugin["source_id"], name],
                                {"type": "plugin", "plugin_source_id": plugin["source_id"]}, name, self.now)
            record.update(server=name, client=plugin["client"], scope=plugin["scope"],
                          registry_key=plugin["registry_key"], scope_path=plugin["scope_path"])
            self.observe(record, "declared", "yes", "selected plugin MCP declaration")
            self.observe(record, "enabled", plugin["status"]["enabled"], "owning plugin settings")
            self.observe(record, "authenticated", "unknown", "authentication not probed")
            self.add(record)
            plugin["dependencies"].append({"kind": "mcp_binding", "source_id": record["source_id"]})

    def bindings(self):
        stage = "private_bindings"
        if not self.configured(stage):
            return
        data = self.read_json(self.request[stage], stage)
        if data is None:
            return
        for binding in self.collection(data, "bindings", stage, ("id", "kind")):
            if not isinstance(binding, dict) or binding.get("kind") not in ("mcp_binding", "app_connector") or not binding.get("id"):
                self.problem(stage, "binding requires id and typed kind")
                continue
            kind = binding["kind"]
            field = "server" if kind == "mcp_binding" else "connector"
            if not isinstance(binding.get(field), str) or not binding[field].strip():
                self.problem(stage, "binding requires a nonempty string " + field)
                continue
            record = new_record(kind, [binding["id"]], {"type": "private_binding"}, ".", self.now)
            record["binding_id"] = binding["id"]
            record[field] = binding.get(field)
            self.observe(record, "declared", "yes", "supplied binding declaration")
            state = binding.get("authenticated", "unknown")
            self.observe(record, "authenticated", state if isinstance(state, str) and state in STATES else "unknown", "supplied binding observation")
            self.add(record)

    def runtime(self):
        stage = "runtime_discovery"
        if not self.configured(stage):
            return
        data = self.read_json(self.request[stage], stage)
        if data is None:
            return
        policy = self.request.get("runtime_discovery_policy")
        if policy is not None and (not isinstance(policy, dict) or set(policy) != {"max_age_seconds"}
                or type(policy["max_age_seconds"]) is not int or not 0 <= policy["max_age_seconds"] <= 31536000):
            self.problem(stage, "runtime_discovery_policy requires max_age_seconds from 0 to 31536000")
            return
        self.coverage[stage]["max_age_seconds"] = policy["max_age_seconds"] if policy else None
        for item in self.collection(data, "entrypoints", stage, ("source_id", "kind", "name")):
            if not self.text_fields(item, ("client", "scope", "relative_path", "install_name", "observed_at"), stage):
                continue
            record = self.records.get(item.get("source_id"))
            matches = [e for e in record["entrypoints"] if all(e.get(k) == item.get(k)
                       for k in ("kind", "name", "client", "scope")) and all(
                           e.get(k) == item[k] for k in ("relative_path", "install_name") if k in item)] if record else []
            if len(matches) != 1:
                self.problem(stage, "runtime entrypoint has no unique exact source match")
                continue
            captured = item.get("observed_at")
            freshness = "unassessed"
            if policy is not None:
                try:
                    age = (timestamp(self.now) - timestamp(captured)).total_seconds()
                    freshness = "future" if age < 0 else "stale" if age > policy["max_age_seconds"] else "current"
                except (ValueError, TypeError, OverflowError):
                    freshness = "unknown"
                if freshness != "current":
                    self.problem(stage, "runtime evidence is " + freshness)
            for key in ("discovered", "compatible"):
                value = item.get(key, "unknown")
                valid = isinstance(value, str) and value in STATES
                if not valid:
                    self.problem(stage, "invalid runtime observation state")
                observe(matches[0], key, value if valid and freshness in ("current", "unassessed") else "unknown",
                        "supplied runtime observation", captured)
                matches[0]["evidence"][key].update(freshness=freshness, supplied_value=value if valid else "unknown")

    def native(self):
        stage = "native_discovery"
        if stage not in self.request:
            return
        self.coverage[stage] = {"status": "unchecked", "observed_at": None, "reason": "acquisition disabled"}
        from .native_discovery import NativeDiscoveryError, acquire
        try:
            capture = acquire(self.request[stage])
        except NativeDiscoveryError as exc:
            self.problem(stage, exc.code)
            return
        if capture is None:
            return
        captured = capture["observed_at"]
        self.coverage[stage].update(status="checked", observed_at=captured, reason="native skills/list inspected")
        self.native_observation = {"observed_at": captured, "entrypoints": []}
        data = capture["result"].get("data")
        if not isinstance(data, list) or not data:
            self.problem(stage, "native result has no scope data")
            return
        index = defaultdict(list)
        for record in self.records.values():
            for ep in record["entrypoints"]:
                if ep["kind"] == "skill" and ep["client"] == "codex" and ep.get("resolved_path"):
                    index[normalize(ep["resolved_path"])].append(ep)
        observed = defaultdict(list)
        for scope in data:
            if (not isinstance(scope, dict) or not isinstance(scope.get("cwd"), str)
                    or not Path(scope["cwd"]).is_absolute()
                    or normalize(scope["cwd"]) != normalize(Path(self.request[stage]["cwd"]).resolve())):
                self.problem(stage, "native result has unexpected cwd")
                continue
            if not isinstance(scope.get("errors", []), list) or scope.get("errors", []):
                self.problem(stage, "native skills/list reported load errors")
            if not isinstance(scope.get("skills"), list):
                self.problem(stage, "native skills must be a list")
                continue
            for item in scope["skills"]:
                row = {"observed_at": captured, "match": "unmatched", "enabled": None}
                self.native_observation["entrypoints"].append(row)
                if not isinstance(item, dict):
                    self.problem(stage, "invalid native skill entry")
                    continue
                path = item.get("path")
                row["enabled"] = item.get("enabled") if type(item.get("enabled")) is bool else None
                if isinstance(item.get("scope"), str):
                    row["native_scope"] = item["scope"]
                if not isinstance(path, str) or not path or '\x00' in path or not Path(path).is_absolute():
                    self.problem(stage, "native skill requires absolute SKILL.md path")
                    continue
                row["path"] = path
                try:
                    resolved = Path(path).resolve(strict=True)
                    if resolved.name != "SKILL.md" or not resolved.is_file():
                        raise ValueError("not an entrypoint")
                except (OSError, ValueError, RuntimeError):
                    self.problem(stage, "native skill path is unresolved", path)
                    continue
                row["resolved_path"] = str(resolved)
                observed[normalize(resolved)].append(row)
        for path, rows in observed.items():
            matches = index.get(path, [])
            if len(matches) != 1 or len(rows) != 1:
                state = "ambiguous" if len(matches) > 1 or len(rows) > 1 else "unmatched"
                for row in rows:
                    row["match"] = state
                for ep in matches:
                    for dimension in ("enabled", "discovered"):
                        observe(ep, dimension, "unknown", "ambiguous native skills/list observation", captured)
                self.problem(stage, "native entrypoint has no unique exact source match")
                continue
            ep, row = matches[0], rows[0]
            row.update({key: ep.get(key) for key in
                        ("source_id", "kind", "name", "client", "scope", "relative_path", "install_name")})
            row["match"] = "exact"
            enabled = row["enabled"]
            value = "yes" if enabled is True else "no" if enabled is False else "unknown"
            row["discovered"] = value
            if enabled is None:
                self.problem(stage, "native skill enabled flag is unknown")
            for dimension in ("enabled", "discovered"):
                observe(ep, dimension, value, "native skills/list observation", captured)
                ep["evidence"][dimension]["enabled"] = enabled

    def result(self):
        self.external()
        self.skill_roots()
        self.repo_roots()
        self.plugins()
        self.workflows()
        self.bindings()
        self.runtime()
        self.native()
        declarations = [r for r in self.records.values() if r["kind"] == "skill"
                        and r["status"]["declared"] == "yes"]
        for record in self.records.values():
            record["aliases"].sort()
            if record["origin"]["type"] == "local":
                names = set(record["aliases"] + [record.get("name")])
                record["candidates"] = sorted(r["source_id"] for r in declarations
                    if names.intersection(r["aliases"] + [r.get("name")]))
        result = {"schema_version": 1, "observed_at": self.now,
                "status": {dimension: "unknown" for dimension in DIMENSIONS},
                "records": sorted(self.records.values(), key=lambda r: r["source_id"]),
                "coverage": self.coverage, "problems": self.problems}
        if hasattr(self, "native_observation"):
            result["native_discovery"] = self.native_observation
        return result


def discover(request: dict, *, now=None) -> dict:
    """Inspect only configured inputs; absent inputs remain explicitly unchecked."""
    if not isinstance(request, dict):
        raise ValueError("catalog request must be an object")
    return Discovery(request, now=now).result()
