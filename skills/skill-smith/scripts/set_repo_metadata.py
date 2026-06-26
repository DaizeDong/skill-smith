#!/usr/bin/env python3
"""Set a skill repo's GitHub remote metadata to Skill Repo Spec v1 (topics + description + homepage).

This is the deploy-time complement to check_conformance.py (which only lints LOCAL files). It writes
the REMOTE metadata that a plain `git push` leaves unset -- the root-cause gap that left freshly
published skill repos with topics=null. Run it right after the first push (deploy.md Step 8), then
verify with check_remote_conformance.py (Gate G6b).

What it does (idempotent -- safe to re-run):
  (a) PUT repos/<owner>/<repo>/topics = base-9 + domain topics (deduped, lowercased, sanitized, <=20).
      PUT *replaces* the whole topic set, so re-running converges to exactly this set.
  (b) gh repo edit --description "<desc>"   (one-line description; long plugin.json desc is squeezed)
  (c) gh repo edit --homepage "<url>"       (Spec: github.com/<owner>/<repo>)

Defaults are read from the repo's own .claude-plugin/plugin.json so you rarely hand-type anything:
  - owner/repo  <- plugin.json homepage (github.com/<owner>/<repo>)
  - description <- plugin.json description (first sentence / truncated to a one-liner)
  - domain topics <- plugin.json keywords (drop trailing 'skill' + anything already in base-9)

Usage:
  python set_repo_metadata.py <repo_dir> [--owner O --repo R] [--description D]
                              [--topics t1,t2,...] [--homepage URL] [--dry-run]
  python set_repo_metadata.py --owner O --repo R [--topics ...] [--description D]

Exit 0 on success (or dry-run), 1 on failure, 2 on usage/precondition error.
Stdlib only. Never echoes secrets. Does NOT touch git identity or any other repo.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

# Skill Repo Spec v1 -- base-9 GitHub topics (identity fingerprint, every repo MUST carry all 9).
BASE9 = ["claude-code", "claude-plugin", "claude-skill", "claude",
         "ai", "ai-agent", "agent", "llm", "skill"]
MAX_TOPICS = 20  # GitHub hard limit


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
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def owner_repo_from_homepage(homepage):
    """Parse github.com/<owner>/<repo> out of a plugin.json homepage URL."""
    if not homepage:
        return None, None
    m = re.search(r"github\.com/([^/]+)/([^/#?]+)", homepage)
    if m:
        return m.group(1), m.group(2).rstrip("/")
    return None, None


def sanitize_topic(t):
    """GitHub topic rules: lowercase, hyphen-separated, alnum start, <=50 chars."""
    t = (t or "").strip().lower()
    t = re.sub(r"[^a-z0-9-]+", "-", t)      # non-alnum -> hyphen
    t = re.sub(r"-{2,}", "-", t).strip("-")  # collapse + trim hyphens
    t = t[:50].rstrip("-")
    return t


def derive_domain_topics(keywords, extra):
    """keywords (minus trailing 'skill' + base-9 members) + any --topics extras -> domain topics."""
    base = set(BASE9)
    seen, out = set(), []
    for raw in list(keywords or []) + list(extra or []):
        t = sanitize_topic(raw)
        if not t or t == "skill" or t in base or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def build_topics(keywords, extra):
    """base-9 first (so they survive the <=20 cap), then domain topics; deduped, capped."""
    out, seen = [], set()
    for t in BASE9 + derive_domain_topics(keywords, extra):
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out[:MAX_TOPICS]


def one_line_description(desc):
    """Squeeze a (possibly long) plugin.json description into a single repo tagline."""
    if not desc:
        return ""
    desc = " ".join(desc.split())
    # prefer the first sentence; fall back to a hard truncation.
    m = re.match(r"(.+?[.!?])(\s|$)", desc)
    cand = m.group(1) if m else desc
    if len(cand) > 350:
        cand = cand[:347].rstrip() + "..."
    return cand


def gh_path():
    return shutil.which("gh")


def run_gh(args, input_text=None):
    gh = gh_path()
    if not gh:
        return None
    return subprocess.run([gh] + args, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", input=input_text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo_dir", nargs="?", help="path to the skill repo (reads plugin.json defaults)")
    ap.add_argument("--owner")
    ap.add_argument("--repo")
    ap.add_argument("--description")
    ap.add_argument("--topics", help="extra domain topics, comma-separated (added to keywords)")
    ap.add_argument("--homepage")
    ap.add_argument("--dry-run", action="store_true", help="print intended changes, make none")
    a = ap.parse_args()

    repo_dir = os.path.abspath(os.path.expanduser(a.repo_dir)) if a.repo_dir else None
    pj = load_plugin(repo_dir)

    # resolve owner/repo
    owner, repo = a.owner, a.repo
    if not (owner and repo):
        o2, r2 = owner_repo_from_homepage(pj.get("homepage"))
        owner = owner or o2
        repo = repo or r2 or (pj.get("name") if pj else None)
    if not (owner and repo):
        print("ERROR: could not resolve owner/repo. Pass --owner/--repo or a repo_dir with a "
              "plugin.json homepage (github.com/<owner>/<repo>).", file=sys.stderr)
        return 2

    extra = [t for t in (a.topics.split(",") if a.topics else []) if t.strip()]
    topics = build_topics(pj.get("keywords", []), extra)
    description = a.description if a.description is not None else one_line_description(pj.get("description"))
    homepage = a.homepage or pj.get("homepage") or ("https://github.com/%s/%s" % (owner, repo))

    print("set_repo_metadata -> %s/%s" % (owner, repo))
    print("  topics (%d): %s" % (len(topics), ", ".join(topics)))
    print("  description: %s" % (description or "(none)"))
    print("  homepage:    %s" % homepage)

    if a.dry_run:
        print("  [dry-run] no changes made.")
        return 0

    if not gh_path():
        print("ERROR: gh CLI not found on PATH; cannot set remote metadata.", file=sys.stderr)
        return 2

    rc = 0
    # (a) topics -- PUT replaces the whole set (idempotent convergence)
    payload = json.dumps({"names": topics})
    r = run_gh(["api", "--method", "PUT", "repos/%s/%s/topics" % (owner, repo), "--input", "-"],
               input_text=payload)
    if r is None or r.returncode != 0:
        print("  [FAIL] set topics: %s" % ((r.stderr or r.stdout).strip() if r else "gh missing"),
              file=sys.stderr)
        rc = 1
    else:
        print("  [ok] topics set (%d)" % len(topics))

    # (b) description
    if description:
        r = run_gh(["repo", "edit", "%s/%s" % (owner, repo), "--description", description])
        if r is None or r.returncode != 0:
            print("  [FAIL] set description: %s" % ((r.stderr or r.stdout).strip() if r else "gh missing"),
                  file=sys.stderr)
            rc = 1
        else:
            print("  [ok] description set")

    # (c) homepage
    if homepage:
        r = run_gh(["repo", "edit", "%s/%s" % (owner, repo), "--homepage", homepage])
        if r is None or r.returncode != 0:
            print("  [FAIL] set homepage: %s" % ((r.stderr or r.stdout).strip() if r else "gh missing"),
                  file=sys.stderr)
            rc = 1
        else:
            print("  [ok] homepage set")

    print("DONE" if rc == 0 else "COMPLETED WITH FAILURES")
    return rc


if __name__ == "__main__":
    sys.exit(main())
