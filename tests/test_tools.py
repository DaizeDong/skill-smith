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
    """A skill resolving under the code root is OURS; a loose directory is LOCAL.

    The middle tier is named `local`, not `other`, on purpose. Nothing installs into the user
    skills dir automatically, so a loose directory there was put there by hand and is the
    operator's to edit. It was called `other` and documented as third-party, which is how a
    perfectly fixable overflow came to be reported as somebody else's problem.
    """
    code_root = tmp_path / "code"
    lib = code_root / "lib"                       # inside the code root -> tier "ours"
    make_skill(str(lib), "mine", "short one.")
    outside = tmp_path / "outside"
    make_skill(str(outside), "loose", "short two.")
    r = run([BUDGET, "--skills-dir", str(lib), "--code-root", str(code_root),
             "--installed-plugins", empty_plugins(tmp_path)])
    assert "tier ours 1 skills" in squeeze(r.stdout), r.stdout
    assert "tier local 0 skills" in squeeze(r.stdout), r.stdout
    r2 = run([BUDGET, "--skills-dir", str(outside), "--code-root", str(code_root),
              "--installed-plugins", empty_plugins(tmp_path)])
    assert "tier ours 0 skills" in squeeze(r2.stdout), r2.stdout
    assert "tier local 1 skills" in squeeze(r2.stdout), r2.stdout


def test_budget_no_tier_is_described_as_unfixable(tmp_path):
    """The report must never tell the operator that a user-tier skill is not theirs to edit.

    Regression, 2026-08-01. The middle tier's report text read "not ours to edit". On the only
    machine this ever ran on, every skill in that tier was the operator's own and tracked in their
    own config repo, so the sentence was false and it was the sentence that made the row look
    permanently red. Wording that assigns blame to an absent third party is now a test failure.
    """
    lib = str(tmp_path / "lib")
    make_skill(lib, "fat", "x" * 400)
    r = run([BUDGET, "--skills-dir", lib, "--code-root", str(tmp_path / "elsewhere"),
             "--installed-plugins", empty_plugins(tmp_path)])
    for phrase in ("not ours to edit", "third-party", "third party"):
        assert phrase not in r.stdout, \
            "the report claims a user-tier skill belongs to someone else (%r):\n%s" % (phrase, r.stdout)


def test_budget_per_skill_cap_fails_only_for_ours(tmp_path):
    """The 180-char cap is a FAIL for our tier and a printed note for the rest.

    Not because the rest is unfixable, but because the cap is a Spec-v1 AUTHORING rule for skills
    this repo produces. Applying it retroactively to skills that predate the spec would turn dozens
    of rows red at once with no defect behind them, which is the same alarm-bleaching failure the
    verdict split exists to prevent.
    """
    code_root = tmp_path / "code"
    lib = code_root / "lib"
    make_skill(str(lib), "fat", "x" * 200)
    ours = run([BUDGET, "--skills-dir", str(lib), "--code-root", str(code_root),
                "--installed-plugins", empty_plugins(tmp_path)])
    assert ours.returncode == 1, "our own over-cap description must fail:\n%s" % ours.stdout
    assert "over the 180 per-skill cap" in ours.stdout
    assert "cap_over_ours=1" in ours.stdout, ours.stdout
    # Identical library, but now nothing resolves under the code root.
    loose = run([BUDGET, "--skills-dir", str(lib), "--code-root", str(tmp_path / "elsewhere"),
                 "--installed-plugins", empty_plugins(tmp_path)])
    assert loose.returncode == 0, "length alone outside our tier must not fail:\n%s" % loose.stdout
    assert "Spec-v1 authoring rule" in loose.stdout
    assert "cap_over_ours=0" in loose.stdout, loose.stdout


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


def test_budget_reports_both_the_documented_and_the_observed_number(tmp_path):
    """The documented constant and the observed capacity disagree; print both, believe the latter."""
    lib = str(tmp_path / "lib")
    for i in range(40):
        make_skill(lib, "skill%02d" % i, "y" * 700)      # ~28k chars, well over capacity
    r = run([BUDGET, "--skills-dir", lib, "--code-root", str(tmp_path / "nope"),
             "--installed-plugins", empty_plugins(tmp_path)])
    assert "documented budget : 15000 chars" in squeeze(r.stdout), r.stdout
    assert "OBSERVED capacity : 21565 chars, measured 2026-08-01" in squeeze(r.stdout), r.stdout


def test_budget_never_names_a_victim_it_did_not_measure(tmp_path):
    """Without --listing the tool must give a COUNT and a bound, and no names.

    Regression, 2026-08-01. The tool used to print four specific skills as truncated, derived from
    a running-total-in-load-order model. Checked against a live listing, the real loss was
    non-contiguous, 20 times larger, and fell mostly on a tier the tool reported as having zero
    victims. Named guesses in a findings list are indistinguishable from measurements to the reader,
    so the tool is no longer allowed to make them.
    """
    lib = str(tmp_path / "lib")
    for i in range(180):                              # ~29k chars, comfortably over capacity
        make_skill(lib, "skill%03d" % i, "y" * 150)
    r = run([BUDGET, "--skills-dir", lib, "--code-root", str(tmp_path / "nope"),
             "--installed-plugins", empty_plugins(tmp_path)])
    assert "AT LEAST" in r.stdout, r.stdout[-2000:]
    assert "is not derivable from disk" in r.stdout, r.stdout[-2000:]
    assert "min_lost=" in r.stdout, r.stdout[-2000:]
    # No individual skill may be accused of being invisible when nothing observed it. Everything
    # from the cutoff block onward is DIAGNOSIS, and diagnosis is exactly where a guessed name gets
    # mistaken for a measured one. The inventory table above it lists every skill by name and is
    # fine, because it claims nothing. Every description here is under the cap, so there is no trim
    # plan in this run and no legitimate reason for any skill name to appear below the line.
    diagnosis = r.stdout.split("documented budget")[-1]
    named = [i for i in range(180) if ("skill%03d" % i) in diagnosis]
    assert not named, \
        "the report names %d skill(s) as losing their description without having observed it: %s\n%s" \
        % (len(named), named[:5], diagnosis[:1500])


def test_budget_measures_losses_when_given_a_listing(tmp_path):
    """With --listing the names stop being a model and start being an observation."""
    lib = str(tmp_path / "lib")
    make_skill(lib, "seen", "a description that survived.")
    make_skill(lib, "lost", "a description that did not survive.")
    listing = tmp_path / "listing.txt"
    listing.write_text("- seen: a description that survived.\n- lost\n", encoding="utf-8")
    r = run([BUDGET, "--skills-dir", lib, "--code-root", str(tmp_path / "nope"),
             "--installed-plugins", empty_plugins(tmp_path), "--listing", str(listing)])
    assert "MEASURED against" in r.stdout, r.stdout
    assert "1 of 2 file-backed skills appear in the listing with NO" in squeeze(r.stdout), r.stdout
    assert "lost" in r.stdout.split("MEASURED against")[1], r.stdout


def test_budget_listing_parses_plugin_prefixed_names(tmp_path):
    """`plugin:skill: description` must not be read as a skill called `plugin`.

    Regression: partitioning on the FIRST colon made every plugin skill in the listing look absent
    from disk, which printed as "the capture and the filesystem disagree" over 87 skills instead of
    as the parser bug it was. The separator is a colon followed by whitespace.
    """
    cache = tmp_path / "cache" / "demo" / "1.0.0"
    make_skill(str(cache / "skills"), "widget", "does a thing.")
    inst = tmp_path / "installed_plugins.json"
    inst.write_text(json.dumps({"version": 2, "plugins": {
        "demo@market": [{"installPath": str(cache)}]}}), encoding="utf-8")
    lib = str(tmp_path / "lib")
    make_skill(lib, "solo", "a user skill.")
    listing = tmp_path / "listing.txt"
    listing.write_text("- solo: a user skill.\n- demo:widget\n", encoding="utf-8")
    r = run([BUDGET, "--skills-dir", lib, "--code-root", str(tmp_path / "nope"),
             "--installed-plugins", str(inst), "--listing", str(listing)])
    assert "absent from the listing entirely" not in r.stdout, \
        "a plugin-prefixed listing entry was not matched to its skill:\n%s" % r.stdout
    assert "widget" in r.stdout.split("MEASURED against")[1], r.stdout


def test_budget_ok_when_the_library_fits(tmp_path):
    """The companion assertion: overflow is what fails, not merely having more than one tier."""
    lib = str(tmp_path / "lib")
    for i in range(5):
        make_skill(lib, "skill%02d" % i, "y" * 150)
    r = run([BUDGET, "--skills-dir", lib, "--code-root", str(tmp_path / "nope"),
             "--installed-plugins", empty_plugins(tmp_path)])
    assert r.returncode == 0, r.stdout[-2000:]
    assert "The library fits inside the observed capacity" in r.stdout, r.stdout[-2000:]
    assert "BUDGET: OK" in r.stdout and "lever=n/a" in r.stdout, r.stdout[-2000:]


def test_budget_blocked_is_not_red_and_is_priced(tmp_path):
    """The core of the redesign: real, unfixable-by-editing, amber, and quoted a price.

    An overflow far larger than every trimmable char must exit 3, not 1. It must also NOT be quiet
    about it: the run states the arithmetic on both sides and ranks the plugin removals that would
    close it, because "uninstall a plugin" without a number is a shrug, not a lever.
    """
    cache = tmp_path / "cache" / "big" / "1.0.0"
    for i in range(60):
        make_skill(str(cache / "skills"), "plug%02d" % i, "z" * 600)   # ~36k chars of plugin
    inst = tmp_path / "installed_plugins.json"
    inst.write_text(json.dumps({"version": 2, "plugins": {
        "big@market": [{"installPath": str(cache)}]}}), encoding="utf-8")
    lib = str(tmp_path / "lib")
    make_skill(lib, "mine", "y" * 100)                                  # nothing to trim
    r = run([BUDGET, "--skills-dir", lib, "--code-root", str(tmp_path / "nope"),
             "--installed-plugins", str(inst)])
    assert r.returncode == 3, "an overflow no edit can clear must be BLOCKED, not FAIL:\n%s" \
        % r.stdout[-2500:]
    assert "BUDGET: BLOCKED" in r.stdout and "lever=decision" in r.stdout, r.stdout[-2500:]
    assert "deliberately NOT red" in r.stdout, r.stdout[-2500:]
    assert "big@market" in r.stdout.split("NO LEVER")[1], \
        "the amber row must name and price the removal, not just describe the condition:\n%s" \
        % r.stdout[-2500:]


def test_budget_trimmable_overflow_is_red_not_blocked(tmp_path):
    """BLOCKED must not be reachable while keystrokes would still close the gap.

    Otherwise amber becomes a place to park work. The lever is computed from the arithmetic on
    every run, never assumed from which tier the chars are in.
    """
    lib = str(tmp_path / "lib")
    for i in range(24):
        make_skill(lib, "fat%02d" % i, "y" * 1000)     # ~24k, and ~20k of it is trimmable
    r = run([BUDGET, "--skills-dir", lib, "--code-root", str(tmp_path / "nope"),
             "--installed-plugins", empty_plugins(tmp_path)])
    assert r.returncode == 1, "trimming clears this, so it is red:\n%s" % r.stdout[-2000:]
    assert "lever=trim" in r.stdout, r.stdout[-2000:]
    assert "DO THIS: trim" in r.stdout, r.stdout[-2000:]


def test_budget_our_cap_violation_does_not_swallow_the_overflow(tmp_path):
    """Red for our own cap must not hide the larger amber condition underneath it.

    An earlier shape printed the removal pricing only in the BLOCKED branch, so a single over-cap
    description of ours would flip the state to FAIL and the 30,000-char overflow would vanish from
    the report entirely. The colour is decided by the lever; the REPORTING is unconditional.
    """
    code_root = tmp_path / "code"
    lib = code_root / "lib"
    make_skill(str(lib), "ours-fat", "y" * 400)                       # over the 180 cap
    cache = tmp_path / "cache" / "big" / "1.0.0"
    for i in range(60):
        make_skill(str(cache / "skills"), "plug%02d" % i, "z" * 600)
    inst = tmp_path / "installed_plugins.json"
    inst.write_text(json.dumps({"version": 2, "plugins": {
        "big@market": [{"installPath": str(cache)}]}}), encoding="utf-8")
    r = run([BUDGET, "--skills-dir", str(lib), "--code-root", str(code_root),
             "--installed-plugins", str(inst)])
    assert r.returncode == 1, "our own over-cap description is red:\n%s" % r.stdout[-2500:]
    assert "cap_over_ours=1" in r.stdout, r.stdout[-2500:]
    assert "NO LEVER" in r.stdout, \
        "the overflow disappeared from the report because the run was red for another reason:\n%s" \
        % r.stdout[-2500:]
    assert "it will still be here, amber, once the red is gone" in r.stdout, r.stdout[-2500:]


def test_budget_plugin_ranking_is_ordered_and_priced(tmp_path):
    """--plugins is the amber row's lever, so it must rank and total, not merely list."""
    cache = tmp_path / "cache"
    make_skill(str(cache / "small" / "1.0" / "skills"), "s1", "a" * 100)
    for i in range(10):
        make_skill(str(cache / "large" / "1.0" / "skills"), "l%d" % i, "b" * 400)
    inst = tmp_path / "installed_plugins.json"
    inst.write_text(json.dumps({"version": 2, "plugins": {
        "small@market": [{"installPath": str(cache / "small" / "1.0")}],
        "large@market": [{"installPath": str(cache / "large" / "1.0")}],
    }}), encoding="utf-8")
    lib = str(tmp_path / "lib")
    make_skill(lib, "user-one", "a user skill.")
    r = run([BUDGET, "--skills-dir", lib, "--code-root", str(tmp_path / "nope"),
             "--installed-plugins", str(inst), "--plugins"])
    block = r.stdout.split("INSTALLED PLUGINS BY DESCRIPTION COST")[1]
    assert block.index("large@market") < block.index("small@market"), \
        "the ranking is not sorted by cost descending:\n%s" % block


def test_budget_fingerprint_moves_only_when_the_finding_set_moves(tmp_path):
    """The "is tonight's colour new?" answer. Same findings, same fp; new plugin, new fp."""
    def fp_of(out):
        return [t for t in out.split() if t.startswith("fp=")][0]
    cache = tmp_path / "cache"
    for i in range(60):
        make_skill(str(cache / "big" / "1.0" / "skills"), "p%02d" % i, "z" * 600)
    make_skill(str(cache / "extra" / "1.0" / "skills"), "e1", "z" * 600)
    one = tmp_path / "one.json"
    one.write_text(json.dumps({"version": 2, "plugins": {
        "big@market": [{"installPath": str(cache / "big" / "1.0")}]}}), encoding="utf-8")
    two = tmp_path / "two.json"
    two.write_text(json.dumps({"version": 2, "plugins": {
        "big@market": [{"installPath": str(cache / "big" / "1.0")}],
        "extra@market": [{"installPath": str(cache / "extra" / "1.0")}]}}), encoding="utf-8")
    lib = str(tmp_path / "lib")
    make_skill(lib, "mine", "y" * 100)
    a = run([BUDGET, "--skills-dir", lib, "--code-root", str(tmp_path / "nope"),
             "--installed-plugins", str(one)])
    b = run([BUDGET, "--skills-dir", lib, "--code-root", str(tmp_path / "nope"),
             "--installed-plugins", str(one)])
    cc = run([BUDGET, "--skills-dir", lib, "--code-root", str(tmp_path / "nope"),
              "--installed-plugins", str(two)])
    assert fp_of(a.stdout) == fp_of(b.stdout), "identical libraries fingerprinted differently"
    assert fp_of(a.stdout) != fp_of(cc.stdout), \
        "installing a plugin did not change the fingerprint, so a new condition reads as last "\
        "night's:\n%s\n%s" % (fp_of(a.stdout), fp_of(cc.stdout))


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
