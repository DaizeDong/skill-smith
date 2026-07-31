# Step 5, The Acceptance Gate (P2: generation != usable)

This is skill-smith's core value and the answer to "tested-real". A skill is **accepted only if it
passes every gate below**. Any failure is an **explicit reject with the reason surfaced**, never a
silent ship (mirrors self-evolve's no-silent-degradation invariant). This is anti-self-deception: the
skill must *prove* it works, not *look* like it does.

| # | Gate | Rule (reject if not met) | How to check | Counters which risk |
|---|---|---|---|---|
| G1 | **Eval lift** | with-skill measurably beats a no-skill baseline on the brief's proof tasks | `agent-skills-eval` (with/without, judge-graded) or scenario-eval | 73% silently broken / faith-based |
| G2 | **Trigger rate** | held-out trigger rate >= threshold (default 0.9) | `run_loop.py` held-out score (see `triggering.md`) | ~50% non-activation |
| G3 | **Library prompt budget** | our tier: every description <= 180 chars, and none of ours past the truncation cutoff. The written rule says ~15k chars total; the cutoff OBSERVED on this machine 2026-07-31 is ~20k and four installed skills are already past it. Believe the observed number. | `python scripts/budget_check.py` | silent truncation -> invisible skills |
| G4 | **Dedup** | description overlap with existing skills below threshold | `python scripts/dedup_check.py` | wrong-skill selection / dilution |
| G5 | **Security** | generated scripts have no injection vectors / hardcoded secrets / destructive ops; audited before any run | manual + scan; never blind-run auto-generated code | prompt-injection / malware surface |
| G6 | **Spec conformance (local)** | local files pass Skill Repo Spec v1, including the three SKILL.md checks: size (warn 12,000 chars, fail 16,000), every relative path resolves, instruction text states rules rather than version deltas | `python scripts/check_conformance.py <repo>` | repo inconsistency; an always-loaded file nobody measured; a shard pointer the agent cannot open |
| G6b | **Remote conformance (GitHub)** | after publish: GitHub repo has base-9 + >=1 domain topic, non-empty description (homepage advisory) | `python scripts/check_remote_conformance.py <repo>` (deploy post-verify; SKIPs explicitly if no gh/offline) | topics=null / metadata never set by `git push` |
| G7 | **Focus** | one job, <=3 modules; not a multi-purpose blob | review against the Step-0 brief | exhaustive < focused (SkillsBench) |
| G8 | **Config standard** | IF config-bearing: passes the seven-element standard E1 to E7 (schema doc · env-var discovery mount · deterministic init · verify doctor · two configs hot-swappable · secrets gitignored Mode B · README Config section) | `python scripts/check_config_conformance.py <repo>` (auto-skips if not config-bearing) | "works on my machine" config / unconfigurable-by-others |

## How to run the gate

```bash
python scripts/check_conformance.py ~/CodesClaude/<name>         # G6  (local files)
python scripts/check_remote_conformance.py ~/CodesClaude/<name>  # G6b (GitHub remote, post-publish)
python scripts/check_config_conformance.py ~/CodesClaude/<name>  # G8 (config-bearing; auto-skips otherwise)
python scripts/budget_check.py                                   # G3 (whole library)
python scripts/dedup_check.py                                    # G4
# G1/G2 are not wired yet (agent-skills-eval / run_loop); run them manually and record the numbers.
```

`check_conformance.py` prints three statuses. `FAIL` means an edit fixes it and the exit code is 1.
`WARN` means the finding is real and no edit available today makes it clean, so it is printed and
counted on the summary line and never blocks. `PASS` rows carry their measurement in the row label
(`SKILL.md size (6376 chars)`, `shard pointers resolve (15)`) because a check that verified fifteen
pointers and one that found none would otherwise print the same line.

> **G6 and G6b are two layers, neither substitutes for the other.** G6 lints the committed files;
> G6b queries the live GitHub repo and proves the remote topics/description were actually set (a plain
> `git push` sets none). The topics=null incident happened because only G6 existed. After publishing,
> set remote metadata with `python scripts/set_repo_metadata.py <repo>` and then G6b must PASS; if
> `gh` is unavailable/offline, G6b SKIPs **explicitly** (stated, not silent), re-run before the
> deploy is considered done.

## Verdict semantics

- **accepted**, all gates pass. Proceed to self-evolve handoff (Step 6) for ongoing iteration.
- **reject (fixable)**, name the failing gate(s); loop back to the relevant step (e.g. G2 -> Step 4,
  G3 -> prune/merge the library, G7 -> split into a batch). Re-run the gate.
- **reject (drop)**, if G1 shows no lift after iteration, the skill is negative-value; do not ship it.
  An empty/negative result is a legitimate, honest outcome ("a skill that does not help is not a
  skill").

The gate is **library-aware**: G3/G4 evaluate the candidate *in the context of everything already
installed*, which is why a skill good in isolation can still be rejected (it would push the set over
budget). That is the point, see `batch.md`.
