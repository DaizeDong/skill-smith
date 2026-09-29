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
      UNKNOWN         an inventory record or skill could not be measured. Known failures still
                      retain FAIL/BLOCKED priority, with unresolved coverage reported separately.
      OK / green      complete inventory, under capacity, nothing of ours over the cap.

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
Exit codes: 0 OK, 1 FAIL (a lever exists), 2 UNKNOWN inventory, 3 BLOCKED (real, no lever).
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
# BLOCKED exists so that "real, and no edit closes it" has somewhere to
# live other than the FAIL bucket, where it would sit forever and bleach the colour out of every
# other finding.
OK, FAIL, UNKNOWN, BLOCKED = "OK", "FAIL", "UNKNOWN", "BLOCKED"
RC = {OK: 0, FAIL: 1, UNKNOWN: 2, BLOCKED: 3}


def parse_frontmatter(text):
    """Read scalar skill metadata; unsupported or malformed metadata remains unmeasurable.

    This stdlib parser accepts plain, quoted and block text. It does not interpret YAML
    collections, aliases or tags as descriptions. Missing names retain the directory fallback.
    """
    lines = text.lstrip("\ufeff").splitlines()
    if not lines or lines[0].strip() != "---":
        return None, None
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return None, None
    fields = {}
    i = 1
    while i < end:
        match = re.match(r"^(name|description):\s*(.*)$", lines[i])
        if not match:
            line = lines[i]
            if (line.strip() and not line.lstrip().startswith("#")
                    and not line.startswith((" ", "\t"))
                    and not re.match(r"^[\w-]+:\s*", line)):
                return None, None
            i += 1
            continue
        key, raw = match.groups()
        if key in fields:
            return None, None
        continuation = []
        i += 1
        while i < end and (not lines[i].strip() or lines[i].startswith((" ", "\t"))):
            continuation.append(lines[i].strip())
            i += 1
        raw = raw.strip()
        if re.fullmatch(r"[>|][+-]?", raw):
            value = " ".join(continuation).strip()
        else:
            raw = " ".join([raw, *continuation]).strip()
            if raw.startswith('"'):
                try:
                    value, consumed = json.JSONDecoder().raw_decode(raw)
                except ValueError:
                    return None, None
                if not isinstance(value, str) or (raw[consumed:].strip()
                                                 and not raw[consumed:].lstrip().startswith("#")):
                    return None, None
            elif raw.startswith("'"):
                quoted = re.fullmatch(r"'((?:[^']|'')*)'\s*(?:#.*)?", raw)
                if not quoted:
                    return None, None
                value = quoted.group(1).replace("''", "'")
            else:
                value = re.split(r"\s+#", raw, maxsplit=1)[0].strip()
                if (not value or value[0] in "[{&*!|>#" or value.lower() in
                        ("null", "~", "true", "false") or re.search(r":\s", value)
                        or value.startswith("- ") or re.fullmatch(
                            r"[+-]?(?:\d[\d_]*(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", value)):
                    return None, None
        if not value.strip():
            return None, None
        fields[key] = value
    return fields.get("name"), fields.get("description")


def read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeError):
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


def skill_directory_rows(skills_dir, tier_for, owner=None):
    """Measure each direct skill directory and retain every unresolved entry."""
    rows, problems = [], []
    label = "plugin %s" % owner if owner else "user"
    try:
        entries = sorted(os.listdir(skills_dir))
    except OSError as error:
        return rows, ["%s inventory not readable at %s: %s" % (label, skills_dir, error)]
    for entry in entries:
        directory = os.path.join(skills_dir, entry)
        try:
            if not stat.S_ISDIR(os.stat(directory).st_mode):
                continue  # README and other files beside the skill directories are not skills.
            path = os.path.join(directory, "SKILL.md")
            if not stat.S_ISREG(os.stat(path).st_mode):
                raise OSError("SKILL.md is not a regular file")
        except OSError as error:
            problems.append("%s skill %s not readable: %s" % (label, directory, error))
            continue
        raw = read(path)
        if raw is None:
            problems.append("%s skill not readable as UTF-8: %s" % (label, path))
            continue
        name, desc = parse_frontmatter(raw)
        if desc is None:
            problems.append("%s skill has missing or malformed metadata: %s" % (label, path))
            continue
        rows.append(Row(tier_for(directory), name or entry, desc, path, owner))
    return rows, problems


def user_tier_rows(skills_dir, code_root, problems=None):
    """Every skill in the user skills dir, tiered by where the directory actually resolves.

    Depth 1 only. The depth-2 glob a predecessor used matched a plugin-shaped layout that does not
    occur under this directory and would double-count a repo shipping several skills.

    OURS vs LOCAL is a statement about WHERE THE FILE LIVES and nothing more. It used to be read as
    a statement about who wrote it, which is how "loose directory" silently became "third party,
    cannot be fixed". Both tiers sit inside a directory the operator maintains by hand.
    """
    code_root = os.path.normcase(os.path.abspath(code_root))

    def tier_for(directory):
        resolved = os.path.normcase(os.path.realpath(directory))
        return OURS if resolved.startswith(code_root + os.sep) else LOCAL

    rows, unresolved = skill_directory_rows(skills_dir, tier_for)
    if problems is not None:
        problems.extend(unresolved)
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
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate object key: %s" % key)
            result[key] = value
        return result

    try:
        data = json.loads(raw, object_pairs_hook=unique_object)
    except ValueError as e:
        return rows, ["installed_plugins.json is not valid JSON: %s" % e]
    if not isinstance(data, dict) or not isinstance(data.get("plugins"), dict):
        return rows, ["installed_plugins.json must contain a plugins object"]
    measured_by_skill = {}
    for key, records in sorted(data["plugins"].items()):
        if not key.strip():
            problems.append("installed_plugins.json contains an empty plugin key")
            continue
        if isinstance(records, dict):
            records = [records]
        if not isinstance(records, list) or not records:
            problems.append("%s: expected nonempty install records" % key)
            continue
        for index, rec in enumerate(records):
            label = "%s record %d" % (key, index + 1)
            ip = rec.get("installPath") if isinstance(rec, dict) else None
            if not isinstance(ip, str) or not ip or "\0" in ip or not os.path.isabs(ip):
                problems.append("%s: installPath must be an absolute path" % label)
                continue
            try:
                entries = os.listdir(ip)
            except OSError as error:
                problems.append("%s: installPath not readable at %s: %s" % (label, ip, error))
                continue
            if not any(os.path.normcase(entry) == os.path.normcase("skills") for entry in entries):
                continue  # A readable plugin without a skills directory can ship only commands.
            measured, unresolved = skill_directory_rows(os.path.join(ip, "skills"), lambda _d: PLUGIN, key)
            problems.extend(unresolved)
            for row in measured:
                dedupe = (key, os.path.basename(os.path.dirname(row.path)).lower())
                if dedupe in measured_by_skill:
                    previous = measured_by_skill[dedupe]
                    if previous is not None and (previous.name, previous.desc) != (row.name, row.desc):
                        problems.append("%s skill %s: active scopes have conflicting metadata"
                                        % dedupe)
                        measured_by_skill[dedupe] = None
                    continue
                measured_by_skill[dedupe] = row
    return [row for row in measured_by_skill.values() if row is not None], problems


def library_inventory(skills_dir, code_root, installed_json):
    """The shared G3/G4 population: user skills plus active plugin installs, with coverage gaps."""
    problems = []
    rows = user_tier_rows(skills_dir, code_root, problems)
    plugins, unresolved = plugin_tier_rows(installed_json)
    return rows + plugins, problems + unresolved


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
    rows, problems = library_inventory(skills_dir, code_root,
                                       os.path.abspath(os.path.expanduser(a.installed_plugins)))

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
    if problems:
        print("  Coverage incomplete: all costs and plans below cover the measured subtotal only.")

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
    elif problems:
        print("  The measured subtotal is under capacity; the complete library cost is UNKNOWN.")
    else:
        print("  The library fits inside the observed capacity, so nothing is dropped.")

    if listing_problem:
        print("  NOTE: --listing was given but unusable, so losses below are the bound, not the")
        print("        measurement: %s" % listing_problem)

    if problems:
        print("\n  UNRESOLVABLE inventory records (cost unknown, NOT counted as zero):")
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
    findings.extend(("unresolved:%s" % problem, None) for problem in problems)
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
    elif problems:
        state = UNKNOWN
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
        if problems:
            print("    - %d unresolved inventory record(s); the complete library cost is unknown."
                  % len(problems))
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
        print("  the %d-char cap. Together they give back %d chars, which covers the measured %d needed:"
              % (a.per_skill_max, covered, overflow))
        if problems:
            print("  Unresolved inventory may require further changes; this is not a complete plan.")
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
        if enough and problems:
            print("  would clear the measured overflow; unresolved inventory may still exceed capacity.")
        elif enough:
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
            if enough and problems:
                print("    total: %d chars removed from the measured subtotal; full coverage is unresolved."
                      % shed)
            elif enough:
                print("    total: %d chars, %d skills, leaving the library at %d against a capacity"
                      % (shed, sum(p[2] for p in picked), grand - shed))
                print("    of %d." % a.capacity)
            else:
                print("    NOT ENOUGH. Removing every plugin frees %d of the %d needed, leaving %d"
                      % (shed, overflow, grand - shed))
                print("    against a capacity of %d. The user tier alone is over." % a.capacity)
        elif problems:
            print("\n  Removal needs are UNKNOWN until the inventory is complete.")
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
          "cap_over_ours=%d plugins=%d lever=%s fp=%s unresolved=%d"
          % (state, grand, a.capacity, overflow, headroom,
             len(measured[0]) if measured is not None else floor_lost,
              len(long_ours), len(ranked), lever, fp, len(problems)))
    return RC[state]


if __name__ == "__main__":
    sys.exit(main())
