#!/usr/bin/env python3
"""Inspect companion storage and retire explicitly reviewed, inactive artifacts.

The contract belongs to the source repository. This shared CLI never treats a
private repository, a Git history, or an unknown path as permission to retain or
delete it. Existing domain schemas remain authoritative.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys


CONTRACT = "storage.contract.json"
FIELDS = ("artifact_id", "path_pattern", "purpose", "schema", "producer",
          "consumer_or_final_deliverable", "rebuild_or_restore")
CLASSES = {"core", "rebuildable", "retired"}
SEPARATE = "separate_companion"
COMBINED = "combined_private_repo"


def relative_path(value, *, pattern=False):
    """Accept portable relative paths without Windows aliases or traversal."""
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError("path must be a nonempty relative POSIX path")
    parts = value.split("/")
    if any(p in {"", ".", ".."} or p.endswith((" ", ".")) for p in parts):
        raise ValueError("path contains an absolute, empty or traversal component")
    for part in parts:
        if part.casefold() == ".git" or any(ord(c) < 32 or c in '<>|"' for c in part):
            raise ValueError("repository metadata and invalid path characters are forbidden")
        if re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", part, re.I):
            raise ValueError("path contains a reserved Windows name")
        if not pattern and any(c in part for c in "*?["):
            raise ValueError("retirement requires a concrete path, not a glob")
    if value in {"*", "**", "**/*"}:
        raise ValueError("repository metadata and unrestricted catch-all paths are forbidden")
    return value


def validate_contract(repo):
    path = no_links(Path(repo) / CONTRACT)
    if not path.is_file() or path.lstat().st_nlink != 1:
        raise ValueError("source contract must be an ordinary unlinked file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(value, dict) or type(value.get("schema_version")) is not int
            or value["schema_version"] != 1):
        raise ValueError("storage contract requires schema_version 1")
    if not isinstance(value.get("tool"), str) or not value["tool"].strip():
        raise ValueError("storage contract requires a tool identity")
    layout = value.get("layout", SEPARATE)
    if layout not in (SEPARATE, COMBINED):
        raise ValueError("unsupported storage layout")
    roots = value.get("data_roots")
    if layout == COMBINED:
        if not isinstance(roots, list) or not roots:
            raise ValueError("combined_private_repo requires nonempty data_roots")
        for root in roots:
            relative_path(root)
        folded = [root.casefold() for root in roots]
        if len(set(folded)) != len(folded) or any(
                b.startswith(a + "/") for a in folded for b in folded if a != b):
            raise ValueError("data_roots must not overlap")
    elif roots is not None:
        raise ValueError("data_roots is only supported for explicit combined_private_repo layout")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("storage contract requires an audited nonempty artifact list")
    identifiers = set()
    for row in artifacts:
        if not isinstance(row, dict) or any(not isinstance(row.get(k), str) or not row[k].strip() for k in FIELDS):
            raise ValueError("artifact requires all documented nonempty fields")
        if row["artifact_id"] in identifiers:
            raise ValueError("duplicate artifact_id")
        identifiers.add(row["artifact_id"])
        relative_path(row["path_pattern"], pattern=True)
        if layout == COMBINED and not in_data_scope(value, row["path_pattern"]):
            raise ValueError("artifact path_pattern is outside declared data_roots")
        retention = row.get("retention_rule")
        if (not isinstance(retention, dict) or retention.get("class") not in CLASSES
                or not isinstance(retention.get("rule"), str) or not retention["rule"].strip()):
            raise ValueError("artifact requires an explicit retention class and rule")
        for key in ("max_bytes",):
            if key in row and (type(row[key]) is not int or row[key] <= 0):
                raise ValueError("artifact max_bytes must be a positive integer")
    if "max_bytes" in value and (type(value["max_bytes"]) is not int or value["max_bytes"] <= 0):
        raise ValueError("contract max_bytes must be a positive integer")
    if not isinstance(value.get("protected_paths", []), list):
        raise ValueError("protected_paths must be a list of relative patterns")
    for pattern in value.get("protected_paths", []):
        relative_path(pattern, pattern=True)
    return value


def in_data_scope(contract, relative):
    if contract.get("layout", SEPARATE) != COMBINED:
        return True
    return any(relative == root or relative.startswith(root + "/") for root in contract["data_roots"])


def matches(path, pattern):
    """Segment glob: * stays within a segment; ** matches zero or more segments."""
    def match(parts, pats):
        if not pats:
            return not parts
        if pats[0] == "**":
            return match(parts, pats[1:]) or bool(parts) and match(parts[1:], pats)
        return bool(parts) and fnmatch.fnmatchcase(parts[0], pats[0]) and match(parts[1:], pats[1:])
    return match(path.split("/"), pattern.split("/"))


def load_guard(repo, name):
    # The single shared checker owns one reviewed security dependency. Consumer
    # repositories need neither a copied script nor a second Guards installation.
    package_root = Path(__file__).resolve().parents[3]
    path = package_root / "guards/tools" / (name + ".py")
    spec = importlib.util.spec_from_file_location("storage_contract_" + name, path)
    if spec is None or spec.loader is None:
        raise ValueError("required pinned guards module is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def no_links(path, *, allow_missing=False):
    """Inspect lexical ancestors before resolve can hide a junction or symlink."""
    path = Path(os.path.abspath(path))
    for node in (*reversed(path.parents), path):
        try:
            info = node.lstat()
        except FileNotFoundError:
            if allow_missing:
                return None
            raise
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("symlink/junction boundary refused: " + str(node))
    return path


def prove_companion(repo, companion=None):
    repo = no_links(repo).resolve()
    contract = validate_contract(repo)
    combined = contract.get("layout", SEPARATE) == COMBINED
    if companion is None and combined:
        companion = repo
    if companion is None:
        resolver = load_guard(repo, "datadir")
        resolver._own_repo_root = lambda: str(repo)
        companion = resolver.resolve_companion_root(contract["tool"])
        if companion is None:
            raise ValueError("companion is uninitialized; configure the existing shared resolver")
    root = no_links(companion).resolve()
    if combined:
        if root != repo:
            raise ValueError("combined_private_repo requires the same source and companion root")
    elif root == repo or root.is_relative_to(repo) or repo.is_relative_to(root):
        raise ValueError("companion must be a separate PRIVATE worktree")
    guard = load_guard(repo, "data_boundary")
    proof = guard.prove_private_companion(root)
    if Path(proof.root).resolve() != root:
        raise ValueError("companion must name the exact proven worktree root")
    return root, proof


def inventory(root, selected=None, *, hash_files=False):
    """Enumerate metadata without following links; hashes are limited to planned removals."""
    root = no_links(root).resolve()
    start = root / relative_path(selected) if selected else root
    no_links(start)
    rows, errors = [], []

    def visit(path):
        rel = path.relative_to(root).as_posix()
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            errors.append({"path": rel, "reason": "link_or_junction"})
            return
        if path.name.casefold() == ".git":
            if path.parent != root:
                errors.append({"path": rel, "reason": "nested_repository"})
            return
        if stat.S_ISDIR(info.st_mode):
            rows.append({"path": rel, "type": "directory", "bytes": 0, "mtime_ns": info.st_mtime_ns})
            for entry in sorted(path.iterdir()):
                visit(entry)
        elif stat.S_ISREG(info.st_mode):
            if info.st_nlink != 1:
                errors.append({"path": rel, "reason": "hardlink"})
                return
            row = {"path": rel, "type": "file", "bytes": info.st_size, "mtime_ns": info.st_mtime_ns}
            if hash_files:
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                row["sha256"] = digest.hexdigest()
            rows.append(row)
        else:
            errors.append({"path": rel, "reason": "unsupported_file_type"})

    if selected:
        visit(start)
    else:
        for entry in sorted(root.iterdir()):
            visit(entry)
    return rows, errors


def owners(contract, path):
    return [row for row in contract["artifacts"] if matches(path, row["path_pattern"])]


def check_storage(repo, companion=None):
    contract = validate_contract(repo)
    root, proof = prove_companion(repo, companion)
    layout = contract.get("layout", SEPARATE)
    data_roots = contract.get("data_roots", [])
    rows, errors, missing, excluded = [], [], [], []
    if layout == COMBINED:
        for relative in data_roots:
            if no_links(root / relative, allow_missing=True) is None:
                missing.append(relative)
                continue
            found, failures = inventory(root, relative)
            rows.extend(found)
            errors.extend(failures)
        top_level = {relative.split("/", 1)[0] for relative in data_roots}
        for entry in sorted(root.iterdir()):
            if entry.name.casefold() == ".git" or entry.name in top_level:
                continue
            info = entry.lstat()
            linked = stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)
            excluded.append({"path": entry.name, "type": "link_not_followed" if linked else
                             "directory_not_traversed" if stat.S_ISDIR(info.st_mode) else "file",
                             "bytes": info.st_size if stat.S_ISREG(info.st_mode) and not linked else None})
    else:
        rows, errors = inventory(root)
    totals = {row["artifact_id"]: 0 for row in contract["artifacts"]}
    undeclared, ambiguous = [], []
    for row in rows:
        found = owners(contract, row["path"])
        row["artifact_ids"] = [a["artifact_id"] for a in found]
        if row["type"] == "directory":
            continue  # containers are structural; files and empty leaves are checked below
        if not found:
            undeclared.append(row["path"])
        elif len(found) != 1:
            ambiguous.append(row["path"])
        else:
            totals[found[0]["artifact_id"]] += row["bytes"]
    nonempty = {r["path"].rpartition("/")[0] for r in rows}
    for row in rows:
        if (row["type"] == "directory" and not row["artifact_ids"]
                and row["path"] not in nonempty):
            undeclared.append(row["path"])
    total = sum(row["bytes"] for row in rows)
    over_budget = []
    if total > contract.get("max_bytes", total):
        over_budget.append("companion")
    for row in contract["artifacts"]:
        if totals[row["artifact_id"]] > row.get("max_bytes", total):
            over_budget.append(row["artifact_id"])
    overhead = git_overhead(root)
    return {"schema_version": 1, "mode": "dry_run", "root": str(root), "layout": layout,
            "data_roots": data_roots, "missing_data_roots": missing, "excluded_source": excluded,
            "private_repositories": list(proof.repositories), "bytes": total,
            "artifact_scope_bytes": total, "worktree_bytes_excluding_git": total if layout == SEPARATE else None,
            "git_overhead": overhead,
            "artifact_bytes": totals, "undeclared": undeclared, "ambiguous": ambiguous,
            "boundary_errors": errors, "over_budget": over_budget, "structure": rows,
            "schema_validation": "domain schemas are referenced, not executed by this inventory",
            "ok": not (errors or undeclared or ambiguous or over_budget or overhead["errors"])}


def git_overhead(root):
    """Measure the local admin directory separately; never follow an external gitfile."""
    admin = root / ".git"
    if not admin.exists():
        return {"bytes": 0, "status": "missing", "errors": ["missing_git_metadata"]}
    no_links(admin)
    if admin.is_file():
        return {"bytes": admin.stat().st_size, "status": "external_admin_not_traversed", "errors": []}
    total, errors = 0, []
    for base, dirs, files in os.walk(admin, followlinks=False):
        for name in list(dirs) + files:
            path = Path(base) / name
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                errors.append(path.relative_to(admin).as_posix())
                if name in dirs:
                    dirs.remove(name)
            elif stat.S_ISREG(info.st_mode):
                total += info.st_size
    return {"bytes": total, "status": "measured_local_admin", "errors": errors}


def retirement_rows(contract, root, path):
    if not in_data_scope(contract, path):
        raise ValueError("retirement path is outside declared data_roots")
    rows, errors = inventory(root, path, hash_files=True)
    if errors:
        raise ValueError("retirement contains a link, nested repository or unsupported file")
    nonempty = {r["path"].rpartition("/")[0] for r in rows}
    for row in rows:
        rel = row["path"]
        if (any(matches(rel, p) for p in contract.get("protected_paths", []))
                or Path(rel).name.casefold().endswith((".lock", ".pid", "-wal", "-shm"))):
            raise ValueError("active/recovery marker or protected path refuses retirement: " + rel)
        found = owners(contract, rel)
        # An undeclared container may only contain independently declared removable children.
        container = row["type"] == "directory" and rel in nonempty
        if (not found and not container) or len(found) > 1:
            raise ValueError("unknown or ambiguous artifact refuses retirement: " + rel)
        if any(a["retention_rule"]["class"] == "core" for a in found):
            raise ValueError("core artifact refuses retirement: " + rel)
    return rows


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def create_plan(repo, companion, paths, reason, inactive_evidence):
    if not reason.strip() or not inactive_evidence.strip():
        raise ValueError("retirement needs a reviewed reason and evidence that writers/references are inactive")
    contract = validate_contract(repo)
    root, proof = prove_companion(repo, companion)
    clean = sorted(set(relative_path(p) for p in paths))
    if not clean or any(b.startswith(a + "/") for i, a in enumerate(clean) for b in clean[i + 1:]):
        raise ValueError("select non-overlapping concrete retirement paths")
    items = [{"path": p, "snapshot": retirement_rows(contract, root, p)} for p in clean]
    return {"schema_version": 1, "mode": "review_required", "companion": str(root),
            "repositories": list(proof.repositories), "contract_sha256": canonical_hash(contract),
            "reason": reason, "inactive_evidence": inactive_evidence,
            "activity_verification": "operator assertion; unknown/active writers must not be approved",
            "items": items}


def remove_exact(root, rows):
    """Remove individually checked leaves; never invoke recursive link-following deletion."""
    ordered = sorted(rows, key=lambda row: (row["path"].count("/"), row["path"]), reverse=True)
    if os.name == "nt":
        # Feed data through stdin, never interpolate paths into executable shell text.
        script = r"""
$ErrorActionPreference = 'Stop'
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
$root = [IO.Path]::GetFullPath($request.root).TrimEnd('\')
foreach ($row in $request.rows) {
    $target = [IO.Path]::GetFullPath([IO.Path]::Combine($root, $row.path))
    if (-not $target.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Path escaped companion' }
    $cursor = $target
    while ($cursor) {
        $entry = Get-Item -LiteralPath $cursor -Force -ErrorAction Stop
        if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse boundary changed' }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
    $entry = Get-Item -LiteralPath $target -Force -ErrorAction Stop
    if ($row.type -eq 'directory') {
        if (-not $entry.PSIsContainer -or [IO.Directory]::GetFileSystemEntries($target).Length) { throw 'Directory changed before removal' }
    } else {
        if ($entry.PSIsContainer -or $entry.Length -ne $row.bytes) { throw 'File changed before removal' }
        if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $row.sha256) { throw 'File digest changed before removal' }
    }
    Remove-Item -LiteralPath $target -Force -ErrorAction Stop
}
"""
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                       input=json.dumps({"root": str(root), "rows": ordered}),
                       text=True, check=True, capture_output=True)
        return
    for row in ordered:
        target = no_links(root / relative_path(row["path"]))
        if not target.is_relative_to(root) or target == root:
            raise ValueError("deletion escaped the companion boundary")
        if row["type"] == "directory" and any(target.iterdir()):
            raise ValueError("directory changed during deletion; refusing recursive removal")
        if row["type"] == "directory":
            target.rmdir()
        else:
            if hashlib.sha256(target.read_bytes()).hexdigest() != row["sha256"]:
                raise ValueError("file changed before deletion")
            target.unlink()


def apply_plan(repo, companion, plan_path, approved_sha256):
    raw = Path(plan_path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != approved_sha256:
        raise ValueError("approval does not match the exact reviewed plan bytes")
    plan = json.loads(raw)
    if (plan.get("schema_version") != 1 or plan.get("mode") != "review_required"
            or not isinstance(plan.get("items"), list) or not plan["items"]):
        raise ValueError("invalid retirement plan")
    current = create_plan(repo, companion, [i["path"] for i in plan["items"]],
                          plan.get("reason", ""), plan.get("inactive_evidence", ""))
    if current != plan:
        raise ValueError("contract, PRIVATE identity or artifact snapshot changed; review a fresh plan")
    root = Path(current["companion"])
    for item in current["items"]:
        # Revalidate each concrete tree immediately before the first deletion in that tree.
        fresh = create_plan(repo, companion, [item["path"]], current["reason"], current["inactive_evidence"])
        if fresh != {**current, "items": [item]}:
            raise ValueError("retirement target changed before deletion")
        remove_exact(root, item["snapshot"])
    return {"schema_version": 1, "mode": "applied", "removed": [i["path"] for i in current["items"]],
            "bytes": sum(r["bytes"] for i in current["items"] for r in i["snapshot"])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "check", "plan", "apply"))
    parser.add_argument("--repo", required=True)
    parser.add_argument("--companion")
    parser.add_argument("--json", action="store_true", help="JSON is the stable output format")
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--reason", default="")
    parser.add_argument("--inactive-evidence", default="")
    parser.add_argument("--plan")
    parser.add_argument("--approve-sha256")
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            contract = validate_contract(args.repo)
            result = {"ok": True, "tool": contract["tool"], "artifacts": len(contract["artifacts"])}
        elif args.command == "check":
            result = check_storage(args.repo, args.companion)
        elif args.command == "plan":
            result = create_plan(args.repo, args.companion, args.path, args.reason, args.inactive_evidence)
        else:
            if not args.plan or not args.approve_sha256:
                raise ValueError("apply requires --plan and --approve-sha256")
            result = apply_plan(args.repo, args.companion, args.plan, args.approve_sha256)
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok", True) else 1
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc), "error_type": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
