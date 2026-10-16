#!/usr/bin/env python3
"""Inspect companion storage and retire explicitly reviewed, inactive artifacts.

The contract belongs to the source repository. This shared CLI never treats a
private repository, a Git history, or an unknown path as permission to retain or
delete it. Existing domain schemas remain authoritative.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

MAX_NATIVE_ROWS = 10000
MAX_NATIVE_REQUEST_BYTES = 16 * 1024 * 1024
MAX_PATHS_FILE_BYTES = 1024 * 1024


def _runtime():
    try:
        from fleet_guards import runtime
    except ImportError as exc:
        raise ImportError(
            'fleet_guards is not installed; run: pip install -e "$(git config --get fleet.guards)"') from exc
    return runtime


# Path ownership has one source of truth in fleet-guards.
sc = _runtime().storage_contract()


def resolve_companion(repo, companion=None):
    """The companion root, separate from the source unless the layout is combined.

    Its PRIVATE publication is enforced by commit-time hooks, not here.
    """
    repo = sc.no_links(repo).resolve()
    contract = sc.validate_contract(repo)
    combined = contract.get("layout", sc.SEPARATE) == sc.COMBINED
    if companion is None and combined:
        companion = repo
    if companion is None:
        companion = _runtime().companion_resolver(source_root=repo).resolve_companion_root(contract["tool"])
        if companion is None:
            raise ValueError("companion is uninitialized; configure the existing shared resolver")
    root = sc.no_links(companion).resolve()
    if combined:
        if root != repo:
            raise ValueError("combined_private_repo requires the same source and companion root")
    elif root == repo or root.is_relative_to(repo) or repo.is_relative_to(root):
        raise ValueError("companion must be a separate worktree")
    return root


def inventory(root, selected=None, *, hash_files=False):
    """Enumerate metadata without following links; hashes are limited to planned removals."""
    root = sc.no_links(root).resolve()
    start = root / sc.relative_path(selected) if selected else root
    sc.no_links(start)
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


def check_storage(repo, companion=None):
    contract = sc.validate_contract(repo)
    root = resolve_companion(repo, companion)
    layout = contract.get("layout", sc.SEPARATE)
    data_roots = contract.get("data_roots", [])
    rows, errors, missing, excluded = [], [], [], []
    if layout == sc.COMBINED:
        for relative in data_roots:
            if sc.no_links(root / relative, allow_missing=True) is None:
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
        found = sc.owners(contract, row["path"])
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
            "bytes": total,
            "artifact_scope_bytes": total, "worktree_bytes_excluding_git": total if layout == sc.SEPARATE else None,
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
    sc.no_links(admin)
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
    if not sc.in_data_scope(contract, path):
        raise ValueError("retirement path is outside declared data_roots")
    for parent in (root / path).parents:
        if parent == root:
            break
        if (parent / ".git").exists():
            raise ValueError("retirement path belongs to a nested repository")
    rows, errors = inventory(root, path, hash_files=True)
    if errors:
        raise ValueError("retirement contains a link, nested repository or unsupported file")
    nonempty = {r["path"].rpartition("/")[0] for r in rows}
    for row in rows:
        rel = row["path"]
        if (any(sc.matches(rel, p) for p in contract.get("protected_paths", []))
                or Path(rel).name.casefold().endswith((".lock", ".pid", "-wal", "-shm"))):
            raise ValueError("active/recovery marker or protected path refuses retirement: " + rel)
        found = sc.owners(contract, rel)
        # An undeclared container may only contain independently declared removable children.
        container = row["type"] == "directory" and rel in nonempty
        if (not found and not container) or len(found) > 1:
            raise ValueError("unknown or ambiguous artifact refuses retirement: " + rel)
        if any(a["retention_rule"]["class"] == "core" for a in found):
            raise ValueError("core artifact refuses retirement: " + rel)
    return rows


def read_paths_file(path):
    """Read one bounded selection; the planner still validates every concrete path."""
    path = sc.no_links(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("paths-file must be an ordinary UTF-8 JSON file")
    if info.st_size > MAX_PATHS_FILE_BYTES:
        raise ValueError("paths-file exceeds 1 MiB; select a smaller batch")
    with path.open("rb") as stream:
        raw = stream.read(MAX_PATHS_FILE_BYTES + 1)
    if len(raw) > MAX_PATHS_FILE_BYTES:
        raise ValueError("paths-file exceeds 1 MiB; select a smaller batch")
    paths = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(paths, list) or not 1 <= len(paths) <= MAX_NATIVE_ROWS:
        raise ValueError("paths-file requires a JSON array of 1..10000 concrete paths")
    return paths


def _native_request(root, rows, *, control_files=()):
    """Use the same bounded request encoding during planning and native apply."""
    if not rows or len(rows) > MAX_NATIVE_ROWS:
        raise ValueError("native retirement requires 1..10000 rows; review smaller concrete plans")
    request = json.dumps({"root": str(root), "rows": rows, "controls": list(control_files)})
    if len(request.encode("utf-8")) > MAX_NATIVE_REQUEST_BYTES:
        raise ValueError("native retirement request exceeds 16 MiB; review smaller concrete plans")
    return request


def create_plan(repo, companion, paths, reason, inactive_evidence):
    if not reason.strip() or not inactive_evidence.strip():
        raise ValueError("retirement needs a reviewed reason and evidence that writers/references are inactive")
    contract = sc.validate_contract(repo)
    root = resolve_companion(repo, companion)
    clean = sorted(sc.relative_path(p) for p in paths)
    if any(character in path for path in clean for character in "[]"):
        raise ValueError("retirement requires concrete paths without glob patterns")
    normalized = [p.casefold() if os.name == "nt" else p for p in clean]
    selected = set(normalized)
    if (not clean or len(selected) != len(clean) or any(
            "/".join(parts[:i]) in selected
            for path in normalized for parts in [path.split("/")] for i in range(1, len(parts)))):
        raise ValueError("select non-overlapping concrete retirement paths")
    items = [{"path": p, "snapshot": retirement_rows(contract, root, p)} for p in clean]
    if os.name == "nt":
        rows = [row for item in items for row in item["snapshot"]]
        controls = _control_snapshots(_control_files(repo))
        _native_request(root, rows, control_files=controls)
    return {"schema_version": 1, "mode": "review_required", "companion": str(root),
            "contract_sha256": sc.canonical_hash(contract),
            "reason": reason, "inactive_evidence": inactive_evidence,
            "activity_verification": "operator assertion; unknown/active writers must not be approved",
            "items": items}


class RetirementApplyError(ValueError):
    """An unsuccessful apply, including the exact acknowledged partial removals."""

    def __init__(self, result):
        self.result = result
        super().__init__(result["error"])


def _control_files(repo):
    """The source contract stays frozen while the native executor removes files."""
    return [Path(repo) / sc.CONTRACT]


def _control_snapshots(paths):
    records = []
    for path in paths:
        path = Path(os.path.abspath(path))
        exists = sc.no_links(path, allow_missing=True) is not None
        if exists and path.is_dir():
            # The root .git directory is checked as a boundary, not read as a file.
            records.append({"path": str(path), "directory": True})
        elif exists:
            if not path.is_file() or path.stat().st_nlink != 1:
                raise ValueError("configuration control must be an ordinary unlinked file")
            records.append({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        else:
            records.append({"path": str(path), "missing": True})
    return records


def remove_exact(root, rows, *, control_files=()):
    """Remove individually checked leaves; never invoke recursive deletion.

    Existing control files and parent directories stay locked during the batch.
    Absent controls are checked rather than locked. The approved inactive-writer
    assertion still applies: Remove-Item deletes by path after closing the checked
    payload handle, so it is not an atomic handle-bound deletion primitive.
    """
    ordered = sorted(rows, key=lambda row: (row["path"].count("/"), row["path"]), reverse=True)
    if os.name == "nt":
        request = _native_request(root, ordered, control_files=control_files)
        # Feed data through stdin, never interpolate paths into executable shell text.
        script = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
$root = [IO.Path]::GetFullPath($request.root).TrimEnd('\')
Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using Microsoft.Win32.SafeHandles;
public static class RetirementNative {
    [StructLayout(LayoutKind.Sequential)] public struct Info {
        public uint Attributes, CreationLow, CreationHigh, AccessLow, AccessHigh,
            WriteLow, WriteHigh, Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
    }
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetFileInformationByHandle(SafeFileHandle file, out Info info);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern SafeFileHandle CreateFile(
        string name, uint access, uint share, IntPtr security, uint mode, uint flags, IntPtr template);
    static Dictionary<string, SafeFileHandle> held = new Dictionary<string, SafeFileHandle>(StringComparer.OrdinalIgnoreCase);
    public static Info Information(SafeFileHandle handle) {
        Info info;
        if (!GetFileInformationByHandle(handle, out info)) throw new IOException("Cannot read native file identity");
        if ((info.Attributes & 0x400) != 0) throw new IOException("Reparse boundary changed");
        return info;
    }
    public static bool Exists(string path) {
        try { File.GetAttributes(path); return true; }
        catch (FileNotFoundException) { return false; }
        catch (DirectoryNotFoundException) { return false; }
    }
    public static void Parents(string path) { Parents(path, false); }
    public static void Parents(string path, bool allowMissing) {
        string cursor = Path.GetDirectoryName(path);
        while (!String.IsNullOrEmpty(cursor)) {
            FileAttributes attributes;
            try { attributes = File.GetAttributes(cursor); }
            catch (FileNotFoundException) { if (!allowMissing) throw; cursor = Path.GetDirectoryName(cursor); continue; }
            catch (DirectoryNotFoundException) { if (!allowMissing) throw; cursor = Path.GetDirectoryName(cursor); continue; }
            if ((attributes & FileAttributes.ReparsePoint) != 0 || (attributes & FileAttributes.Directory) == 0)
                throw new IOException("Parent link or type changed");
            if (!held.ContainsKey(cursor)) {
                var handle = CreateFile(cursor, 0x80, 3, IntPtr.Zero, 3, 0x02200000, IntPtr.Zero);
                if (handle.IsInvalid) { handle.Dispose(); throw new IOException("Cannot freeze parent directory"); }
                try { Information(handle); held.Add(cursor, handle); } catch { handle.Dispose(); throw; }
            }
            cursor = Path.GetDirectoryName(cursor);
        }
    }
    public static string Target(string root, string relative) {
        if (String.IsNullOrEmpty(relative) || relative.Contains("\\") || relative.Contains(":"))
            throw new IOException("Invalid relative retirement path");
        foreach (string part in relative.Split('/')) {
            string lower = part.ToLowerInvariant();
            if (part == "" || part == "." || part == ".." || lower == ".git" ||
                lower.EndsWith(".lock") || lower.EndsWith(".pid") || lower.EndsWith("-wal") || lower.EndsWith("-shm"))
                throw new IOException("Active marker or invalid retirement path");
        }
        string target = Path.GetFullPath(Path.Combine(root, relative));
        if (!target.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
            throw new IOException("Path escaped companion");
        Parents(target);
        string cursor = Path.GetDirectoryName(target);
        while (!String.Equals(cursor, root, StringComparison.OrdinalIgnoreCase)) {
            if (Exists(Path.Combine(cursor, ".git"))) throw new IOException("Nested repository appeared before removal");
            cursor = Path.GetDirectoryName(cursor);
        }
        if ((File.GetAttributes(target) & FileAttributes.ReparsePoint) != 0) throw new IOException("Reparse target changed");
        return target;
    }
    public static string Digest(FileStream stream) {
        stream.Position = 0;
        using (var hash = SHA256.Create()) return BitConverter.ToString(hash.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
    }
    public static FileStream Freeze(string path, string expected) {
        Parents(path);
        FileStream stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        try {
            var info = Information(stream.SafeFileHandle);
            if (info.Links != 1 || Digest(stream) != expected) throw new IOException("Contract changed");
            return stream;
        } catch { stream.Dispose(); throw; }
    }
    public static void FileMatches(string path, long size, long modified, string hash) {
        using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read)) {
            var info = Information(stream.SafeFileHandle);
            long time = checked((long)(((ulong)info.WriteHigh << 32) | info.WriteLow) - 116444736000000000L) * 100;
            if (info.Links != 1) throw new IOException("Hardlink appeared before removal");
            if ((info.Attributes & 0x10) != 0 || stream.Length != size || time != modified)
                throw new IOException("File type, bytes or mtime changed before removal");
            if (Digest(stream) != hash) throw new IOException("File digest changed before removal");
            if (Information(stream.SafeFileHandle).Links != 1) throw new IOException("Hardlink changed while hashing");
        }
    }
    public static void CloseParents() { foreach (var handle in held.Values) handle.Dispose(); held.Clear(); }
    public static void ReleaseDirectory(string path) {
        SafeFileHandle handle;
        if (held.TryGetValue(path, out handle)) { held.Remove(path); handle.Dispose(); }
    }
}
'@
$heldFiles = [Collections.Generic.List[IO.FileStream]]::new()
$index = 0
try {
    foreach ($control in $request.controls) {
        [RetirementNative]::Parents($control.path, [bool]$control.missing)
        if ($control.missing) {
            if ([RetirementNative]::Exists($control.path)) { throw 'Contract control appeared after planning' }
        } elseif ($control.directory) {
            $attributes = [IO.File]::GetAttributes($control.path)
            if (($attributes -band [IO.FileAttributes]::ReparsePoint) -or -not ($attributes -band [IO.FileAttributes]::Directory)) { throw 'Configuration directory boundary changed' }
        } else {
            $heldFiles.Add([RetirementNative]::Freeze($control.path, $control.sha256))
        }
    }
    foreach ($row in $request.rows) {
        foreach ($control in $request.controls) {
            if ($control.missing -and [RetirementNative]::Exists($control.path)) { throw 'Contract control appeared during removal' }
        }
        $target = [RetirementNative]::Target($root, $row.path)
        if ($row.type -eq 'directory') {
            if (-not [IO.Directory]::Exists($target) -or [IO.Directory]::GetFileSystemEntries($target).Length) { throw 'Directory changed before removal' }
            [RetirementNative]::ReleaseDirectory($target)
        } elseif ($row.type -eq 'file') {
            [RetirementNative]::FileMatches($target, [long]$row.bytes, [long]$row.mtime_ns, $row.sha256)
        } else { throw 'Unsupported retirement type' }
        Remove-Item -LiteralPath $target -Force -ErrorAction Stop
        [Console]::Out.WriteLine('{"removed":' + $index + '}')
        $index++
    }
} catch {
    [Console]::Out.WriteLine((@{failed_index=$index; error=$_.Exception.Message} | ConvertTo-Json -Compress))
    exit 1
} finally {
    foreach ($stream in $heldFiles) { $stream.Dispose() }
    [RetirementNative]::CloseParents()
}
"""
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                input=request,
                                text=True, encoding="utf-8", errors="replace", capture_output=True)
        removed, failure = [], None
        for line in result.stdout.splitlines():
            try:
                receipt = json.loads(line)
                if not isinstance(receipt, dict) or failure is not None:
                    raise ValueError("unexpected retirement acknowledgement")
                if (set(receipt) == {"removed"} and type(receipt["removed"]) is int
                        and receipt["removed"] == len(removed) < len(ordered)):
                    removed.append(ordered[len(removed)]["path"])
                elif (set(receipt) == {"failed_index", "error"}
                      and type(receipt["failed_index"]) is int
                      and receipt["failed_index"] == len(removed) <= len(ordered)
                      and isinstance(receipt["error"], str)):
                    failure = receipt
                else:
                    raise ValueError("unexpected retirement acknowledgement")
            except (ValueError, KeyError, IndexError) as exc:
                failure = {"failed_index": len(removed), "error": str(exc)}
                break
        if result.returncode or failure or len(removed) != len(ordered):
            reason = (failure or {}).get("error") or result.stderr.strip()[-1200:] or "native retirement stopped without a complete receipt"
            index = min((failure or {}).get("failed_index", len(removed)), len(ordered) - 1)
            # A killed child can stop between removal and acknowledgement. Keep
            # observed missing paths distinct from confirmed child operations.
            missing, unknown = [], []
            acknowledged = set(removed)
            for row in ordered:
                if row["path"] in acknowledged:
                    continue
                try:
                    if sc.no_links(root / row["path"], allow_missing=True) is None:
                        missing.append(row["path"])
                except (OSError, ValueError):
                    unknown.append(row["path"])
            raise RetirementApplyError({"ok": False, "mode": "partial", "removed": removed,
                                        "failed_path": ordered[index]["path"], "error": reason,
                                        "unacknowledged_missing": missing, "boundary_unknown": unknown,
                                        "native_exit_code": result.returncode})
        return removed
    for row in ordered:
        target = sc.no_links(root / sc.relative_path(row["path"]))
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
    return [row["path"] for row in ordered]


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
        raise ValueError("contract or artifact snapshot changed; review a fresh plan")
    root = Path(current["companion"])
    if os.name == "nt":
        rows = [row for item in current["items"] for row in item["snapshot"]]
        # create_plan just revalidated every snapshot; the native executor freezes the
        # contract bytes and checks each leaf again as it removes it.
        try:
            remove_exact(root, rows, control_files=_control_snapshots(_control_files(repo)))
        except RetirementApplyError as exc:
            failure = dict(exc.result)
        except Exception as exc:
            failure = {"ok": False, "mode": "partial", "removed": [],
                       "failed_path": rows[0]["path"], "error": str(exc)}
        else:
            return {"schema_version": 1, "mode": "applied", "removed": [i["path"] for i in current["items"]],
                    "bytes": sum(r["bytes"] for r in rows)}
        failure["removed_count"] = len(failure["removed"])
        raise RetirementApplyError(failure)
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
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--path", action="append", default=[], help="Concrete companion-relative path; plan only")
    selection.add_argument("--paths-file", help="UTF-8 JSON array, at most 1 MiB and 10000 paths; plan only")
    parser.add_argument("--reason", default="")
    parser.add_argument("--inactive-evidence", default="")
    parser.add_argument("--plan")
    parser.add_argument("--approve-sha256")
    args = parser.parse_args(argv)
    if args.command != "plan" and (args.path or args.paths_file is not None):
        parser.error("--path and --paths-file are only valid for plan")
    try:
        if args.command == "validate":
            contract = sc.validate_contract(args.repo)
            result = {"ok": True, "tool": contract["tool"], "artifacts": len(contract["artifacts"])}
        elif args.command == "check":
            result = check_storage(args.repo, args.companion)
        elif args.command == "plan":
            paths = read_paths_file(args.paths_file) if args.paths_file is not None else args.path
            result = create_plan(args.repo, args.companion, paths, args.reason, args.inactive_evidence)
        else:
            if not args.plan or not args.approve_sha256:
                raise ValueError("apply requires --plan and --approve-sha256")
            result = apply_plan(args.repo, args.companion, args.plan, args.approve_sha256)
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok", True) else 1
    except RetirementApplyError as exc:
        print(json.dumps(exc.result, indent=2))
        return 1
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc), "error_type": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
