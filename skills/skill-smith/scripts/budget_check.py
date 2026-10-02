#!/usr/bin/env python3
"""Audit installed file-backed skill descriptions and current listing visibility.

The inventory includes user and active plugin tiers. Only the authored tier has the
per-skill description cap. A supplied listing measures missing descriptions by identity;
an incomplete listing or inventory remains explicitly unresolved.

--capacity supplies an explicit current capacity policy. Crossing that policy produces
FAIL when trimming can close the gap and BLOCKED when a removal decision is needed.
Those projections do not establish that any current description is absent: only the
listing does that. Observed omissions and authored-description violations produce FAIL.

Without --capacity, a complete listing supplies a current visible-character lower bound.
The historical capacity remains a labelled estimate when no complete listing is available;
it cannot override complete current coverage or create an enforced overflow by itself.
Fleet PASS additionally requires a complete current listing.
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


def frontmatter_end(lines):
    """Locate a column-zero closing fence, preserving fences inside YAML blocks."""
    return next(i for i in range(1, len(lines)) if lines[i].rstrip() == "---")


def parse_frontmatter(text):
    """Validate the whole YAML mapping before extracting string loader metadata.

    PyYAML is required. Missing names retain the inventory's directory fallback;
    missing, invalid or unavailable YAML never produces measurable descriptions.
    """
    if not isinstance(text, str):
        return None, None
    lines = text.lstrip("\ufeff").splitlines()
    if not lines or lines[0].rstrip() != "---":
        return None, None
    try:
        end = frontmatter_end(lines)
    except StopIteration:
        return None, None
    try:
        import yaml
    except ImportError:
        return None, None

    merge_key = object()

    class UniqueKeySafeLoader(yaml.SafeLoader):
        def construct_mapping(self, node, deep=False):
            if isinstance(node, yaml.MappingNode):
                seen = set()
                for key_node, _ in node.value:
                    key = (merge_key if key_node.tag == "tag:yaml.org,2002:merge"
                           else self.construct_object(key_node, deep=True))
                    if key in seen:
                        raise yaml.constructor.ConstructorError(
                            None, None, "duplicate mapping key", key_node.start_mark)
                    seen.add(key)
            # Check explicit keys before SafeLoader expands merge mappings, which
            # legitimately allow an explicit key to override an inherited value.
            return super().construct_mapping(node, deep=deep)

    try:
        fields = yaml.load("\n".join(lines[1:end]) + "\n", Loader=UniqueKeySafeLoader)
    except (yaml.YAMLError, TypeError, ValueError, RecursionError):
        return None, None
    if not isinstance(fields, dict):
        return None, None
    for key in ("name", "description"):
        if key in fields and (not isinstance(fields[key], str) or not fields[key].strip()):
            return None, None
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
        key = m.group(1).lower() if m else body.split()[0].rstrip(":").lower()
        has_description = bool(m)
        if key in out and out[key] != has_description:
            return None, "listing contains conflicting observations for %s" % key
        out[key] = has_description
    if not out:
        return None, "listing at %s contained no '- name' lines" % path
    return out, None


def listing_identity(row):
    """Canonical identity shared by measurements and finding fingerprints."""
    return ("%s:%s" % (row.owner, row.name) if row.owner else row.name).lower()


def measure_losses(rows, listing):
    """Return measured losses and unresolved identities, without borrowing a plugin's row.

    Prefer the full owner identity. Loader-style plugin prefixes and bare names are usable
    only when they identify exactly one installed row. Missing or ambiguous rows stay unseen.
    """
    aliases = {}
    row_keys = []
    for index, row in enumerate(rows):
        keys = [listing_identity(row)]
        if row.owner:
            keys += ["%s:%s" % (row.owner.split("@", 1)[0].lower(), row.name.lower()), row.name.lower()]
        keys = list(dict.fromkeys(keys))
        row_keys.append(keys)
        for key in keys:
            aliases.setdefault(key, set()).add(index)
    lost, unseen = [], []
    for index, row in enumerate(rows):
        observations = [listing[key] for key in row_keys[index]
                        if key in listing and aliases[key] == {index}]
        if not observations or len(set(observations)) != 1:
            unseen.append(row)
            continue
        if not observations[0]:
            lost.append(row)
    return lost, unseen


def main():
    ap = argparse.ArgumentParser(description="G3: does the installed library fit in the prompt?")
    ap.add_argument("--skills-dir", default=os.path.expanduser("~/.claude/skills"))
    ap.add_argument("--code-root", default=os.path.expanduser("~/CodesClaude"),
                    help="a skill resolving under here is OURS, and only OURS has a per-skill cap")
    ap.add_argument("--installed-plugins",
                    default=os.path.expanduser("~/.claude/plugins/installed_plugins.json"))
    ap.add_argument("--per-skill-max", type=int, default=PER_SKILL_MAX)
    ap.add_argument("--capacity", type=int, default=None,
                    help="explicit current capacity policy; the historical estimate is advisory")
    ap.add_argument("--extra", default="", help="a candidate description to hypothetically add")
    ap.add_argument("--plugins", action="store_true",
                    help="rank installed plugins by description cost, and price the removals")
    ap.add_argument("--listing", default="",
                    help="a captured live skill listing; turns predicted losses into measured ones")
    a = ap.parse_args()
    configured_capacity = a.capacity
    if configured_capacity is not None and configured_capacity <= 0:
        ap.error('--capacity must be positive')

    skills_dir = os.path.abspath(os.path.expanduser(a.skills_dir))
    code_root = os.path.abspath(os.path.expanduser(a.code_root))
    rows, problems = library_inventory(skills_dir, code_root,
                                       os.path.abspath(os.path.expanduser(a.installed_plugins)))

    per_tier = {t: [r for r in rows if r.tier == t] for t in (OURS, LOCAL, PLUGIN)}
    totals = {t: sum(r.cost for r in v) for t, v in per_tier.items()}
    extra = cost("candidate", a.extra) if a.extra else 0
    grand = sum(totals.values()) + extra
    user_rows = [r for r in rows if r.tier in (OURS, LOCAL)]

    # Current omissions require a listing; capacity arithmetic supplies a separate projection.
    measured = None
    listing_problem = None
    measurement = "not_supplied"
    if a.listing:
        measurement = "incomplete"
        listing, listing_problem = parse_listing(a.listing)
        if listing is not None:
            lost, unseen = measure_losses(rows, listing)
            measured = (lost, unseen, listing)
            problems.extend("listing identity absent or ambiguous: %s" % listing_identity(row) for row in unseen)
            if not unseen and not problems:
                measurement = "complete"
        if listing_problem:
            problems.append(listing_problem)

    if configured_capacity is not None:
        a.capacity = configured_capacity
        capacity_source = "configured"
    elif measurement == "complete":
        lost_rows = {id(row) for row in measured[0]}
        a.capacity = sum(row.cost for row in rows if id(row) not in lost_rows)
        capacity_source = "current_listing_lower_bound"
    else:
        a.capacity = OBSERVED_CAPACITY_CHARS
        capacity_source = "historical_estimate"
    estimated_overflow = max(0, grand - a.capacity)
    overflow = estimated_overflow if configured_capacity is not None else 0


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
    print("  capacity reference : %d chars (%s)" % (a.capacity, capacity_source))
    print("  OBSERVED capacity : %d chars, measured %s (historical estimate; advisory only)"
          % (OBSERVED_CAPACITY_CHARS, OBSERVED_CAPACITY_DATE))
    print("  Actual description omissions come only from the supplied current listing.")
    print("  library totals at : %d chars%s"
          % (grand, " (including the candidate)" if extra else ""))
    if problems:
        print("  Coverage incomplete: all costs and plans below cover the measured subtotal only.")

    floor_lost = min_skills_lost(rows, overflow)
    ranked = rank_plugins(rows)

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
        print("  Projected overflow above the explicit capacity policy: %d chars." % overflow)
        print("  The implied minimum removal is %d skill(s); current omissions are unmeasured."
              % floor_lost)
    elif problems:
        print("  The complete library cost and current visibility are UNKNOWN.")
    else:
        print("  Arithmetic estimate: historical capacity is advisory; live visibility is unmeasured.")
        if capacity_source == "historical_estimate" and estimated_overflow:
            print("  Under that historical estimate, AT LEAST %d skill(s) would need removal."
                  % min_skills_lost(rows, estimated_overflow))
            print("  Current omission is not derivable from disk; this projection does not assert a loss.")
        print("  Supply --listing to measure descriptions or --capacity to enforce a current policy.")

    if listing_problem:
        print("  NOTE: supplied listing is unusable; no current omission count was established:")
        print("        %s" % listing_problem)

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
    measured_lost = measured[0] if measured is not None else []
    findings.extend(("lost:%s" % listing_identity(row),
                     "%s has no description in the supplied listing" % listing_identity(row))
                    for row in measured_lost)
    long_ours = [(r.name, len(r.desc)) for r in per_tier[OURS] if len(r.desc) > a.per_skill_max]
    for n, ln in sorted(long_ours, key=lambda x: -x[1]):
        findings.append(("cap:%s" % n,
                         "%s: description is %d chars, over the %d per-skill cap"
                         % (n, ln, a.per_skill_max)))
    if overflow > 0:
        findings.append(("overflow",
                         "the library declares %d chars against explicit capacity %d; "
                         "the policy projection exceeds that limit by %d chars. "
                         "Current description visibility is reported separately."
                         % (grand, a.capacity, overflow)))
        for key, c, n in ranked:
            # Fingerprinted so that installing or removing a plugin visibly changes the finding SET,
            # which is how the operator tells tonight's amber from last night's.
            findings.append(("plugin:%s" % key, None))

    if long_ours or trimmable or measured_lost:
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
        if measurement == "complete":
            print("  STATUS: OK (our tier clean; current listing has no observed description omissions)")
        elif configured_capacity is not None:
            ratio = grand / float(a.capacity)
            print("  STATUS: OK (our tier clean; configured capacity use %.0f%%; visibility unmeasured)"
                  % (ratio * 100))
        else:
            print("  STATUS: OK (our tier clean; historical capacity is advisory; visibility unmeasured)")
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
        print("    selected capacity reference   %6d chars" % a.capacity)
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
        # Report capacity-policy overflow even when a separate cap violation or observed
        # description omission makes the overall run red.
        need = overflow - headroom
        picked, shed, enough = removal_plan(ranked, need)
        print("\n  NO LEVER MADE OF KEYSTROKES EXISTS. Trimming every user-tier description to the")
        print("  cap yields %d chars and %d are needed, so %d chars would still be over."
              % (headroom, overflow, need))
        print("  The remaining capacity-policy overflow requires a decision about what to stop having.")
        if state == BLOCKED:
            print("  This run is deliberately NOT red: red is for what can be closed tonight, and a")
            print("  colour that never changes stops being read.")
        else:
            if long_ours:
                print("  This run is red for %d authored description cap violation(s)." % len(long_ours))
            if measured_lost:
                print("  This run is red for %d observed description omission(s)." % len(measured_lost))
                print("  Restore visibility and measure a new complete listing to clear that finding.")
            print("  Capacity-policy overflow is separate and remains after description trimming.")
        print("  Priced, so the decision has numbers on it. Even after trimming, removing:")
        for key, c, n in picked:
            print("    %-44s frees %6d chars, %2d skills" % (key, c, n))
        if enough and problems:
            print("  would clear the measured overflow; unresolved inventory may still exceed capacity.")
        elif enough:
            print("  would put the library back inside the selected capacity reference. Fewer removals will")
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
            print("\n  To get under the selected capacity reference by plugin removal ALONE (%d chars):"
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
        elif configured_capacity is None:
            print("\n  No removal policy is enforced without --capacity.")
            print("  The capacity reference is advisory; current omissions require a listing.")
        else:
            print("\n  No removal is needed under the configured capacity policy.")

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
          "cap_over_ours=%d plugins=%d lever=%s fp=%s unresolved=%d measurement=%s "
          "capacity_source=%s estimated_overflow=%d projected_min_removals=%d"
          % (state, grand, a.capacity, overflow, headroom,
             len(measured_lost),
              len(long_ours), len(ranked), lever, fp, len(problems), measurement,
              capacity_source, estimated_overflow, floor_lost))
    return RC[state]


if __name__ == "__main__":
    sys.exit(main())
