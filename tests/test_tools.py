#!/usr/bin/env python3
"""A-provider signal for skill-smith: assert the pipeline and every tool work.

This is the self-evolve A-tier grader for this repo. It must:
  - exit 0 when the 4 scripts are correct, and
  - go red (mutation_killed) when any script is broken.

Run:  python -m pytest -q   (from repo root)

Stdlib + pytest only. No network. Cross-platform (uses tmp_path, no shell).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

# ---------------------------------------------------------------------------
# Locate scripts relative to this test file (repo-root independent).
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_REPO, "skills", "skill-smith", "scripts")

SCAFFOLD = os.path.join(_SCRIPTS, "scaffold_skill.py")
CONFORM = os.path.join(_SCRIPTS, "check_conformance.py")
BUDGET = os.path.join(_SCRIPTS, "budget_check.py")
DEDUP = os.path.join(_SCRIPTS, "dedup_check.py")


def run(args, **kw):
    """Run a script as a subprocess; return CompletedProcess (text)."""
    proc = subprocess.run(
        [sys.executable] + args,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, **kw,
    )
    return proc


def write_utf8(path, text, bom=False):
    """Write text without (default) or with a UTF-8 BOM, no platform newline mangling."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = text.encode("utf-8-sig" if bom else "utf-8")
    with open(path, "wb") as f:
        f.write(data)


def make_skill(libdir, name, desc, bom=False):
    """Create <libdir>/<name>/SKILL.md with given frontmatter."""
    body = "---\nname: %s\ndescription: %s\n---\nbody\n" % (name, desc)
    write_utf8(os.path.join(libdir, name, "SKILL.md"), body, bom=bom)


# ===========================================================================
# 0. Scripts exist and are importable as files
# ===========================================================================

def test_scripts_present():
    for p in (SCAFFOLD, CONFORM, BUDGET, DEDUP):
        assert os.path.isfile(p), "missing tool: %s" % p


# ===========================================================================
# 1. check_conformance on skill-smith itself -> 20/20, exit 0
# ===========================================================================

def test_conformance_self_passes():
    r = run([CONFORM, _REPO])
    assert r.returncode == 0, "skill-smith must pass its own gate:\n%s\n%s" % (r.stdout, r.stderr)
    assert "passed" in r.stdout
    # every line must be PASS (no FAIL anywhere)
    assert "[FAIL]" not in r.stdout, r.stdout


def test_conformance_bad_dir_fails():
    """A directory missing required files must FAIL (grader is discriminating, not a rubber stamp)."""
    r = run([CONFORM, _SCRIPTS])  # scripts dir is not a spec repo
    assert r.returncode == 1, "non-conformant dir must exit 1:\n%s" % r.stdout
    assert "[FAIL]" in r.stdout


# ===========================================================================
# 2. End-to-end: scaffold -> check_conformance passes (the core pipeline)
# ===========================================================================

def test_scaffold_then_conformance(tmp_path):
    out = str(tmp_path / "out")
    r = run([SCAFFOLD, "my-skill",
             "--tagline", "Do the thing fast.",
             "--description", "When the user wants X, do Y in scope Z.",
             "--topics", "alpha,beta",
             "--out-dir", out, "--version", "0.3.0"])
    assert r.returncode == 0, r.stdout + r.stderr
    repo = os.path.join(out, "my-skill")
    assert os.path.isdir(repo)
    c = run([CONFORM, repo])
    assert c.returncode == 0, "scaffold output must be 20/20 conformant:\n%s" % c.stdout
    assert "[FAIL]" not in c.stdout


def test_scaffold_kebab_normalization(tmp_path):
    out = str(tmp_path / "out")
    r = run([SCAFFOLD, "Test Skill_FOO",
             "--description", "x", "--out-dir", out])
    assert r.returncode == 0, r.stdout + r.stderr
    assert os.path.isdir(os.path.join(out, "test-skill-foo")), \
        "messy name must normalize to kebab-case: %s" % os.listdir(out)
    assert "normalized name" in r.stdout


def test_scaffold_rejects_empty_name(tmp_path):
    """A name that kebab-normalizes to empty must be refused with a clear error,
    not silently collapse the repo root onto --out-dir itself."""
    out = str(tmp_path / "out")
    os.makedirs(out, exist_ok=True)
    r = run([SCAFFOLD, "___", "--description", "x", "--out-dir", out])
    assert r.returncode == 2, "empty kebab name must be rejected (exit 2):\n%s" % r.stdout
    # Must be the *empty-name* error specifically, not the generic "already exists" path
    # the unfixed scaffold falls into when root collapses onto --out-dir.
    assert "normalizes to empty" in r.stdout, \
        "must give a clear empty-name error, not 'already exists':\n%s" % r.stdout
    assert os.listdir(out) == [], "must not scaffold anything for an empty name: %s" % os.listdir(out)


def test_dedup_candidate_case_insensitive(tmp_path):
    """An UPPERCASE candidate description must still match a lowercase library entry
    (tokenization lowercases), otherwise dedup misses real duplicates by mere casing."""
    lib = str(tmp_path / "lib")
    make_skill(lib, "alpha", "parse pdf invoices and extract totals.")
    r = run([DEDUP, "--skills-dir", lib, "--threshold", "0.4",
             "--desc", "PARSE PDF INVOICES AND EXTRACT TOTALS", "--name", "C"])
    assert r.returncode == 1, "uppercase duplicate must be flagged:\n%s" % r.stdout


def test_scaffold_version_four_source_sync(tmp_path):
    """The four version sources the linter checks must all carry the --version value."""
    out = str(tmp_path / "out")
    ver = "1.2.3"
    r = run([SCAFFOLD, "verskill", "--description", "x", "--out-dir", out, "--version", ver])
    assert r.returncode == 0
    repo = os.path.join(out, "verskill")
    pj = json.loads(open(os.path.join(repo, ".claude-plugin", "plugin.json"), encoding="utf-8").read())
    assert pj["version"] == ver
    readme = open(os.path.join(repo, "README.md"), encoding="utf-8").read()
    roadmap = open(os.path.join(repo, "ROADMAP.md"), encoding="utf-8").read()
    changelog = open(os.path.join(repo, "CHANGELOG.md"), encoding="utf-8").read()
    assert ("Roadmap-v%s-purple" % ver) in readme
    assert ("Current: **v%s**" % ver) in roadmap
    assert ("[%s]" % ver) in changelog


def test_scaffold_plugin_fingerprint(tmp_path):
    out = str(tmp_path / "out")
    r = run([SCAFFOLD, "fp-skill", "--description", "x", "--topics", "foo,bar", "--out-dir", out])
    assert r.returncode == 0
    pj = json.loads(open(os.path.join(out, "fp-skill", ".claude-plugin", "plugin.json"),
                         encoding="utf-8").read())
    assert pj["author"]["name"] == "DaizeDong"
    assert pj["license"] == "MIT"
    assert pj["homepage"] == "https://github.com/DaizeDong/fp-skill"
    assert pj["keywords"][-1] == "skill"
    assert "foo" in pj["keywords"] and "bar" in pj["keywords"]


def test_scaffold_refuses_without_force(tmp_path):
    out = str(tmp_path / "out")
    a1 = run([SCAFFOLD, "dup", "--description", "x", "--out-dir", out])
    assert a1.returncode == 0
    a2 = run([SCAFFOLD, "dup", "--description", "x", "--out-dir", out])  # no --force
    assert a2.returncode == 2, "existing repo without --force must refuse (exit 2):\n%s" % a2.stdout
    a3 = run([SCAFFOLD, "dup", "--description", "x", "--out-dir", out, "--force"])
    assert a3.returncode == 0, "with --force it must overwrite:\n%s" % a3.stdout


# ===========================================================================
# 3. budget_check: three tiers, only ours can fail, and the plugin tier is
#    read from installed_plugins.json rather than globbed out of the cache
# ===========================================================================

def empty_plugins(tmp_path):
    """An installed_plugins.json with nothing in it, so a test measures only the user tier."""
    p = tmp_path / "installed_plugins.json"
    p.write_text(json.dumps({"version": 2, "plugins": {}}), encoding="utf-8")
    return str(p)


def squeeze(text):
    """Collapse runs of spaces, so an assertion tests the report's CONTENT, not its column widths."""
    return " ".join(text.split())


def test_budget_totals(tmp_path):
    """Cost is the listing line, "- name: desc\\n", so 5 chars of framing per skill."""
    lib = str(tmp_path / "lib")
    make_skill(lib, "alpha", "parse pdf invoices and extract totals.")       # 5 + 38 + 5 = 48
    make_skill(lib, "beta", "parse pdf invoices and extract totals fast.")   # 4 + 43 + 5 = 52
    r = run([BUDGET, "--skills-dir", lib, "--code-root", str(tmp_path / "nope"),
             "--installed-plugins", empty_plugins(tmp_path)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "TOTAL 2 skills 100 chars" in squeeze(r.stdout), r.stdout


def test_budget_tiers_are_reported_separately(tmp_path):
    """A skill resolving under the code root is OURS; anything else is not."""
    code_root = tmp_path / "code"
    lib = code_root / "lib"                       # inside the code root -> tier "ours"
    make_skill(str(lib), "mine", "short one.")
    outside = tmp_path / "outside"
    make_skill(str(outside), "theirs", "short two.")
    # Point the scan at a dir holding both by scanning the outside dir with a code root that
    # cannot contain it, then again with one that can.
    r = run([BUDGET, "--skills-dir", str(lib), "--code-root", str(code_root),
             "--installed-plugins", empty_plugins(tmp_path)])
    assert "tier ours 1 skills" in squeeze(r.stdout), r.stdout
    assert "tier other 0 skills" in squeeze(r.stdout), r.stdout
    r2 = run([BUDGET, "--skills-dir", str(outside), "--code-root", str(code_root),
              "--installed-plugins", empty_plugins(tmp_path)])
    assert "tier ours 0 skills" in squeeze(r2.stdout), r2.stdout
    assert "tier other 1 skills" in squeeze(r2.stdout), r2.stdout


def test_budget_per_skill_cap_fails_only_for_ours(tmp_path):
    """The 180-char per-skill cap is a FAIL for our tier and a printed note for anyone else."""
    code_root = tmp_path / "code"
    lib = code_root / "lib"
    make_skill(str(lib), "fat", "x" * 200)
    ours = run([BUDGET, "--skills-dir", str(lib), "--code-root", str(code_root),
                "--installed-plugins", empty_plugins(tmp_path)])
    assert ours.returncode == 1, "our own over-cap description must fail:\n%s" % ours.stdout
    assert "over the 180 per-skill cap" in ours.stdout
    # Identical library, but now nothing resolves under the code root.
    theirs = run([BUDGET, "--skills-dir", str(lib), "--code-root", str(tmp_path / "elsewhere"),
                  "--installed-plugins", empty_plugins(tmp_path)])
    assert theirs.returncode == 0, "a third-party description is not ours to fail on:\n%s" % theirs.stdout
    assert "not ours to edit" in theirs.stdout


def test_budget_plugin_tier_comes_from_installed_plugins(tmp_path):
    """Active installPaths are counted once; a stale record is NAMED, never silently dropped.

    The cache on a real machine holds 2 to 4 versions of each plugin plus scratch clones, so a
    glob reports a library many times larger than the one that is loaded.
    """
    cache = tmp_path / "cache"
    active = cache / "demo" / "2.0.0"
    stale = cache / "demo" / "1.0.0"
    make_skill(str(active / "skills"), "demo-skill", "the active one.")
    make_skill(str(stale / "skills"), "demo-skill", "the stale one that must not be counted.")
    inst = tmp_path / "installed_plugins.json"
    inst.write_text(json.dumps({"version": 2, "plugins": {
        # two records for one plugin: the same skill must be counted once
        "demo@market": [{"installPath": str(active)}, {"installPath": str(active)}],
        "ghost@market": [{"installPath": str(cache / "ghost" / "9.9.9")}],
    }}), encoding="utf-8")
    lib = str(tmp_path / "lib")
    make_skill(lib, "user-one", "a user skill.")
    r = run([BUDGET, "--skills-dir", lib, "--code-root", str(tmp_path / "nope"),
             "--installed-plugins", str(inst)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "tier plugin 1 skills" in squeeze(r.stdout), "stale version or duplicate record counted:\n%s" % r.stdout
    assert "the stale one" not in r.stdout, r.stdout
    assert "UNRESOLVABLE plugin records" in r.stdout and "ghost@market" in r.stdout, \
        "a plugin whose installPath is gone must be named, not treated as zero:\n%s" % r.stdout


def test_budget_reports_both_cutoffs_and_names_the_truncated(tmp_path):
    """The documented constant and the observed cutoff disagree; print both, name the victims."""
    lib = str(tmp_path / "lib")
    for i in range(40):
        make_skill(lib, "skill%02d" % i, "y" * 700)      # ~28k chars total, well past the cutoff
    r = run([BUDGET, "--skills-dir", lib, "--code-root", str(tmp_path / "nope"),
             "--installed-plugins", empty_plugins(tmp_path)])
    assert "documented budget : 15000 chars" in squeeze(r.stdout), r.stdout
    assert "OBSERVED cutoff : between 19943 and 20231" in squeeze(r.stdout), r.stdout
    assert "PAST THE CUTOFF" in r.stdout, r.stdout
    assert "certainly truncated" in r.stdout, r.stdout


def test_budget_fails_when_any_tier_is_past_the_cutoff(tmp_path):
    """A skill past the truncation cutoff fails the check no matter who wrote its description.

    The regression: the verdict used to be gated on tier, so the only harm this tool exists to find
    could not turn it red. Every description here is UNDER the per-skill cap and NONE of them is
    ours, so truncation is the sole possible reason for a nonzero exit. Under the old rule this
    library exited 0 with dozens of skills silently missing from the prompt.
    """
    lib = str(tmp_path / "lib")
    for i in range(130):
        make_skill(lib, "skill%03d" % i, "y" * 150)      # under the 180 cap, past the cutoff
    r = run([BUDGET, "--skills-dir", lib, "--code-root", str(tmp_path / "nope"),
             "--installed-plugins", empty_plugins(tmp_path)])
    assert r.returncode == 1, "a truncated third-party skill must fail:\n%s" % r.stdout[-2000:]
    assert "over the 180 per-skill cap" not in r.stdout, \
        "no description here is over the cap, so the cap must not be the reason:\n%s" % r.stdout[-2000:]
    assert "the agent cannot see this skill at all" in r.stdout, r.stdout[-2000:]
    # The operator is told the lever, and told that editing someone else's description is not it.
    assert "THE LEVER" in r.stdout, r.stdout[-2000:]
    assert "uninstall a plugin" in r.stdout, r.stdout[-2000:]
    assert "trim OUR descriptions" in r.stdout, r.stdout[-2000:]


def test_budget_ok_when_nothing_is_truncated(tmp_path):
    """The companion assertion: the condition above is what fails, not merely having other tiers."""
    lib = str(tmp_path / "lib")
    for i in range(5):
        make_skill(lib, "skill%02d" % i, "y" * 150)
    r = run([BUDGET, "--skills-dir", lib, "--code-root", str(tmp_path / "nope"),
             "--installed-plugins", empty_plugins(tmp_path)])
    assert r.returncode == 0, r.stdout[-2000:]
    assert "Nothing is past the observed cutoff." in r.stdout, r.stdout[-2000:]


def test_budget_extra_candidate(tmp_path):
    lib = str(tmp_path / "lib")
    make_skill(lib, "one", "abc")
    base = run([BUDGET, "--skills-dir", lib, "--code-root", str(tmp_path / "nope"),
                "--installed-plugins", empty_plugins(tmp_path)])
    assert base.returncode == 0
    withx = run([BUDGET, "--skills-dir", lib, "--code-root", str(tmp_path / "nope"),
                 "--installed-plugins", empty_plugins(tmp_path), "--extra", "y" * 50])
    assert withx.returncode == 0
    assert "candidate description" in withx.stdout


def test_budget_bom_tolerant(tmp_path):
    """A SKILL.md saved with a UTF-8 BOM (common on Windows editors) must still be counted.

    Regression guard: parse_frontmatter must not be defeated by a leading BOM, otherwise
    the budget silently under-counts and a library can overflow undetected.
    """
    lib = str(tmp_path / "lib")
    make_skill(lib, "withbom", "parse pdf invoices and extract totals.", bom=True)
    r = run([BUDGET, "--skills-dir", lib, "--code-root", str(tmp_path / "nope"),
             "--installed-plugins", empty_plugins(tmp_path)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "TOTAL 1 skills" in squeeze(r.stdout), \
        "BOM'd SKILL.md was dropped (under-count):\n%s" % r.stdout


# ===========================================================================
# 4. dedup_check: flags a known duplicate + --desc candidate mode
# ===========================================================================

def test_dedup_flags_pair(tmp_path):
    lib = str(tmp_path / "lib")
    make_skill(lib, "alpha", "parse pdf invoices and extract totals.")
    make_skill(lib, "beta", "parse pdf invoices and extract totals fast.")
    r = run([DEDUP, "--skills-dir", lib, "--threshold", "0.4"])
    assert r.returncode == 1, "near-duplicate pair must be flagged (exit 1):\n%s" % r.stdout
    assert "alpha" in r.stdout and "beta" in r.stdout


def test_dedup_distinct_ok(tmp_path):
    lib = str(tmp_path / "lib")
    make_skill(lib, "alpha", "parse pdf invoices and extract totals.")
    make_skill(lib, "gamma", "schedule recurring kubernetes cluster backups nightly.")
    r = run([DEDUP, "--skills-dir", lib, "--threshold", "0.4"])
    assert r.returncode == 0, "distinct descriptions must pass:\n%s" % r.stdout


def test_dedup_desc_candidate_mode(tmp_path):
    lib = str(tmp_path / "lib")
    make_skill(lib, "alpha", "parse pdf invoices and extract totals.")
    # candidate nearly identical to alpha -> overlap, exit 1
    r = run([DEDUP, "--skills-dir", lib, "--threshold", "0.4",
             "--desc", "parse pdf invoices and extract totals", "--name", "cand"])
    assert r.returncode == 1, "overlapping candidate must exit 1:\n%s" % r.stdout
    assert "OVERLAP" in r.stdout
    # distinct candidate -> exit 0
    r2 = run([DEDUP, "--skills-dir", lib, "--threshold", "0.4",
              "--desc", "render 3d terrain meshes from gis elevation rasters", "--name", "cand2"])
    assert r2.returncode == 0, "distinct candidate must exit 0:\n%s" % r2.stdout


# ===========================================================================
# 5. check_conformance, the three SKILL.md checks added 2026-07-31:
#    always-loaded size, shard pointers resolve, rules not version deltas
# ===========================================================================

def make_repo(root, skill="demo", body="body\n", repo_name=None):
    """The minimum a repo needs for the SKILL.md checks to run over it.

    The other conformance checks will FAIL on this skeleton, which is fine: every assertion below
    reads the specific row it is about, never the exit code alone.
    """
    d = root if repo_name is None else os.path.join(root, repo_name)
    write_utf8(os.path.join(d, "skills", skill, "SKILL.md"),
               "---\nname: %s\ndescription: x\n---\n%s" % (skill, body))
    return d


def row(stdout, needle):
    for ln in stdout.splitlines():
        if needle in ln:
            return ln.strip()
    return ""


def test_size_gate_warns_then_fails(tmp_path):
    small = make_repo(str(tmp_path / "a"), body="x" * 100)
    r = run([CONFORM, small])
    assert "[PASS] SKILL.md size" in r.stdout, row(r.stdout, "SKILL.md size")

    mid = make_repo(str(tmp_path / "b"), body="x" * 13000)
    r = run([CONFORM, mid])
    assert "[WARN] SKILL.md size" in r.stdout, row(r.stdout, "SKILL.md size")
    assert "over the 12000 warn line" in r.stdout

    big = make_repo(str(tmp_path / "c"), body="x" * 17000)
    r = run([CONFORM, big])
    assert "[FAIL] SKILL.md size" in r.stdout, row(r.stdout, "SKILL.md size")
    assert r.returncode == 1


def test_size_gate_ratchet_allows_shrink_and_blocks_growth(tmp_path):
    """A grandfathered file may shrink freely and may not grow by a character.

    The allowlist is keyed by "<repo dir>/<path>", so a temp repo named after a real entry
    exercises the real table rather than a test-only copy of it.
    """
    ceiling = 41959                                  # the 2026-07-31 measurement in the table
    under = make_repo(str(tmp_path / "shrunk"), skill="orchestrator",
                      repo_name="buy-me-a-car")
    head = len(open(os.path.join(under, "skills", "orchestrator", "SKILL.md"),
                    encoding="utf-8").read())
    write_utf8(os.path.join(under, "skills", "orchestrator", "SKILL.md"),
               "---\nname: orchestrator\ndescription: x\n---\n" + "x" * (ceiling - head + 4))
    r = run([CONFORM, under])
    assert "[WARN] SKILL.md size" in r.stdout, row(r.stdout, "SKILL.md size")
    assert "Ceiling 41959 set 2026-07-31" in r.stdout, r.stdout

    write_utf8(os.path.join(under, "skills", "orchestrator", "SKILL.md"),
               "---\nname: orchestrator\ndescription: x\n---\n" + "x" * (ceiling - head + 200))
    r = run([CONFORM, under])
    assert "[FAIL] SKILL.md size" in r.stdout, "a grandfathered file that GREW must fail:\n%s" % r.stdout
    assert "may shrink, never grow" in r.stdout


def test_grandfathered_entry_states_a_dated_target_and_never_passes_quietly(tmp_path):
    """The allowlist may not produce a silent pass, and the summary line must carry the debt.

    Regression for the honesty defect: the allowlist was seeded with exactly the files over the FAIL
    line, so the gate's first fleet run produced zero FAIL rows and a reader could conclude the fleet
    was within budget. Three things must be true on every run for a grandfathered file:
      it WARNs (never PASSes) while it is over the fail line,
      its row names the target and the date it is due, and
      the summary line states how many entries are carried and how many chars over target they are.
    """
    ceiling = 41959
    d = make_repo(str(tmp_path / "gf"), skill="orchestrator", repo_name="buy-me-a-car")
    head = len(open(os.path.join(d, "skills", "orchestrator", "SKILL.md"), encoding="utf-8").read())
    write_utf8(os.path.join(d, "skills", "orchestrator", "SKILL.md"),
               "---\nname: orchestrator\ndescription: x\n---\n" + "x" * (ceiling - head + 4))
    r = run([CONFORM, d])
    line = row(r.stdout, "SKILL.md size")
    assert "[WARN]" in line, line
    assert "GRANDFATHERED DEBT" in line, line
    assert "target due 2026-10-31" in line, line
    assert "over the 16000 target" in line, line
    # The summary line is what fleet_check.py lifts into the nightly digest.
    summary = row(r.stdout, "passed")
    assert "1 grandfathered" in summary, summary
    assert "chars over target" in summary, summary
    assert "GRANDFATHERED ALWAYS-LOADED DEBT" in r.stdout, r.stdout


def test_grandfathered_entry_fails_once_its_target_date_passes(tmp_path):
    """A grandfather clause with no expiry is a permanent exemption with a friendly name.

    Exercised in-process because the real allowlist's dates are all in the future by design; the
    thing under test is the expiry rule, not today's table.
    """
    sys.path.insert(0, _SCRIPTS)
    import importlib
    cc = importlib.import_module("check_conformance")
    importlib.reload(cc)
    key = "expired-repo/SKILL.md"
    cc.SKILL_MD_GRANDFATHERED[key] = (30000, "2020-01-01", 16000, "2020-06-30")
    d = str(tmp_path / "expired-repo")
    write_utf8(os.path.join(d, "SKILL.md"),
               "---\nname: x\ndescription: y\n---\n" + "x" * 25000)
    cc.results[:] = []
    cc.GRANDFATHER_DEBT.update(entries=0, over_target=0, overdue=0, rows=[])
    cc.check_skill_md_size(d)
    verdicts = [(nm, ok, detail) for nm, ok, detail in cc.results if "SKILL.md size" in nm]
    assert verdicts, cc.results
    _nm, ok, detail = verdicts[0]
    assert ok is False, "an overdue grandfather entry must FAIL, got %r (%s)" % (ok, detail)
    assert "EXPIRED" in detail, detail
    assert cc.GRANDFATHER_DEBT["overdue"] == 1, cc.GRANDFATHER_DEBT


def test_shard_pointer_resolves_against_skill_dir_then_repo_root(tmp_path):
    d = make_repo(str(tmp_path / "r"),
                  body="load `reference/shard.md` and `tools/thing.py`\n")
    write_utf8(os.path.join(d, "skills", "demo", "reference", "shard.md"), "s\n")
    write_utf8(os.path.join(d, "tools", "thing.py"), "t\n")
    r = run([CONFORM, d])
    # The count is in the row LABEL on purpose: details print only for non-PASS rows, so a check
    # that verified two pointers and one that found none would otherwise read identically.
    assert "[PASS] shard pointers resolve (2)" in r.stdout, row(r.stdout, "shard pointers")


def test_shard_pointer_dangling_in_an_existing_dir_fails(tmp_path):
    d = make_repo(str(tmp_path / "r"), body="load `reference/gone.md`\n")
    write_utf8(os.path.join(d, "skills", "demo", "reference", "other.md"), "o\n")
    r = run([CONFORM, d])
    assert "[FAIL] shard pointers resolve" in r.stdout, row(r.stdout, "shard pointers")
    assert "is right there, the file is not" in r.stdout


def test_shard_pointer_moved_file_fails(tmp_path):
    d = make_repo(str(tmp_path / "r"), body="load `domains/auction.md`\n")
    write_utf8(os.path.join(d, "skills", "demo", "reference", "domains", "auction.md"), "a\n")
    r = run([CONFORM, d])
    assert "[FAIL] shard pointers resolve" in r.stdout, row(r.stdout, "shard pointers")
    assert "moved?" in r.stdout


def test_shard_pointer_uncorroborated_only_warns(tmp_path):
    """A runtime output path, or a path in someone else's repo, must not go red.

    Verified on the fleet: of six unresolved pointers, the three with no corroboration were all
    correct by design (an archive file a run writes, a path in the user's private companion repo,
    a shard named in a sibling skill's repo).
    """
    d = make_repo(str(tmp_path / "r"), body="writes `archive/report.md` on each run\n")
    r = run([CONFORM, d])
    assert "[WARN] shard pointers resolve" in r.stdout, row(r.stdout, "shard pointers")
    assert "fine if they name a runtime output" in r.stdout


def test_shard_pointer_ignores_urls_and_placeholders(tmp_path):
    d = make_repo(str(tmp_path / "r"),
                  body="see [docs](https://example.com/a/b.md), `<slug>/thing.md`, `~/abs/x.md`\n")
    r = run([CONFORM, d])
    assert "[PASS] shard pointers resolve" in r.stdout, row(r.stdout, "shard pointers")


def test_retrofit_marker_warns_and_fences_are_exempt(tmp_path):
    d = make_repo(str(tmp_path / "r"), body="Phase 5 adds a modifier to the score.\n")
    r = run([CONFORM, d])
    assert "[WARN] instruction text states rules" in r.stdout, \
        row(r.stdout, "instruction text states rules")
    assert "retrofit marker" in r.stdout
    # The file count must be the number of files CARRYING a marker, not the number scanned. It was
    # handed the scanned count, so 8 markers in 5 files read as "8 markers across 10 files".
    assert "1 retrofit marker(s) in 1 of 1 file(s) scanned" in r.stdout, \
        row(r.stdout, "instruction text states rules")
    # exit code must be untouched by a WARN
    fenced = make_repo(str(tmp_path / "f"),
                       body="```text\nbad: Phase 5 adds a modifier to the score.\n```\n")
    r2 = run([CONFORM, fenced])
    assert "[PASS] instruction text states rules" in r2.stdout, \
        "an example inside a fence is not a retrofit:\n%s" % row(r2.stdout, "instruction text")


def test_warn_does_not_change_the_exit_code(tmp_path):
    """A WARN is printed, counted on the summary line, and never blocks."""
    d = make_repo(str(tmp_path / "r"), body="x" * 13000)
    r = run([CONFORM, d])
    warn_line = [ln for ln in r.stdout.splitlines() if "passed" in ln][-1]
    assert "WARN" in warn_line, "the summary line must carry the WARN count:\n%s" % warn_line
    # This skeleton repo fails plenty of OTHER checks, so assert on the reason rather than on rc:
    # no FAIL row may come from the three checks under test here.
    for ln in r.stdout.splitlines():
        if ln.strip().startswith("[FAIL]"):
            assert "SKILL.md size" not in ln and "shard pointers" not in ln \
                and "instruction text" not in ln, ln


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
