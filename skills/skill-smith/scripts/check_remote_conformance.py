#!/usr/bin/env python3
"""Skill Repo Spec v1 REMOTE linter -- Acceptance Gate G6b. See ../reference/acceptance-gate.md.

G6 (check_conformance.py) only validates LOCAL files; it cannot see what GitHub actually stored. The
root cause of the topics=null incident was exactly that blind spot: repos passed G6, were pushed, and
shipped with NO remote topics/description because `git push` never sets them. G6b closes the loop by
querying the live GitHub repo and asserting the Spec-v1 remote metadata is in place.

Checks (against the live repo via gh):
  - base-9 topics ALL present (claude-code claude-plugin claude-skill claude ai ai-agent agent llm skill)
  - at least one DOMAIN topic beyond the base-9
  - description non-empty
  - homepage == github.com/<owner>/<repo>  (advisory: reported, does not by itself fail the gate)

Usage:
  python check_remote_conformance.py <repo_dir>          # owner/repo from plugin.json homepage
  python check_remote_conformance.py --owner O --repo R

Exit 0 = PASS or SKIP (no gh / not authenticated / offline -- stated explicitly, never silent),
1 = FAIL (reachable repo missing required remote metadata), 2 = usage/precondition error.
Stdlib only. Never echoes secrets.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

BASE9 = ["claude-code", "claude-plugin", "claude-skill", "claude",
         "ai", "ai-agent", "agent", "llm", "skill"]
PASS, FAIL = "PASS", "FAIL"


def read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None


def load_plugin(repo_dir):
    if not repo_dir:
        return {}
    raw = read(os.path.join(repo_dir, ".claude-plugin", "plugin.json"))
    try:
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def owner_repo_from_homepage(homepage):
    if not homepage:
        return None, None
    m = re.search(r"github\.com/([^/]+)/([^/#?]+)", homepage)
    return (m.group(1), m.group(2).rstrip("/")) if m else (None, None)


def run_gh(args):
    gh = shutil.which("gh")
    if not gh:
        return None
    return subprocess.run([gh] + args, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def fetch_remote(owner, repo):
    """Return (data, skip_reason). data = {topics, description, homepage} or None if we must SKIP."""
    if not shutil.which("gh"):
        return None, "gh CLI not found on PATH"
    r = run_gh(["repo", "view", "%s/%s" % (owner, repo),
                "--json", "repositoryTopics,description,homepageUrl"])
    if r is None:
        return None, "gh CLI not found on PATH"
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip().lower()
        if any(k in err for k in ("auth", "login", "token", "gh auth")):
            return None, "gh not authenticated (run `gh auth login`)"
        if any(k in err for k in ("could not resolve", "network", "timeout", "dial tcp", "offline")):
            return None, "offline / network error reaching GitHub"
        if "not found" in err or "404" in err:
            return None, None  # reachable but repo absent -> handled by caller as FAIL? treat as SKIP-ish
        return None, "gh repo view failed: %s" % (r.stderr or r.stdout or "").strip()
    try:
        j = json.loads(r.stdout)
    except Exception as e:
        return None, "could not parse gh JSON: %s" % e
    rt = j.get("repositoryTopics") or []
    # gh returns either [{"name": "x"}, ...] or ["x", ...] across versions -> normalize.
    topics = []
    for t in rt:
        if isinstance(t, dict):
            topics.append((t.get("name") or t.get("topic", {}).get("name") or "").lower())
        elif isinstance(t, str):
            topics.append(t.lower())
    topics = [t for t in topics if t]
    return {"topics": topics, "description": (j.get("description") or "").strip(),
            "homepage": (j.get("homepageUrl") or "").strip()}, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo_dir", nargs="?")
    ap.add_argument("--owner")
    ap.add_argument("--repo")
    a = ap.parse_args()

    repo_dir = os.path.abspath(os.path.expanduser(a.repo_dir)) if a.repo_dir else None
    pj = load_plugin(repo_dir)
    owner, repo = a.owner, a.repo
    if not (owner and repo):
        o2, r2 = owner_repo_from_homepage(pj.get("homepage"))
        owner = owner or o2
        repo = repo or r2 or (pj.get("name") if pj else None)
    if not (owner and repo):
        print("ERROR: could not resolve owner/repo. Pass --owner/--repo or a repo_dir whose "
              "plugin.json homepage is github.com/<owner>/<repo>.", file=sys.stderr)
        return 2

    print("Skill Repo Spec v1 REMOTE conformance (G6b): %s/%s" % (owner, repo))
    print("-" * 64)

    data, skip = fetch_remote(owner, repo)
    if data is None:
        if skip is None:
            print("  [FAIL] repo not found on GitHub (nothing published yet?)")
            print("-" * 64)
            print("FAIL: remote repo unreachable as a real repo.")
            return 1
        print("  SKIP: %s" % skip)
        print("-" * 64)
        print("SKIP: remote metadata not verified (stated, not silent). Re-run once gh is "
              "available/authenticated and online.")
        return 0

    topics = data["topics"]
    results = []

    missing_base = [t for t in BASE9 if t not in topics]
    results.append(("base-9 topics all present", not missing_base,
                    "missing: %s" % ", ".join(missing_base) if missing_base else ""))

    domain = [t for t in topics if t not in set(BASE9)]
    results.append((">=1 domain topic beyond base-9", len(domain) >= 1,
                    "domain topics: %s" % (", ".join(domain) or "(none)")))

    desc_ok = bool(data["description"])
    results.append(("description non-empty", desc_ok,
                    "" if desc_ok else "remote description is empty"))

    # homepage -- advisory only (Spec target pattern), does not flip the verdict.
    expected_home = "https://github.com/%s/%s" % (owner, repo)
    home_ok = data["homepage"].rstrip("/") == expected_home.rstrip("/")

    n_fail = 0
    for nm, ok, detail in results:
        if not ok:
            n_fail += 1
        line = "  [%s] %s" % (PASS if ok else FAIL, nm)
        if detail:
            line += "  -> %s" % detail
        print(line)
    # advisory line
    print("  [%s] homepage == %s  (advisory)" %
          ("PASS" if home_ok else "WARN", expected_home) +
          ("" if home_ok else "  -> got: %s" % (data["homepage"] or "(empty)")))

    print("-" * 64)
    print("  topics on repo (%d): %s" % (len(topics), ", ".join(topics) or "(none)"))
    if n_fail == 0:
        print("PASS: remote metadata conforms to Skill Repo Spec v1.")
        return 0
    print("FAIL (%d): remote metadata incomplete -> run set_repo_metadata.py and re-check." % n_fail)
    return 1


if __name__ == "__main__":
    sys.exit(main())
