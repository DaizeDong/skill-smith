#!/usr/bin/env python3
"""Library system-prompt budget check (Acceptance Gate G3).

WHAT IS BEING PREVENTED, AND WHY IT IS INVISIBLE
    Every installed skill injects `name` + `description` into the system prompt. Past a budget the
    descriptions are SILENTLY TRUNCATED: the skill still exists, still has a description in its
    SKILL.md, and the agent simply never sees it, so it never fires. Nothing errors, nothing logs.
    The only way to notice is to count.

    This machine is past the cutoff RIGHT NOW. Measured 2026-07-31 against the skill listing this
    machine actually produced: `slides-polish` and `small-cap-deepdive` still carried their
    descriptions at a running total of 19,753 and 19,943 chars, and the next four in load order
    (`system-profile`, `training-check`, `vast-gpu`, `writing-systems-papers`) appeared with NO
    description at all, even though all four have one in their SKILL.md. So the real cutoff for this
    tier sits between 19,943 and 20,231 chars, which by the chars/4 estimate is 4,986 to 5,058
    tokens, i.e. almost certainly a 5,000 TOKEN budget rather than the char figure this file used to
    hardcode.

    The doctrine's documented constant is 15,000 chars. The OBSERVED cutoff is near 20,000. Both are
    printed. The observed one is what actually silences a skill; the documented one is what the
    written rule says, and where they disagree the code does not get to pick silently.

THE THREE TIERS, AND WHAT EACH ONE IS ALLOWED TO FAIL FOR
    ours    skills under the user skills dir that resolve into the fleet code root. The operator
            writes these descriptions, so an over-length description here is a one-edit fix and
            fails the run.
    other   third-party skills installed in the same user skills dir. They occupy the SAME budget.
            Their WORDING is not ours to edit, so a long third-party description never fails.
    plugin  skills shipped by installed plugins, read from installed_plugins.json. Same rule.

    FAIL ON THE CONDITION, NOT ON THE AUTHOR
    Those tiers used to gate the whole verdict, and the result was a check that could not see the
    only harm it exists to detect. On 2026-07-31 four installed skills were sitting past the
    observed truncation cutoff, invisible to the model, and this tool exited 1 for an entirely
    different reason: two of OUR descriptions were over the per-skill cap. Had those two been
    trimmed, the tool would have gone green with four skills still silently missing from the prompt.
    A skill the agent cannot see is a capability loss regardless of who wrote its description, so
    "a skill is currently past the truncation cutoff" is now a FAILURE whoever owns it.
    That does not hand the operator someone else's file to edit, because editing the third-party
    description was never the lever. The levers are: uninstall or remove a third-party skill from
    the user skills dir, or trim OURS, since the cutoff is a RUNNING TOTAL and every character cut
    anywhere ahead of a victim pulls it back under. The failure message says exactly that.

WHY installed_plugins.json AND NOT A GLOB
    The plugin cache keeps 2 to 4 stale versions per plugin (superpowers 6.1.1 + 6.2.0 + a sha,
    huggingface-skills 1.0.18 through 1.0.20 + a sha) plus scratch clones named temp_git_*. A glob
    over the cache counts every one of them and reports a library several times larger than the one
    that is actually loaded. installed_plugins.json names the ACTIVE installPath per plugin, which
    is the only place that answer exists. Entries whose installPath is missing from disk are printed
    as unresolvable, never skipped in silence.

Usage:
  python budget_check.py [--skills-dir ~/.claude/skills] [--code-root ~/CodesClaude]
                         [--extra "candidate description to test-add"]
Stdlib only. Exits 1 only on OUR tier's failures. Token estimate = chars / 4 (rough).
"""
import argparse
import json
import os
import re
import stat
import sys

# The documented rule, kept because it is what the written doctrine says.
DOCUMENTED_MAX_CHARS = 15000
# What the loader was OBSERVED to do on 2026-07-31 (see the module docstring). The interval is the
# honest form of the answer: the last surviving skill sat at 19,943 and the first truncated one
# would have taken the running total to 20,231. Anything inside that band is a coin flip.
OBSERVED_CUTOFF_LOW = 19943
OBSERVED_CUTOFF_HIGH = 20231
OBSERVED_CUTOFF_DATE = "2026-07-31"
# One skill's description. Long descriptions are the fleet's own contribution to the overflow, and
# unlike the tier total this is fixable by the operator in one edit.
PER_SKILL_MAX = 180
WARN_RATIO = 0.8

OURS, OTHER, PLUGIN = "ours", "other", "plugin"


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

    Modelled on the shape the listing actually takes, one "- name: description" line per skill. The
    old model added a flat 12, which is close enough to be indistinguishable in the total and wrong
    enough to move the cutoff comparison. Use the real line.
    """
    return len("- %s: %s\n" % (name, desc))


def user_tier_rows(skills_dir, code_root):
    """(tier, name, desc, path) for every skill in the user skills dir.

    Depth 1 only. The depth-2 glob the predecessor used matched a plugin-shaped layout that does not
    occur under this directory, and would double-count a repo that ships several skills.
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
        tier = OURS if resolved.startswith(code_root + os.sep) else OTHER
        name, desc = parse_frontmatter(read(p) or "")
        if desc is None:
            continue
        rows.append((tier, name or entry, desc, p))
    return rows


def plugin_tier_rows(installed_json):
    """(tier, name, desc, path) per skill of every ACTIVE plugin install, plus unresolvable entries.

    Returns (rows, problems). Dedupe is by (plugin key, skill dir name): installed_plugins.json can
    carry more than one record for a plugin (different scopes), and the same skill must be counted
    once.
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
                rows.append((PLUGIN, name or entry, desc, p))
        if not resolved_any:
            # Say it out loud. A stale record whose install path is gone means the plugin's real
            # cost is unknown, and an unknown printed as zero is the same lie this file exists to
            # stop.
            problems.append("%s: no installPath on disk (%s)"
                            % (key, "; ".join((r or {}).get("installPath", "?") for r in records)))
    return rows, problems


def main():
    ap = argparse.ArgumentParser(description="G3: does the installed library fit in the prompt?")
    ap.add_argument("--skills-dir", default=os.path.expanduser("~/.claude/skills"))
    ap.add_argument("--code-root", default=os.path.expanduser("~/CodesClaude"),
                    help="a skill resolving under here is OURS, and only OURS can fail")
    ap.add_argument("--installed-plugins",
                    default=os.path.expanduser("~/.claude/plugins/installed_plugins.json"))
    ap.add_argument("--per-skill-max", type=int, default=PER_SKILL_MAX)
    ap.add_argument("--extra", default="", help="a candidate description to hypothetically add")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    skills_dir = os.path.abspath(os.path.expanduser(a.skills_dir))
    code_root = os.path.abspath(os.path.expanduser(a.code_root))
    rows = user_tier_rows(skills_dir, code_root)
    prows, problems = plugin_tier_rows(os.path.abspath(os.path.expanduser(a.installed_plugins)))
    rows += prows

    if not rows:
        print("budget_check: no skills found under %s and no plugin skills resolved" % skills_dir)
        return 2

    per_tier = {t: [r for r in rows if r[0] == t] for t in (OURS, OTHER, PLUGIN)}
    totals = {t: sum(cost(n, d) for _t, n, d, _p in v) for t, v in per_tier.items()}
    grand = sum(totals.values())

    # The cutoff is computed over the USER tier in load order, because that is the tier whose
    # truncation was observed. Plugin skills are budgeted elsewhere by the loader (skills past the
    # user-tier cutoff still carried descriptions in the plugin block), so folding them into one
    # running total would name the wrong victims.
    user_rows = [r for r in rows if r[0] in (OURS, OTHER)]
    running, past_low, past_high = 0, [], []
    for tier, name, desc, _p in user_rows:
        running += cost(name, desc)
        if running > OBSERVED_CUTOFF_HIGH:
            past_high.append((tier, name, running))
        elif running > OBSERVED_CUTOFF_LOW:
            past_low.append((tier, name, running))

    print("Skill metadata budget")
    print("  user skills dir : %s" % skills_dir)
    print("  fleet code root : %s   (a skill resolving under here is OURS)" % code_root)
    print("-" * 78)
    print("  %-38s %6s %7s %6s" % ("skill", "tier", "desc", "cost"))
    for tier, name, desc, _p in sorted(rows, key=lambda r: -cost(r[1], r[2])):
        print("  %-38s %6s %7d %6d" % (name[:38], tier, len(desc), cost(name, desc)))
    print("-" * 78)
    for t in (OURS, OTHER, PLUGIN):
        print("  tier %-6s %3d skills  %7d chars (~%d tokens)"
              % (t, len(per_tier[t]), totals[t], totals[t] / 4))
    print("  TOTAL        %3d skills  %7d chars (~%d tokens)" % (len(rows), grand, grand / 4))

    extra = 0
    if a.extra:
        extra = cost("candidate", a.extra)
        print("  + candidate description: %d chars -> %d cost (user tier would end at %d)"
              % (len(a.extra), extra, running + extra))

    print("-" * 78)
    print("  documented budget : %d chars (what the written rule says)" % DOCUMENTED_MAX_CHARS)
    print("  OBSERVED cutoff   : between %d and %d chars, measured %s on this machine's own skill "
          "listing" % (OBSERVED_CUTOFF_LOW, OBSERVED_CUTOFF_HIGH, OBSERVED_CUTOFF_DATE))
    print("  user tier ends at : %d chars%s"
          % (running + extra, " (including the candidate)" if extra else ""))

    if past_high or past_low:
        print("\n  PAST THE CUTOFF (their descriptions are being dropped from the prompt; the agent"
              "\n  cannot see them, and nothing anywhere reports this):")
        for tier, name, at in past_high:
            print("    %-38s %-6s running total %d  (past the high bound: certainly truncated)"
                  % (name[:38], tier, at))
        for tier, name, at in past_low:
            print("    %-38s %-6s running total %d  (inside the uncertain band)"
                  % (name[:38], tier, at))
    else:
        print("\n  Nothing is past the observed cutoff.")

    # Load order is the listing order, which is what was observed. It is not a documented contract,
    # so say so rather than let a reader assume the victim list is authoritative.
    print("  (Victims are named in listing order, which is what was observed to be load order. The"
          "\n   order is not a documented contract; the COUNT past the cutoff is the solid part.)")

    if problems:
        print("\n  UNRESOLVABLE plugin records (cost unknown, NOT counted as zero):")
        for p in problems:
            print("    %s" % p)

    # --- verdict ---------------------------------------------------------------------------------
    # Two different failure classes with two different owners:
    #   description WORDING over the per-skill cap -> only OURS, because only ours is ours to edit.
    #   a skill PAST THE CUTOFF                    -> any tier, because an invisible skill is a
    #                                                 capability loss no matter who wrote it, and the
    #                                                 lever (uninstall, or trim ours) is the
    #                                                 operator's either way.
    fails = []
    long_ours = [(n, len(d)) for t, n, d, _p in per_tier[OURS] if len(d) > a.per_skill_max]
    for n, ln in sorted(long_ours, key=lambda x: -x[1]):
        fails.append("%s: description is %d chars, over the %d per-skill cap"
                     % (n, ln, a.per_skill_max))
    for band, group in (("past the high bound, certainly truncated", past_high),
                        ("inside the uncertain band", past_low)):
        for tier, n, at in group:
            fails.append("%s [%s]: %s at running total %d, so its description is dropped from the "
                         "prompt and the agent cannot see this skill at all" % (n, tier, band, at))

    print("-" * 78)
    other_long = sum(1 for t, _n, d, _p in rows if t != OURS and len(d) > a.per_skill_max)
    if other_long:
        print("  note: %d skill(s) outside our tier are over the %d-char per-skill cap. Their"
              % (other_long, a.per_skill_max))
        print("        WORDING is not ours to edit, so length alone never fails this check. Being"
              "\n        past the cutoff does fail it, for any tier: see below.")
    if fails:
        truncated = len(past_high) + len(past_low)
        print("  STATUS: FAIL")
        for f in fails:
            print("    - %s" % f)
        if truncated:
            print("  THE LEVER for a skill past the cutoff is NOT editing its description if it is")
            print("  not ours. The cutoff is a RUNNING TOTAL, so either lever works on any victim:")
            print("    1. uninstall a plugin, or remove a third-party skill from %s" % skills_dir)
            print("    2. trim OUR descriptions; every character cut ahead of a victim in load")
            print("       order pulls that victim back under the cutoff")
            print("  Doing neither leaves %d skill(s) installed, described, and invisible." % truncated)
        return 1
    ratio = running / float(OBSERVED_CUTOFF_LOW)
    if ratio >= WARN_RATIO:
        print("  STATUS: OK for our tier, but the user tier is at %.0f%% of the observed cutoff."
              % (ratio * 100))
    else:
        print("  STATUS: OK (our tier clean; user tier at %.0f%% of the observed cutoff)."
              % (ratio * 100))
    return 0


if __name__ == "__main__":
    sys.exit(main())
