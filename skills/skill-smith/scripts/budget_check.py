#!/usr/bin/env python3
"""Library system-prompt budget check (Acceptance Gate G3).

WHAT IS BEING PREVENTED, AND WHY IT IS INVISIBLE
    Every installed skill injects `name` + `description` into the system prompt. Past a budget the
    descriptions are SILENTLY DROPPED: the skill still exists, still has a description in its
    SKILL.md, and the agent simply never sees it, so it never fires. Nothing errors, nothing logs.
    The only way to notice is to count.

THE MEASUREMENT OF 2026-08-01, WHICH REPLACED THREE ROUNDS OF GUESSING
    An agent session was asked to write down, verbatim, the skill listing its own system prompt
    carried, and that listing was diffed against the descriptions present in every SKILL.md on
    disk. Result: of 163 file-backed skills, 79 appeared WITH their description and 84 appeared as
    a bare name. The 79 surviving lines came to 21,565 chars. The library declares 53,821. So about
    32,000 chars of description, and 84 skills, were not in the prompt at all.

    Three things that earlier versions of this file asserted were false, and each one mattered:

    1. "Truncation takes a contiguous tail in load order." It does not. In the listing,
       `vast-gpu` kept its description while the skills either side of it alphabetically lost
       theirs. A running-total prefix model cannot produce a non-contiguous set, so every VICTIM
       NAME this tool used to print was a guess dressed as a finding. It no longer guesses. Give it
       `--listing FILE` and it will MEASURE which skills lost their description; without that
       input it reports the arithmetic and says the names are not knowable from disk.

    2. "The plugin tier is budgeted elsewhere, so only the user tier truncates." Backwards. 81 of
       the 84 losses were plugin skills. Computing the running total over the user tier alone made
       the tool report zero plugin victims while the plugin tier was where nearly all the loss was.

    3. "Uninstalling a plugin moves the total by zero." That followed from (2) and is the exact
       opposite of the truth: the plugin tier is 33,040 of the 53,821 chars, and uninstalling the
       largest plugin frees more than four times what trimming every user description could.
       The previous version deleted the operator's only real lever on the strength of a model its
       own observation had already refuted.

WHAT THIS TOOL STILL CANNOT SEE, SAID OUT LOUD RATHER THAN COUNTED AS ZERO
    24 entries in that live listing have no SKILL.md anywhere on disk: built-in skills shipped
    inside the CLI, and skills registered dynamically by a running workflow. They consume the same
    budget and cannot be enumerated from the filesystem. Both sides of this tool's comparison are
    therefore restricted to FILE-BACKED skills, which keeps the arithmetic internally consistent
    and means the real pressure is somewhat worse than the number printed. The capacity figure is
    an OBSERVATION on a date, not a constant of the loader: if the CLI ships more built-ins
    tomorrow, the same library will fit less.

THE THREE TIERS
    ours    skills under the user skills dir that resolve, through a junction, into the fleet code
            root. Authored to this repo's Spec-v1, so the per-skill description cap applies.
    local   skills that sit as plain directories in the user skills dir. STILL THE OPERATOR'S.
            Nothing installs into the user skills dir automatically; plugins install under the
            plugin cache. A loose directory there was put there by hand.
    plugin  skills shipped by installed plugins, read from installed_plugins.json.

    The middle tier used to be called `other` and documented as "third-party, not ours to edit".
    That was an assumption dressed as a fact and it was false: every loose directory here is the
    operator's own. Naming a fixable thing unfixable is one of the two ways this row became
    permanent noise. The tier now records HOW it decided (junction target, or loose), so the claim
    is auditable instead of asserted.

WHY THE COLOUR SPLIT EXISTS, AND WHAT EACH COLOUR IS ALLOWED TO MEAN
    The other way the row became noise: it was RED for a condition no edit could clear. A colour
    that never changes stops being read, and then the next real failure is invisible too. So:

      FAIL / red      something closable tonight by editing a file: one of OUR descriptions over
                      the per-skill cap, or an overflow small enough that trimming user-tier
                      descriptions to the cap would clear it. A lever exists, so the run names it.
      BLOCKED / amber the library is over capacity and trimming cannot close the gap. Real, a
                      genuine capability loss, stated in full on every run WITH the arithmetic and
                      the plugin ranking. Not red, because the remaining move is a DECISION about
                      what to stop having, not a defect somebody forgot to fix.
      OK / green      under capacity, nothing of ours over the cap.

    The lever is COMPUTED, never assumed. That is the whole difference between this and the version
    that decided in advance that the middle tier was somebody else's problem.

    BLOCKED must never be reachable by editing text, or it becomes a place to hide failures. It is
    entered only when trim headroom is arithmetically smaller than the overflow, which the run
    prints both sides of.

WHY THE FIX FOR AMBER IS A RANKING AND NOT AN INSTRUCTION
    "Uninstall a plugin" is not an action, it is a shrug. `--plugins` ranks every installed plugin
    by the chars of description it contributes and the number of skills it brings, then computes
    the smallest set of removals that gets the library back under the observed capacity. That turns
    the amber row into a decision with numbers attached, which the operator can take or decline.
    Declining is a legitimate answer; not being told the price is not.

WHY installed_plugins.json AND NOT A GLOB
    The plugin cache keeps 2 to 4 stale versions per plugin plus scratch clones. A glob over the
    cache counts every one of them and reports a library several times larger than the one actually
    loaded. installed_plugins.json names the ACTIVE installPath per plugin, which is the only place
    that answer exists. Entries whose installPath is missing from disk are printed as unresolvable,
    never skipped in silence.

Usage:
  python budget_check.py [--skills-dir ~/.claude/skills] [--code-root ~/CodesClaude]
                         [--extra "candidate description to test-add"]
                         [--plugins]          rank installed plugins by description cost
                         [--listing FILE]     a captured live skill listing, to MEASURE the losses
Stdlib only. Token estimate = chars / 4 (rough).
Exit codes: 0 OK, 1 FAIL (a lever exists), 2 nothing to measure, 3 BLOCKED (real, no lever).
"""
import argparse
import hashlib
import json
import os
import re
import stat
import sys

# The documented rule, kept because it is what the written doctrine says.
DOCUMENTED_MAX_CHARS = 15000
# What the listing was OBSERVED to carry, measured by diffing a live listing against disk. See the
# module docstring. Restricted to file-backed skills, because that is the only population both
# sides of the comparison can enumerate.
OBSERVED_CAPACITY_CHARS = 21565
OBSERVED_CAPACITY_DATE = "2026-08-01"
OBSERVED_KEPT = 79
OBSERVED_LOST = 84
OBSERVED_MEASURED = OBSERVED_KEPT + OBSERVED_LOST
# One skill's description. Long descriptions are the fleet's own contribution to the overflow, and
# unlike the library total this is fixable by the operator in one edit.
PER_SKILL_MAX = 180
WARN_RATIO = 0.8

OURS, LOCAL, PLUGIN = "ours", "local", "plugin"
# The three verdict states. BLOCKED exists so that "real, and no edit closes it" has somewhere to
# live other than the FAIL bucket, where it would sit forever and bleach the colour out of every
# other finding.
OK, FAIL, BLOCKED = "OK", "FAIL", "BLOCKED"
RC = {OK: 0, FAIL: 1, BLOCKED: 3}


def parse_frontmatter(text):
    """Return (name, description) from a SKILL.md frontmatter block."""
    text = text.lstrip("﻿")  # tolerate a UTF-8 BOM (common from Windows editors)
    if not text.startswith("---"):
        return None, None
    end = text.find("\n---", 3)
    if end == -1:
        return None, None
    block = text[3:end]
    name = desc = None
    lines = block.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^name:\s*(.*)$", line)
        if m:
            name = m.group(1).strip().strip('"\'')
        m = re.match(r"^description:\s*(.*)$", line)
        if m:
            desc = m.group(1).strip().strip('"\'')
            # join folded/continuation lines (indented, no top-level key)
            j = i + 1
            while j < len(lines) and (lines[j].startswith((" ", "\t"))
                                      and not re.match(r"^\s*\w[\w-]*:\s", lines[j])):
                desc += " " + lines[j].strip()
                j += 1
            i = j
            continue
        i += 1
    return name, desc


def read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def link_target(path):
    """The junction/symlink target of path, or None. os.path.islink() misses NTFS junctions."""
    try:
        st = os.lstat(path)
    except OSError:
        return None
    is_link = os.path.islink(path) or bool(
        getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    if not is_link:
        return None
    try:
        t = os.readlink(path)
    except OSError:
        return ""
    for pre in ("\\\\?\\", "\\??\\"):
        if t.startswith(pre):
            t = t[len(pre):]
    return t


def cost(name, desc):
    """What one skill costs the listing.

    Modelled on the shape the listing actually takes, one "- name: description" line per skill.
    """
    return len("- %s: %s\n" % (name, desc))


class Row(object):
    """One measurable skill. `owner` is the plugin key for plugin rows, None otherwise."""

    __slots__ = ("tier", "name", "desc", "path", "owner")

    def __init__(self, tier, name, desc, path, owner=None):
        self.tier, self.name, self.desc, self.path, self.owner = tier, name, desc, path, owner

    @property
    def cost(self):
        return cost(self.name, self.desc)


def user_tier_rows(skills_dir, code_root):
    """Every skill in the user skills dir, tiered by where the directory actually resolves.

    Depth 1 only. The depth-2 glob a predecessor used matched a plugin-shaped layout that does not
    occur under this directory and would double-count a repo shipping several skills.

    OURS vs LOCAL is a statement about WHERE THE FILE LIVES and nothing more. It used to be read as
    a statement about who wrote it, which is how "loose directory" silently became "third party,
    cannot be fixed". Both tiers sit inside a directory the operator maintains by hand.
    """
    rows = []
    if not os.path.isdir(skills_dir):
        return rows
    code_root = os.path.normcase(os.path.abspath(code_root))
    for entry in sorted(os.listdir(skills_dir)):
        d = os.path.join(skills_dir, entry)
        p = os.path.join(d, "SKILL.md")
        if not os.path.isfile(p):
            continue
        tgt = link_target(d)
        resolved = os.path.normcase(os.path.abspath(tgt if tgt else d))
        tier = OURS if resolved.startswith(code_root + os.sep) else LOCAL
        name, desc = parse_frontmatter(read(p) or "")
        if desc is None:
            continue
        rows.append(Row(tier, name or entry, desc, p))
    return rows


def plugin_tier_rows(installed_json):
    """One Row per skill of every ACTIVE plugin install, plus the unresolvable entries.

    Returns (rows, problems). Dedupe is by (plugin key, skill dir name): installed_plugins.json can
    carry more than one record for a plugin (different scopes) and the same skill must count once.
    """
    rows, problems = [], []
    raw = read(installed_json)
    if raw is None:
        return rows, ["installed_plugins.json not readable at %s" % installed_json]
    try:
        data = json.loads(raw)
    except ValueError as e:
        return rows, ["installed_plugins.json is not valid JSON: %s" % e]
    seen = set()
    for key, records in sorted((data.get("plugins") or {}).items()):
        if not isinstance(records, list):
            records = [records]
        resolved_any = False
        for rec in records:
            ip = (rec or {}).get("installPath") or ""
            if not ip or not os.path.isdir(ip):
                continue
            resolved_any = True
            sk = os.path.join(ip, "skills")
            if not os.path.isdir(sk):
                continue
            for entry in sorted(os.listdir(sk)):
                p = os.path.join(sk, entry, "SKILL.md")
                if not os.path.isfile(p):
                    continue
                dedupe = (key, entry.lower())
                if dedupe in seen:
                    continue
                seen.add(dedupe)
                name, desc = parse_frontmatter(read(p) or "")
                if desc is None:
                    continue
                rows.append(Row(PLUGIN, name or entry, desc, p, owner=key))
        if not resolved_any:
            # Say it out loud. A stale record whose install path is gone means the plugin's real
            # cost is unknown, and an unknown printed as zero is the same lie this file exists to
            # stop.
            problems.append("%s: no installPath on disk (%s)"
                            % (key, "; ".join((r or {}).get("installPath", "?") for r in records)))
    return rows, problems


def rank_plugins(rows):
    """[(plugin key, chars, skills)] sorted by chars descending. The amber row's lever."""
    agg = {}
    for r in rows:
        if r.tier != PLUGIN or not r.owner:
            continue
        c, n = agg.get(r.owner, (0, 0))
        agg[r.owner] = (c + r.cost, n + 1)
    return sorted(((k, c, n) for k, (c, n) in agg.items()), key=lambda x: (-x[1], x[0]))


def removal_plan(ranked, need):
    """Smallest prefix of the ranked plugins whose removal shreds `need` chars.

    Greedy largest-first, which for "fewest plugins removed" is optimal on a sorted list. Returns
    (picked, shed, enough). `enough` is False when removing EVERY plugin still leaves the library
    over capacity, which is a different answer and must not be printed as a plan that works.
    """
    picked, shed = [], 0
    for key, c, n in ranked:
        if shed >= need:
            break
        picked.append((key, c, n))
        shed += c
    return picked, shed, shed >= need


def recoverable(desc, cap):
    """Chars a description can give back by being trimmed to the cap. Trimming, never deleting."""
    return max(0, len(desc) - cap)


def trim_plan(rows, need, cap):
    """Greedy largest-first (name, tier, gives_back) covering `need`, plus the total available.

    Trimming only. Nothing is deleted, so no capability is lost by taking this option, which is why
    it is the lever that gets to be red: it costs the operator nothing but keystrokes.
    """
    pool = sorted(((recoverable(r.desc, cap), r.name, r.tier) for r in rows
                   if recoverable(r.desc, cap) > 0), reverse=True)
    picked, got = [], 0
    for gives, n, t in pool:
        if got >= need:
            break
        picked.append((n, t, gives))
        got += gives
    return picked, got, sum(x[0] for x in pool)


def min_skills_lost(rows, overflow):
    """Fewest skills that must lose their description for the rest to fit. A LOWER bound.

    Drops the most expensive descriptions first, which is the kindest possible arrangement. The
    loader is under no obligation to be kind: the 2026-08-01 listing lost 84 skills where this
    bound was far smaller. Printed as a floor, never as an estimate of the real count.
    """
    if overflow <= 0:
        return 0
    n = 0
    for c in sorted((r.cost for r in rows), reverse=True):
        if overflow <= 0:
            break
        overflow -= c
        n += 1
    return n


def parse_listing(path):
    """{skill name: bool has_description} from a captured live skill listing.

    Accepts the shape the listing actually takes, one "- name: description" or bare "- name" per
    line. This is the ONLY way this tool learns which skills really lost their description; every
    other route is inference, and inference is what put four wrong names in this report for a week.
    """
    raw = read(path)
    if raw is None:
        return None, "listing not readable at %s" % path
    out = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        body = line[2:].strip()
        if not body:
            continue
        # The separator is a colon followed by WHITESPACE, not any colon. A plugin skill is listed
        # as `plugin:skill: description`, and splitting on the first colon reads the plugin key as
        # the whole name and the skill name as part of the description. That mistake made this
        # function report 87 installed skills as absent from the listing, which read as a disagreement
        # between disk and capture rather than as a parser bug. Skill names never contain spaces.
        m = re.match(r"^(\S+?):\s+(\S.*)$", body)
        if m:
            out[m.group(1).lower()] = True
        else:
            out[body.split()[0].rstrip(":").lower()] = False
    if not out:
        return None, "listing at %s contained no '- name' lines" % path
    return out, None


def measure_losses(rows, listing):
    """(lost, unseen) by MEASUREMENT: rows described on disk but bare in the listing.

    A plugin skill appears in the listing as `plugin:skill`, so a row is matched on its own name
    and on any listing key whose trailing segment equals it. `unseen` are rows the listing does not
    mention at all, which means the capture and the disk disagree about what is installed.
    """
    tail = {}
    for k, v in listing.items():
        tail.setdefault(k.rpartition(":")[2], v)
    lost, unseen = [], []
    for r in rows:
        key = r.name.lower()
        if key in listing:
            has = listing[key]
        elif key in tail:
            has = tail[key]
        else:
            unseen.append(r)
            continue
        if not has:
            lost.append(r)
    return lost, unseen


def main():
    ap = argparse.ArgumentParser(description="G3: does the installed library fit in the prompt?")
    ap.add_argument("--skills-dir", default=os.path.expanduser("~/.claude/skills"))
    ap.add_argument("--code-root", default=os.path.expanduser("~/CodesClaude"),
                    help="a skill resolving under here is OURS, and only OURS has a per-skill cap")
    ap.add_argument("--installed-plugins",
                    default=os.path.expanduser("~/.claude/plugins/installed_plugins.json"))
    ap.add_argument("--per-skill-max", type=int, default=PER_SKILL_MAX)
    ap.add_argument("--capacity", type=int, default=OBSERVED_CAPACITY_CHARS,
                    help="observed chars of description the listing carried; see the docstring")
    ap.add_argument("--extra", default="", help="a candidate description to hypothetically add")
    ap.add_argument("--plugins", action="store_true",
                    help="rank installed plugins by description cost, and price the removals")
    ap.add_argument("--listing", default="",
                    help="a captured live skill listing; turns predicted losses into measured ones")
    a = ap.parse_args()

    skills_dir = os.path.abspath(os.path.expanduser(a.skills_dir))
    code_root = os.path.abspath(os.path.expanduser(a.code_root))
    rows = user_tier_rows(skills_dir, code_root)
    prows, problems = plugin_tier_rows(os.path.abspath(os.path.expanduser(a.installed_plugins)))
    rows += prows

    if not rows:
        print("budget_check: no skills found under %s and no plugin skills resolved" % skills_dir)
        return 2

    per_tier = {t: [r for r in rows if r.tier == t] for t in (OURS, LOCAL, PLUGIN)}
    totals = {t: sum(r.cost for r in v) for t, v in per_tier.items()}
    extra = cost("candidate", a.extra) if a.extra else 0
    grand = sum(totals.values()) + extra
    user_rows = [r for r in rows if r.tier in (OURS, LOCAL)]

    print("Skill metadata budget")
    print("  user skills dir : %s" % skills_dir)
    print("  fleet code root : %s   (a skill resolving under here is OURS;" % code_root)
    print("                    a plain directory in the skills dir is LOCAL, which is still the")
    print("                    operator's file, just not backed by a fleet repo)")
    print("-" * 78)
    print("  %-38s %6s %7s %6s" % ("skill", "tier", "desc", "cost"))
    for r in sorted(rows, key=lambda r: -r.cost):
        print("  %-38s %6s %7d %6d" % (r.name[:38], r.tier, len(r.desc), r.cost))
    print("-" * 78)
    for t in (OURS, LOCAL, PLUGIN):
        print("  tier %-6s %3d skills  %7d chars (~%d tokens)"
              % (t, len(per_tier[t]), totals[t], totals[t] / 4))
    print("  TOTAL        %3d skills  %7d chars (~%d tokens)"
          % (len(rows), sum(totals.values()), sum(totals.values()) / 4))
    if extra:
        print("  + candidate description: %d chars -> %d cost (library would total %d)"
              % (len(a.extra), extra, grand))

    print("-" * 78)
    print("  documented budget : %d chars (what the written rule says)" % DOCUMENTED_MAX_CHARS)
    print("  OBSERVED capacity : %d chars, measured %s by diffing a live skill listing against"
          % (a.capacity, OBSERVED_CAPACITY_DATE))
    print("                      disk: %d of %d file-backed skills kept their description, %d "
          "appeared" % (OBSERVED_KEPT, OBSERVED_MEASURED, OBSERVED_LOST))
    print("                      as a bare name. Capacity is an observation on a date, not a")
    print("                      constant: built-in skills share the same budget and cannot be")
    print("                      counted from disk, so the real pressure is worse than this.")
    print("  library totals at : %d chars%s"
          % (grand, " (including the candidate)" if extra else ""))

    overflow = max(0, grand - a.capacity)
    floor_lost = min_skills_lost(rows, overflow)
    ranked = rank_plugins(rows)

    # --- what is actually lost: measured if a listing was supplied, bounded if not ---------------
    measured = None
    listing_problem = None
    if a.listing:
        listing, listing_problem = parse_listing(a.listing)
        if listing is not None:
            lost, unseen = measure_losses(rows, listing)
            measured = (lost, unseen, listing)

    print()
    if measured is not None:
        lost, unseen, listing = measured
        print("  MEASURED against %s: %d of %d file-backed skills appear in the listing with NO"
              % (a.listing, len(lost), len(rows) - len(unseen)))
        print("  description, so the agent cannot see them:")
        for r in sorted(lost, key=lambda r: (r.tier, r.name)):
            print("    %-38s %-6s %s" % (r.name[:38], r.tier, r.owner or ""))
        if unseen:
            print("  %d skill(s) on disk are absent from the listing entirely (the capture and the"
                  % len(unseen))
            print("  filesystem disagree about what is installed): %s"
                  % ", ".join(sorted(r.name for r in unseen))[:400])
        extra_entries = len(listing) - (len(rows) - len(unseen))
        if extra_entries > 0:
            print("  %d listing entr(ies) have no SKILL.md on disk: built-in skills and skills"
                  % extra_entries)
            print("  registered by a running workflow. They consume the same budget and are NOT in")
            print("  any total above, which is why the pressure is worse than the arithmetic says.")
    elif overflow > 0:
        print("  AT LEAST %d of %d file-backed skills cannot carry a description, because %d chars"
              % (floor_lost, len(rows), overflow))
        print("  are declared beyond the observed capacity. That is a FLOOR, computed by dropping")
        print("  the most expensive descriptions first; the loader is under no obligation to choose")
        print("  the cheapest set, and on %s it lost %d. WHICH skills lose their description"
              % (OBSERVED_CAPACITY_DATE, OBSERVED_LOST))
        print("  is not derivable from disk: the observed loss was non-contiguous in load order and")
        print("  fell mostly on the plugin tier. Pass --listing FILE to MEASURE it instead.")
    else:
        print("  The library fits inside the observed capacity, so nothing is dropped.")

    if listing_problem:
        print("  NOTE: --listing was given but unusable, so losses below are the bound, not the")
        print("        measurement: %s" % listing_problem)

    if problems:
        print("\n  UNRESOLVABLE plugin records (cost unknown, NOT counted as zero):")
        for p in problems:
            print("    %s" % p)

    # --- verdict ---------------------------------------------------------------------------------
    # Two finding classes, and a third axis that decides the COLOUR rather than the finding:
    #   description WORDING over the per-skill cap -> OURS only. Ours is authored to Spec-v1; LOCAL
    #       and plugin skills predate it or belong to somebody else, and failing them for that would
    #       be a red nobody can ever clear.
    #   the LIBRARY over capacity -> a finding whoever owns the descriptions, because an invisible
    #       skill is a capability loss regardless of who wrote it.
    #   IS THERE A LEVER MADE OF KEYSTROKES? -> computed, never assumed. Trimming user-tier
    #       descriptions to the cap loses nothing, so if that alone clears the overflow the finding
    #       is red and closable tonight. If it does not, the only remaining move is deciding what to
    #       stop having, and that is amber.
    cuts, covered, headroom = trim_plan(user_rows, overflow, a.per_skill_max)
    trimmable = overflow > 0 and headroom >= overflow

    findings = []          # (stable key, message). The key is what gets fingerprinted.
    long_ours = [(r.name, len(r.desc)) for r in per_tier[OURS] if len(r.desc) > a.per_skill_max]
    for n, ln in sorted(long_ours, key=lambda x: -x[1]):
        findings.append(("cap:%s" % n,
                         "%s: description is %d chars, over the %d per-skill cap"
                         % (n, ln, a.per_skill_max)))
    if overflow > 0:
        findings.append(("overflow",
                         "the library declares %d chars of description and the listing was "
                         "observed to carry %d, so %d chars and at least %d skills are not in the "
                         "prompt at all" % (grand, a.capacity, overflow, floor_lost)))
        for key, c, n in ranked:
            # Fingerprinted so that installing or removing a plugin visibly changes the finding SET,
            # which is how the operator tells tonight's amber from last night's.
            findings.append(("plugin:%s" % key, None))

    if long_ours or trimmable:
        state = FAIL
    elif overflow > 0:
        state = BLOCKED
    else:
        state = OK

    print("-" * 78)
    non_ours_long = sum(1 for r in rows if r.tier != OURS and len(r.desc) > a.per_skill_max)
    if non_ours_long:
        print("  note: %d skill(s) outside the `ours` tier are over the %d-char per-skill cap."
              % (non_ours_long, a.per_skill_max))
        print("        The cap is a Spec-v1 authoring rule for skills this repo produces, so length")
        print("        alone never fails for them. The library TOTAL is a finding for every tier.")

    if state == OK:
        ratio = grand / float(a.capacity)
        print("  STATUS: OK (our tier clean, library inside the observed capacity at %.0f%%)%s"
              % (ratio * 100, " Close to the line." if ratio >= WARN_RATIO else ""))
    else:
        print("  STATUS: %s" % state)
        for _key, msg in findings:
            if msg:
                print("    - %s" % msg)

    if overflow > 0:
        print("\n  THE ARITHMETIC OF THE LEVER")
        print("    library declares    %6d chars" % grand)
        print("    observed capacity   %6d chars" % a.capacity)
        print("    OVERFLOW to remove  %6d chars" % overflow)
        print("    TRIM headroom       %6d chars  (every user-tier description above the %d-char"
              % (headroom, a.per_skill_max))
        print("                                cap, trimmed down to it. Trimming only, so no")
        print("                                skill and no capability is lost by taking it.)")

    if trimmable:
        print("\n  DO THIS: trim these %d description(s), all of them the operator's own files, to"
              % len(cuts))
        print("  the %d-char cap. Together they give back %d chars, which covers the %d needed:"
              % (a.per_skill_max, covered, overflow))
        for n, t, gives in cuts:
            print("    %-38s %-6s gives back %5d chars" % (n[:38], t, gives))
    elif overflow > 0:
        # Printed whenever the overflow has no keystroke lever, INCLUDING when the run is red for a
        # separate reason. An earlier shape made this an `elif state == BLOCKED`, so one over-cap
        # description of ours would flip the run to FAIL and silently swallow the far larger
        # condition underneath it. The colour is decided by the lever; the reporting is not.
        need = overflow - headroom
        picked, shed, enough = removal_plan(ranked, need)
        print("\n  NO LEVER MADE OF KEYSTROKES EXISTS. Trimming every user-tier description to the")
        print("  cap yields %d chars and %d are needed, so %d chars would still be over."
              % (headroom, overflow, need))
        print("  What remains is not a defect to fix, it is a DECISION about what to stop having.")
        if state == BLOCKED:
            print("  This run is deliberately NOT red: red is for what can be closed tonight, and a")
            print("  colour that never changes stops being read.")
        else:
            print("  This run is red for the cap violation(s) listed above, which ARE closable")
            print("  tonight. Closing them will not clear this: it is the larger, separate finding")
            print("  and it will still be here, amber, once the red is gone.")
        print("  Priced, so the decision has numbers on it. Even after trimming, removing:")
        for key, c, n in picked:
            print("    %-44s frees %6d chars, %2d skills" % (key, c, n))
        if enough:
            print("  would put the library back inside the observed capacity. Fewer removals will")
            print("  not: the list is largest-first, so it is already the shortest one that works.")
        else:
            print("  would still not be enough: removing EVERY plugin frees %d of the %d needed."
                  % (shed, need))
            print("  The user tier alone is over capacity, so skills must be removed, not just")
            print("  plugins. Run with --plugins for the full ranking.")
        print("  Run --plugins for the full ranking and what each plugin actually buys.")

    if a.plugins:
        print("\n" + "-" * 78)
        print("  INSTALLED PLUGINS BY DESCRIPTION COST (the amber row's only real lever)")
        print("  %-44s %7s %7s %9s" % ("plugin", "chars", "skills", "cumulative"))
        cum = 0
        for key, c, n in ranked:
            cum += c
            print("  %-44s %7d %7d %9d" % (key, c, n, cum))
        print("  %-44s %7d %7d" % ("user tier (ours + local, not a plugin)",
                                   totals[OURS] + totals[LOCAL], len(user_rows)))
        if overflow > 0:
            picked, shed, enough = removal_plan(ranked, overflow)
            print("\n  To get under the observed capacity by plugin removal ALONE (%d chars):"
                  % overflow)
            for key, c, n in picked:
                print("    remove %-40s frees %6d chars, %2d skills" % (key, c, n))
            if enough:
                print("    total: %d chars, %d skills, leaving the library at %d against a capacity"
                      % (shed, sum(p[2] for p in picked), grand - shed))
                print("    of %d." % a.capacity)
            else:
                print("    NOT ENOUGH. Removing every plugin frees %d of the %d needed, leaving %d"
                      % (shed, overflow, grand - shed))
                print("    against a capacity of %d. The user tier alone is over." % a.capacity)
        else:
            print("\n  No removal is needed: the library is inside the observed capacity.")

    # One machine-readable digest, printed unconditionally in every state including OK. The caller
    # reads this line and nothing else. `fp` fingerprints the finding KEYS, not the numbers, so it
    # is stable night to night and changes exactly when the finding SET changes: a new over-cap
    # description, a newly installed plugin, an overflow appearing or clearing. That is how the
    # operator answers "is tonight's colour new?" by eye. It is deliberately stateless; storing last
    # night's value would make this tool a producer of real run data, which under the data boundary
    # would have to live outside the repo, and that is a lot of machinery to avoid comparing 8
    # characters.
    fp = hashlib.sha1(("|".join([state] + sorted(k for k, _m in findings)))
                      .encode("utf-8")).hexdigest()[:8]
    lever = "n/a" if overflow <= 0 else ("trim" if trimmable else "decision")
    print("-" * 78)
    print("  BUDGET: %s total=%d capacity=%d overflow=%d trim_headroom=%d min_lost=%d "
          "cap_over_ours=%d plugins=%d lever=%s fp=%s"
          % (state, grand, a.capacity, overflow, headroom,
             len(measured[0]) if measured is not None else floor_lost,
             len(long_ours), len(ranked), lever, fp))
    return RC[state]


if __name__ == "__main__":
    sys.exit(main())
