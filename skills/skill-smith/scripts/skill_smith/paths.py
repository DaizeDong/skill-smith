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


def probe(path, approved_roots):
    """Retain direct and final targets; distinguish missing from unreadable."""
    result = {"path": str(path), "resolved_path": None, "direct_target": None,
              "is_link": False, "resolution": "unreadable", "resolved": "unknown"}
    try:
        if not any(within(path, root) for root in approved_roots):
            result.update(resolution="outside_approved_roots", resolved="no")
            return result
        try:
            info = os.lstat(path)
            result["is_link"] = stat.S_ISLNK(info.st_mode) or bool(
                getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
            if result["is_link"]:
                result["direct_target"] = os.readlink(path)
        except FileNotFoundError:
            pass
        result["resolved_path"] = os.path.realpath(path)
        if not any(within(result["resolved_path"], root) for root in approved_roots):
            result.update(resolution="outside_approved_roots", resolved="no")
            return result
        info = os.stat(path)
        result["is_directory"] = stat.S_ISDIR(info.st_mode)
        result.update(resolution="resolved", resolved="yes")
    except (FileNotFoundError, NotADirectoryError):
        result.update(resolution="missing", resolved="no")
    except (OSError, ValueError):
        # Permission errors, loops and failed mounts do not establish absence.
        pass
    return result
