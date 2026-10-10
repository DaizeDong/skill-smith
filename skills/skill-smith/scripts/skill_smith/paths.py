"""Bounded filesystem observations, including Windows reparse and UNC paths.

These checks describe the paths at discovery time. They are not a write-time
authorization or protection against a concurrent filesystem replacement.
"""
import ntpath
import os
from pathlib import Path, PureWindowsPath
import stat


def normalize(path):
    value = os.fspath(path)
    for prefix in ("\\\\?\\", "\\??\\"):
        if value.startswith(prefix):
            value = value[len(prefix):]
            if value.upper().startswith("UNC\\"):
                value = "\\\\" + value[4:]
            break
    windows = bool(PureWindowsPath(value).drive) or value.startswith("\\\\")
    module = ntpath if windows else os.path
    return module.normcase(module.abspath(value))


def within(path, root):
    left, right = normalize(path), normalize(root)
    module = ntpath if PureWindowsPath(left).drive else os.path
    try:
        return module.commonpath([left, right]) == right
    except ValueError:
        return False


def join_relative(root, *parts):
    for part in parts:
        if not isinstance(part, str) or not part:
            raise ValueError("source path components must be nonempty strings")
        if PureWindowsPath(part).drive or part.startswith(("/", "\\")):
            raise ValueError("source path component must be relative")
        if ".." in part.replace("\\", "/").split("/"):
            raise ValueError("source path component escapes its root")
    return str(Path(root).joinpath(*(p.replace("\\", "/") for p in parts)))


def _long_path_spelling(path):
    """Expand Windows 8.3 names without resolving junction or symlink targets."""
    value = os.fspath(path)
    if os.name != "nt":
        return value
    import ctypes

    query = ctypes.WinDLL("kernel32", use_last_error=True).GetLongPathNameW
    query.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    query.restype = ctypes.c_uint32
    size = query(value, None, 0)
    if size:
        buffer = ctypes.create_unicode_buffer(size)
        written = query(value, buffer, size)
        if 0 < written < size:
            return buffer.value
    # An unavailable spelling keeps the original boundary; it grants no access.
    return value


def _observe(path):
    """Filesystem facts for one path, in the order probe() consults them.

    The facts are a pure function of the physical directory entry, so one
    observation can serve every spelling of it (another junction to the same
    target). Containment against approved roots is not part of it: that depends
    on the spelling and is always recomputed by probe().
    """
    facts = {"is_link": False, "direct_target": None, "resolved_path": None, "error": None}
    try:
        try:
            info = os.lstat(path)
            facts["is_link"] = stat.S_ISLNK(info.st_mode) or bool(
                getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
            if facts["is_link"]:
                facts["direct_target"] = os.readlink(path)
        except FileNotFoundError:
            pass
        facts["resolved_path"] = os.path.realpath(path)
    except (FileNotFoundError, NotADirectoryError):
        facts["error"] = "missing"
    except (OSError, ValueError):
        facts["error"] = "unreadable"
    return facts


def _observe_target(path, facts):
    """Add the final target's type to ``facts``; only asked for inside the roots."""
    if "stat_error" not in facts:
        facts["is_directory"], facts["stat_error"] = None, None
        try:
            facts["is_directory"] = stat.S_ISDIR(os.stat(path).st_mode)
        except (FileNotFoundError, NotADirectoryError):
            facts["stat_error"] = "missing"
        except (OSError, ValueError):
            facts["stat_error"] = "unreadable"
    return facts


def probe(path, approved_roots, *, memo=None, physical_key=None):
    """Retain direct and final targets; distinguish missing from unreadable.

    ``memo`` and ``physical_key`` let one discovery pass observe a physical entry
    once: callers key an entry by its resolved parent directory plus its name, so
    two links to the same target share the filesystem calls while each spelling
    keeps its own path and its own containment verdict.
    """
    result = {"path": str(path), "resolved_path": None, "direct_target": None,
              "is_link": False, "resolution": "unreadable", "resolved": "unknown"}
    try:
        if not any(within(path, root) for root in approved_roots):
            result.update(resolution="outside_approved_roots", resolved="no")
            return result
        facts = memo.get(physical_key) if memo is not None and physical_key is not None else None
        if facts is None:
            facts = _observe(path)
            if memo is not None and physical_key is not None:
                memo[physical_key] = facts
        result["is_link"] = facts["is_link"]
        result["direct_target"] = facts["direct_target"]
        if facts["error"] is not None:
            if facts["error"] == "missing":
                result.update(resolution="missing", resolved="no")
            return result
        result["resolved_path"] = facts["resolved_path"]
        if not any(within(result["resolved_path"], _long_path_spelling(root))
                   for root in approved_roots):
            result.update(resolution="outside_approved_roots", resolved="no")
            return result
        _observe_target(path, facts)
        if facts["stat_error"] is not None:
            if facts["stat_error"] == "missing":
                result.update(resolution="missing", resolved="no")
            return result
        result["is_directory"] = facts["is_directory"]
        result.update(resolution="resolved", resolved="yes")
    except (FileNotFoundError, NotADirectoryError):
        result.update(resolution="missing", resolved="no")
    except (OSError, ValueError):
        # Permission errors, loops and failed mounts do not establish absence.
        pass
    return result
