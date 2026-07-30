#!/usr/bin/env python3
"""Single source of truth for WHERE a Skill-Repo-Spec-v1 version lives, and what shape it has.

Five sites carry the same version:

  plugin     .claude-plugin/plugin.json   "version": "X.Y.Z"
  README     README.md                    the Roadmap badge, Roadmap-vX.Y.Z[%20<pre>]-purple
  README_CN  README_CN.md                 the same badge
  ROADMAP    ROADMAP.md                   Current: **vX.Y.Z**
  CHANGELOG  CHANGELOG.md                 the topmost  ## [X.Y.Z] - <date>

scaffold_skill.py stamps them once at creation, check_conformance.py reads them, bump_version.py
rewrites them. Each of those used to carry its own private idea of the shape, and that is exactly
how a badge with a legitimate pre-release marker (Roadmap-v0.2.2%20alpha-purple) got read as "no
version at all" and reported the repo as drifted when all five sites agreed. One definition, here,
and nowhere else.

Note on the pre-release marker: it lives in the BADGE ONLY. shields.io encodes a space as %20, so
"v0.2.2 alpha" is written "v0.2.2%20alpha". plugin.json, ROADMAP and CHANGELOG stay plain semver,
because they are read by machines that expect semver. A bump round-trips the marker rather than
flattening it.

Stdlib only.
"""
from __future__ import annotations

import json
import os
import re

# --- the version shape -------------------------------------------------------------------------
SEMVER = r"[0-9]+\.[0-9]+\.[0-9]+"
# URL-encoded space + a pre-release word, e.g. "%20alpha", "%20rc.1". Optional.
PRERELEASE = r"(?:%20[A-Za-z0-9.]+)?"

RE_SEMVER_ONLY = re.compile(r"\A" + SEMVER + r"\Z")
RE_PRERELEASE_TAG = re.compile(r"\A[A-Za-z0-9.]+\Z")

# --- the five sites ----------------------------------------------------------------------------
PLUGIN_REL = os.path.join(".claude-plugin", "plugin.json")
PLUGIN_VERSION_FIELD = "version"

SITE_FILES = {
    "plugin": PLUGIN_REL,
    "README": "README.md",
    "README_CN": "README_CN.md",
    "ROADMAP": "ROADMAP.md",
    "CHANGELOG": "CHANGELOG.md",
}
# Report order, kept stable so the conformance FAIL detail stays diffable across runs.
SITE_ORDER = ("plugin", "README", "README_CN", "ROADMAP", "CHANGELOG")

RE_BADGE = re.compile(r"(Roadmap-v)(" + SEMVER + r")(" + PRERELEASE + r")(-purple)")
RE_ROADMAP_CURRENT = re.compile(r"(Current:\s*\*\*v)(" + SEMVER + r")(\*\*)")
RE_CHANGELOG_HEADING = re.compile(r"^##\s*\[(" + SEMVER + r")\]", re.M)
# Keep a Changelog's staging area. Not a version site (it has no version), but the heading a bump
# converts INTO one, so its shape belongs next to the others.
RE_CHANGELOG_UNRELEASED = re.compile(r"^##\s*\[Unreleased\][^\r\n]*", re.M | re.I)
RE_ROADMAP_CURRENT_HEADING = re.compile(r"^##\s+v(" + SEMVER + r")(.*)$", re.M)

# The badge block every conformant README opens with. __VER__ is substituted at scaffold time.
ROADMAP_BADGE_TMPL = (
    "[![Roadmap](https://img.shields.io/badge/Roadmap-v__VER__-purple?style=flat)](ROADMAP.md)\n"
)
REQUIRED_BADGES = (
    "[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-orange?style=flat)]"
    "(https://docs.anthropic.com/en/docs/claude-code)\n"
    "[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)\n"
    "[![Languages](https://img.shields.io/badge/Languages-EN%20%2F%20CN-blue?style=flat)](#languages)\n"
    + ROADMAP_BADGE_TMPL
)


# --- io ------------------------------------------------------------------------------------------
def read_text(path):
    """Read a site file preserving its line endings verbatim (newline="")."""
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            return f.read()
    except Exception:
        return None


def newline_of(text):
    """The dominant line ending of an existing file, so inserted lines match it."""
    return "\r\n" if text and "\r\n" in text else "\n"


# --- readers ---------------------------------------------------------------------------------------
def badge_version(text):
    """Return (version, prerelease_suffix) from a Roadmap badge; ("", "") pieces are ('' , '')."""
    m = RE_BADGE.search(text or "")
    if not m:
        return None, ""
    return m.group(2), m.group(3)


def roadmap_version(text):
    m = RE_ROADMAP_CURRENT.search(text or "")
    return m.group(2) if m else None


def changelog_version(text):
    m = RE_CHANGELOG_HEADING.search(text or "")
    return m.group(1) if m else None


def plugin_version(raw):
    if not raw:
        return None
    try:
        return json.loads(raw).get(PLUGIN_VERSION_FIELD)
    except Exception:
        return None


def collect(root):
    """Read the version at all five sites. Missing / unparseable site -> None.

    Returns a dict keyed by SITE_ORDER. A site that is absent reads None rather than raising, so
    the caller can report the whole picture instead of dying on the first hole.
    """
    root = os.path.abspath(os.path.expanduser(root))

    def p(key):
        return os.path.join(root, SITE_FILES[key])

    out = {}
    out["plugin"] = plugin_version(read_text(p("plugin")))
    out["README"] = badge_version(read_text(p("README")))[0]
    out["README_CN"] = badge_version(read_text(p("README_CN")))[0]
    out["ROADMAP"] = roadmap_version(read_text(p("ROADMAP")))
    out["CHANGELOG"] = changelog_version(read_text(p("CHANGELOG")))
    return {k: out[k] for k in SITE_ORDER}


def collect_prerelease(root):
    """The pre-release suffix carried by each README badge, e.g. "%20alpha". "" when plain."""
    root = os.path.abspath(os.path.expanduser(root))
    return {
        "README": badge_version(read_text(os.path.join(root, SITE_FILES["README"])))[1],
        "README_CN": badge_version(read_text(os.path.join(root, SITE_FILES["README_CN"])))[1],
    }


def is_synced(versions):
    """True when every site was found AND they all agree."""
    vals = [versions.get(k) for k in SITE_ORDER]
    return all(vals) and len(set(vals)) == 1


# --- writers (pure text in, text out) ------------------------------------------------------------
def set_badge_version(text, new_ver, new_pre=None):
    """Rewrite every Roadmap badge to new_ver. new_pre=None keeps whatever suffix is there.

    Returns (new_text, count).
    """
    def repl(m):
        pre = m.group(3) if new_pre is None else new_pre
        return m.group(1) + new_ver + pre + m.group(4)

    return RE_BADGE.subn(repl, text)


def set_roadmap_current(text, new_ver):
    """Rewrite the 'Current: **vX.Y.Z**' line. Returns (new_text, count)."""
    return RE_ROADMAP_CURRENT.subn(lambda m: m.group(1) + new_ver + m.group(3), text)


def set_plugin_version(raw, old_ver, new_ver):
    """Rewrite plugin.json's version field in place, byte for byte otherwise.

    A targeted substitution, not a json.dumps round-trip: reserializing would silently reformat a
    file a human may have laid out deliberately. The result is re-parsed and asserted before it is
    handed back, so a malformed edit cannot escape.
    """
    pat = re.compile(r'("' + re.escape(PLUGIN_VERSION_FIELD) + r'"\s*:\s*")' + re.escape(old_ver) + r'(")')
    new_raw, n = pat.subn(lambda m: m.group(1) + new_ver + m.group(2), raw, count=1)
    if n != 1:
        raise ValueError("plugin.json: could not locate %r: %r" % (PLUGIN_VERSION_FIELD, old_ver))
    if json.loads(new_raw).get(PLUGIN_VERSION_FIELD) != new_ver:
        raise ValueError("plugin.json: rewrite did not take")
    return new_raw


def changelog_heading(ver, date):
    return "## [%s] - %s" % (ver, date)


def parse_semver(s):
    if not RE_SEMVER_ONLY.match(s or ""):
        raise ValueError("not a semver X.Y.Z: %r" % (s,))
    return tuple(int(x) for x in s.split("."))


def next_version(cur, level):
    """major / minor / patch bump of a plain semver string."""
    major, minor, patch = parse_semver(cur)
    if level == "major":
        return "%d.0.0" % (major + 1)
    if level == "minor":
        return "%d.%d.0" % (major, minor + 1)
    if level == "patch":
        return "%d.%d.%d" % (major, minor, patch + 1)
    raise ValueError("unknown level: %r" % (level,))
