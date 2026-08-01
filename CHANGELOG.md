# Changelog

All notable changes to this project are documented here (Keep a Changelog style).

## [Unreleased]
### Changed
- **`fleet_check.py` took over two minutes, and a report that takes over two minutes gets skipped.**
  Measured on one machine in one network window: **129,978 ms**, reproduced at **127,940 ms** and
  **127,610 ms**. Before this round's coverage work it was 62,977 ms, so the price of a 15% rise in
  rows evaluated had been a 2.1x slowdown. That is the same disease as a gate nobody reads, arriving
  by a different door: the run gets started, abandoned partway, and then not read.
  The cause was serial network I/O. The visibility oracle asks `gh` live per row, and `check_ci`
  resolved a default branch and listed runs per repo per workflow, roughly 110 blocking round trips
  end to end. `install.py --check` had the identical disease and the identical cure earlier in this
  same effort (185s to 8s), so the pattern was already proven here.
  Independent remote queries now fan out over a thread pool and answers are memoized per distinct
  slug: **29,328 ms**, a 4.4x speedup and **2.1x faster than the 62,977 ms pre-coverage baseline**.
  Offline runs went 66,785 ms to 18,128 ms. Deduplication is a real part of that and not only a
  speedup: `gh api repos/<slug>` was issued once by the workflow check to learn a default branch and
  again by the CI check to learn the same one, ~25 duplicate calls per run and a standing chance of
  the two checks disagreeing about which branch they were discussing. `gh auth token --user <acct>`
  was re-shelled once per account **per slug**; it is now once per account.
  **Nothing was bought by asking fewer questions,** which was the whole risk. Every row is still
  interrogated with the same query and the same arguments. Verified rather than asserted: run
  against a frozen copy of the visibility map, the report body is **byte-identical** to the serial
  version, all six per-section counts unchanged (16/17/9+6/1/6/57), 200 rows unchanged. Batching the
  ~57 `gh run list` calls into ~25 per-repo `actions/runs` calls was considered and **rejected**: it
  changes the answer, because a chatty workflow can push a quiet workflow's latest run off the page
  and turn a red guard into "no run on the default branch".
  Detection was then proved by breaking it, not by watching it pass. A repo with no guard workflows
  was declared `PUBLIC` in a doctored map: the concurrent run caught it (`exit 1`, `VERDICT RED`, the
  `FAIL` row naming both missing guards) and its report is byte-identical to the serial run's on the
  same input. Four sabotages of the new machinery were each caught by a new test: results keyed
  without the slug (cross-talk between repos), `as_completed` in place of `map` (shuffled rows and a
  misaligned zip, caught by four separate tests), a memo with no per-key lock, and the coverage
  clause demoted back to the end of the verdict line.
- **The verdict line printed a green total while skipping nearly half its rows.** `pass 104, fail 1,
  warn 7, skip 88` over 200 rows is 56% coverage, and the fraction WAS on the line, four
  pipe-separated fields to the right of the verdict word. That is not far enough forward to do any
  work: a reader scanning for the word after `VERDICT` gets `GREEN` and stops. It was the same defect
  the VERDICT line was introduced to fix, with the correction printed where nobody reached it.
  The coverage clause is now glued to the verdict word and shouts when the sample is partial:
  `VERDICT GREEN OVER 56% OF ROWS (112 of 200; 88 NOT EVALUATED)`. The `TOTAL` line carries the same
  clause under its counts, because bare counts are the other thing a reader rounds into an adjective.
  The machine-readable `verdict` key is unchanged, so callers that switch on the bare word still work.
- **The `budget` row was red by construction, and the two reasons it was red were both wrong.** It
  reported "4 skill(s) past the truncation cutoff" every night, named four specific skills, and
  described the tier they were in as third-party and unfixable. An operator who acted on that row
  could not close it, and a colour that never changes stops being read, which is how every gate in
  this codebase has historically come to be ignored.
  A live skill listing was captured from a running session and diffed, entry by entry, against every
  `SKILL.md` on disk. Of 163 file-backed skills, **79 carried a description into the prompt and 84
  appeared as a bare name**; the surviving lines totalled 21,565 chars against a declared library of
  53,821. That measurement retired three claims the tool was making:
  - **The victim names were a model, not an observation.** The model said truncation takes a
    contiguous tail in load order. The real loss was non-contiguous, 20 times larger than reported,
    and one of the four named skills had its description intact. Named guesses are indistinguishable
    from measurements to a reader, so the tool no longer makes them: without `--listing FILE` it
    prints a FLOOR on how many skills must lose their description and says plainly that the names
    are not derivable from disk. With a captured listing it MEASURES them.
  - **The tier was not the issue and was mislabelled anyway.** 81 of the 84 losses were plugin
    skills, while the running total was computed over the user tier alone, which is why the tool
    reported zero plugin victims over the tier holding nearly all the loss. Separately, the middle
    tier was renamed `other` -> `local` and its "not ours to edit" wording deleted: every loose
    directory in the skills dir is the operator's own.
  - **"Uninstalling a plugin moves the total by zero" was exactly backwards.** It is the largest
    lever available. The previous version printed that sentence while deleting the remedy.
  The verdict now follows the **lever**, computed each run and never assumed. Closable tonight by
  editing (our description over the cap, or an overflow trimming would cover) -> `FAIL`, red, cuts
  named. Not closable by any edit -> `BLOCKED`, exit 3, mapped to WARN, stated in full every run with
  the arithmetic on both sides and a **ranked, priced** list of which plugin removals would clear it.
  `--plugins` prints the full ranking. Amber is not a softer red: red is reserved for what keystrokes
  close, and BLOCKED is unreachable while any trim headroom would still cover the gap.
  Two adjacent fail-open paths were closed while in here. `check_budget` defaulted its count to 0
  when it could not find the machine-readable digest, so a budget_check whose output drifted produced
  a clean green row over an unmeasured library; a missing digest is now `UNKNOWN`. And the removal
  pricing was printed only inside the BLOCKED branch, so a single over-cap description of ours would
  flip the state to FAIL and the 32,000-char overflow would vanish from the report entirely; the
  colour is decided by the lever, the reporting is unconditional.
  The digest line is now `BUDGET: <state> total= capacity= overflow= trim_headroom= min_lost=
  cap_over_ours= plugins= lever= fp=`, and `fp` fingerprints the finding KEYS rather than the
  numbers, so it is stable night to night and moves exactly when the finding set moves. Same fp
  means tonight's colour is last night's colour, which is the question the operator actually has.
- **`fleet_check`'s `ci` check read two workflow names and called that "the CI is green".** It
  interrogated `GUARD_WORKFLOWS` (`pii-guard`, `dash-guard`) and nothing else, so every other
  workflow this fleet authors was invisible to the fleet report: a repo's own anti-regression
  `gate`, the `heartbeat` jobs, `test`, and the memory-health guard living in a PRIVATE repo, which
  the check never walked at all because it reused a repo set assembled to answer the PUBLIC guard
  PRESENCE question. On 2026-07-31 that printed "34 of 34 green" on a day when a real gate workflow
  was concluding success over a log whose last line read `RESULT: BLOCK (3 blocking issue(s))`. The
  workflow was not red at that moment, which is the point: nothing in the report could ever have
  said so if it had been.
  Rows are now CLASSIFIED rather than filtered. Every workflow file observed on every remote default
  branch gets a row tagged `guard` (mandated by policy) or `other` (anything else we wrote), and a
  red run FAILS the row in **both** tiers. `other` fails rather than warns because WARN in this tool
  means "no edit available today makes this clean", which is never true of a workflow in a repo we
  own: fix it or delete it. Downgrading non-guard redness to a warning would have rebuilt the same
  hiding place one layer down, behind a severity tier instead of a name filter. The single escape
  hatch is `CI_WARN_ONLY`, keyed on one named workflow of one named repo, carrying a reason that is
  printed on every run; it ships empty. An unobservable listing stays `UNKNOWN` and a repo with no
  workflows at all is still NAMED (`WARN` when public, `SKIP` when it is a private companion repo
  where CI is not mandated), because disappearing from the report is the failure being fixed.
  Coverage went from 34 guard rows to 42 evaluated rows plus 8 named skips.
- **`fleet_check`'s `databoundary` check asked the wrong question, and the wrong question condemned
  the right answer.** It asserted "the resolved real-run data dir is not inside a git worktree".
  That implements "must not reach a public repo" as "must not be in git", and those are different
  predicates. Real-run output LIVES IN the private companion repo, versioned: that is what the
  doctrine says and what the operator confirmed on 2026-07-31. The old predicate failed
  `market-intel` for keeping its ledger exactly there, an agent then moved the live ledger out to a
  loose unversioned directory to turn the row green, and all the while `daily-hotspots` kept a
  51-entry tracked ledger in ITS private companion repo and nothing objected, because the check
  could not see it at all. Two contradictory shapes in one fleet, endorsed inconsistently.
  The predicate is now the one that matches the harm: **PUBLIC fails, UNKNOWN fails closed** (the
  same treatment the PII gate gives an unknown remote), and **PRIVATE passes and the row names the
  repo**, so a reader can tell "the control examined this and approved it" from "the control
  skipped it". A dir outside every worktree still passes, and the row says out loud that it is
  unversioned. Visibility is resolved from live `gh` (see the next entry, which had to undo the
  map-first order this one shipped with), using a borrowed token per child process rather than
  `gh auth switch`, because this tool is read-only and a checker that mutates machine state to
  answer its own question is a checker whose second run tests something different from its first.
  Proven, not asserted: a throwaway fleet root was built with a fake skill pointed in turn at a
  PUBLIC companion, a PRIVATE one, one absent from the map, and one with no origin at all. FAIL,
  PASS, FAIL, FAIL. The online path was exercised separately against a real public repo missing
  from the map and correctly reported PUBLIC via `gh`.
- **`tools/datadir.py` now follows the same pointer the skills follow**, which is what made the
  check blind in the first place. Several companion repos are pinned with `$<SKILL>_CONFIG` outside
  the dotfile path; the resolver knew only the dotfile path, answered `None`, and downstream that
  is indistinguishable from "this skill has no data". `daily-hotspots` was reported "not
  initialized" for months over a ledger that grew every day. It also refuses a data dir inside the
  skill's own repo, a check deliberately narrow enough to need no map, no `gh` and no network so it
  still works on a stranger's fresh clone.
- **`tools/test_datadir.py` is new and ships fleet-wide**, run by the `pii-guard` workflow. The
  resolver is the pipe every byte of real-run output travels down, and no downstream scanner can
  see a leak that has nothing to smell.

### Fixed
- **The data-boundary control could be defeated by one stale line of JSON, and the file it trusted
  had nothing refreshing it.** The visibility oracle read `~/.pii-guard/visibility.json` FIRST and
  asked `gh` only on a miss, so a cached answer outvoted GitHub unconditionally. Poisoning a copy of
  the map with `{"daizedong/skill-smith": "PRIVATE"}` -- a genuinely PUBLIC repo -- made the check
  print `PASS ... [PRIVATE per visibility map]` over a data dir sitting in a public repo. The map
  had last been written on 2026-07-30 and nothing on the machine rewrites it, so a repo flipped from
  private to PUBLIC on GitHub -- precisely the event this control exists to survive -- would have
  read as PRIVATE indefinitely.
  Three fixes were on the table and the trade was made deliberately. A TTL alone is cheapest and
  does not close it: a freshly written entry is inside any window, so the poisoned copy still
  passes. Scheduling a refresh narrows the drift but leaves a window, and puts correctness back on
  "remember to run the script", which is the design `visibility_of.py` already learned not to trust.
  So the ORDER was inverted: `gh` is asked live, and the map is consulted only when `gh` cannot
  answer. The cost, accepted knowingly, is one `gh repo view` per DISTINCT slug the check actually
  reaches -- on this fleet that is 2 calls, not the 119 keys in the map, because only initialized
  data dirs inside a worktree ever ask. The offline fallback is bounded so the property holds with
  no network at all: the map may vote only while it is younger than 7 days, measured from a
  `_refreshed` stamp `refresh_visibility.py` now writes into it, and an unstamped map, a stamp in
  the future, or an expired one all behave as UNKNOWN, which already fails closed. When `gh` and the
  map disagree the live answer wins and the row says the map is STALE, because the disagreement is
  itself the finding.
  Proven the way the hole was found, against real repos and real GitHub: the poisoned map now FAILS
  and names the map as stale; the same map offline with a fresh stamp still PASSES; the same map
  offline with a 30-day-old stamp, and the same map with no stamp at all, both FAIL closed; a
  genuinely PRIVATE repo visible to only one of the two identities still PASSES via the borrowed
  token; and a reverse-poisoned map claiming a private repo is PUBLIC is overruled the same way.
- **The CI check reported a topic branch's run as the default branch's status.** The query was
  `gh run list -w <wf> --limit 1`, the newest run on ANY ref, while the sentence it printed -- "the
  guard CI is green" -- is a claim about the branch the world clones. On 2026-07-31, 2 of its 34
  green rows were runs from `feat/login-handoff-and-depth-gate` on `shopping-aggregator`, reported
  as if they described `main`. That was survivable only by luck: on 2026-07-22 `daily-hotspots` had
  a GREEN `pii-guard` run on a topic branch while `master`'s own newest `pii-guard` run was a
  FAILURE. It now filters on the repo's default branch, resolved once per repo, and prints which ref
  the evidence came from. **"No run on the default branch" is UNKNOWN**, not a silent fallback to
  whatever run exists: a workflow that has only ever fired on topic branches has said nothing yet
  about the branch being asked about.
  Proven against real GitHub history rather than a fixture, by running both versions of the check
  with the clock pinned to the moment in question: at `2026-07-22T06:55Z` on `daily-hotspots`
  `pii-guard`, before = **PASS**, after = **FAIL** naming `master`'s failing run; at
  `2026-06-01T08:40Z` on `market-intel` `gate`, whose first run ever was on `refresh/2026-06-01`,
  before = **PASS**, after = **UNKNOWN**.
- **Three of the new gates were reassuring the reader, which is the failure mode they exist to
  prevent.** All three were found by an independent pass over the run they had just shipped, and all
  three were green for the wrong reason.
  **`load_budget.py` measured nothing and called it a clean result.** It knew one repo shape,
  `skills/<name>/SKILL.md`. Two repos here keep their single SKILL.md at the ROOT, and those two
  hold two of the largest always-loaded files on the machine. In both it printed "no SKILL.md found,
  nothing to measure" and exited on a code its own docstring called "a state, not a failure". It now
  discovers both layouts (the same resolution `check_conformance.py` uses, deliberately identical),
  and measuring nothing exits **3** and says FAIL. Exit 2 is retired rather than redefined, so a
  caller that special-cased it as benign breaks loudly instead of quietly agreeing. Newly measured:
  `self-evolve` clean, `small-cap-deepdive` BLOCK at 5.82% duplicated prose, both previously unseen.
  **The size gate could not fail.** Its allowlist was seeded with exactly the five files over the
  fail line, so the first fleet run produced zero FAIL rows over 17% of the SKILL.md files and 40%
  of the always-loaded characters. The threshold was not the thing to move. Each entry now carries a
  dated shrink target (all to the 16,000 fail line, staged 2026-08-31 through 2026-10-31), WARNs
  every run with the arithmetic spelled out, is restated in a GRANDFATHERED ALWAYS-LOADED DEBT block,
  is carried on the summary line as `N grandfathered, M chars over target`, and **FAILS once its
  target date passes**. A grandfather clause with no expiry is a permanent exemption with a
  reassuring name.
  **`budget_check.py` could not see the actual harm.** Four installed skills were past the observed
  truncation cutoff and invisible to the model, and the tool exited 1 for an unrelated reason: two of
  OUR descriptions were long. Trimming those two would have turned it green with four skills still
  missing from the prompt, which is exactly what happened while this change was being written. Being
  invisible is a capability loss whoever authored the description, so the CONDITION now fails
  regardless of tier. The operator still never edits a third-party description; the message names the
  two levers that exist, uninstalling one or trimming ours, because the cutoff is a running total.
  Only the per-skill description CAP stays limited to our tier.
- **The retrofit lint said "across N file(s)" where N was the number of files SCANNED**, so 8 markers
  in 5 files read as "8 retrofit marker(s) across 10 file(s)". It now reports both counts.
- **`fleet_check.py` double-counted the truncated skills** because it derived the count by grepping
  `budget_check.py`'s stdout for the phrases that name a victim, and those phrases now also appear in
  the FAIL list: four truncated skills were reported as eight. `budget_check.py` prints one
  machine-readable `TRUNCATED: N` line, unconditionally including the zero, and `fleet_check.py`
  reads it.

### Added
- **Three SKILL.md checks in `check_conformance.py`, and a WARN status to carry them.** The gate
  asked whether files EXIST and never what the always-loaded file costs or whether it keeps its
  promises, so the fleet drifted with nothing to notice: a 41,959-char SKILL.md paid for on every
  invocation, three shard pointers naming files that are not on disk, and instruction text telling
  the reader which iteration added a rule instead of what the rule is.
  **Size:** warn above 12,000 chars, fail above 16,000. These were not chosen so the fleet passes:
  measured 2026-07-31, five of thirty SKILL.md files are over the fail line and four more are in the
  warn band. Those five are grandfathered BY NAME at their measured size, which they may shrink below
  and may not exceed by a character, so the allowlist can only ever get shorter and an already
  oversized file cannot quietly keep growing.
  **Shard pointers:** every relative path a SKILL.md names must resolve, against the skill directory
  first and the repo root second. It only FAILS when something corroborates that the file was meant
  to be here (its parent directory exists under the skill root, or its basename exists exactly once
  elsewhere in the repo); anything else WARNs, because a runtime output path and a path in the user's
  private companion repo are both legitimate. Measured before shipping: 225 pointers resolved, 3
  FAILs all hand-verified as genuinely dangling, 3 WARNs all verified correct by design.
  **Retrofit markers:** an iteration marker next to a rule verb ("Phase 5 adds ...") is a WARN. The
  first draft of this lint matched seven patterns and hit 261 times across 48 files, three of them
  ordinary English; it was cut to the retrofit syntax alone and measured at 8 hits in 5 files, all
  genuine, before shipping. Fenced code blocks are exempt so a doc can show the bad shape.
- **`scripts/budget_check.py` rewritten around what the loader actually does.** It globbed
  `~/.claude/skills` and compared the total to a hardcoded 15,000, which was wrong in three ways at
  once. It now reads the plugin tier from `installed_plugins.json` (the cache holds 2 to 4 stale
  versions per plugin plus scratch clones, so a glob over it finds 1,431 SKILL.md where 88 are
  actually loaded), reports our tier, other user skills and plugin skills separately, and fails only
  on OURS, since a third-party description over budget is real and is not the operator's to edit. It
  prints the documented 15,000-char budget AND the cutoff observed on this machine, which is not the
  same number: the last skill to keep its description sat at a running total of 19,943 chars and the
  next four appeared with no description at all despite having one in their SKILL.md. Those four are
  named in the output, because a truncation is invisible by construction. Adds a 180-char per-skill
  cap for our tier.
- **A VERDICT line, and an escalation for RED.** `fleet_check.py` ends every run with one line
  carrying a verdict and a coverage fraction, mirrored into the status JSON (`schema` 2) as
  `verdict`, `digest` and `coverage`. The nightly caller now quotes that line instead of composing
  its own adjective from the counts, which is how "pass 86, fail 0, skip 82" came to be reported as
  "all green" on the night before an audit found every one of these defects already present. A RED
  verdict additionally sends its own notification and makes the nightly job exit nonzero, the same
  escalation the config-drift check already used, so a red gate cannot be a line nobody reads.
- **`scripts/fleet_check.py`, the driver `check_conformance.py` never had.** The linter has been
  correct and complete for weeks and surfaced nothing, because nothing ever ran it: a gate with no
  driver does not exist. This fans it over every repo carrying `.claude-plugin/plugin.json` and adds
  the four assertions nothing on the machine performs, each with a real failure mode: every skill
  junction resolves (a repo move silently empties the agent's library and no error is raised
  anywhere), visibility PUBLIC implies a `pii-guard` CI workflow, a resolved real-run data directory
  is **not** sitting inside a git worktree, and the `pii-guard` CI that the whole doctrine calls
  "the authority" is actually green. That fourth one is the inverse of `data_boundary.py`: the
  boundary proves the repo holds no real-run output, this proves the output directory is not itself
  a repo, and in the 2026-07 leak both halves were needed and only one existed. There is **no
  `--fix` and never will be**: several of the directories it inspects hold live secrets and
  uncommitted state, so "auto-converge" is a data-loss button with a helpful label. It exits nonzero
  on any FAIL and writes a UTC-stamped status JSON, so a scheduled caller can verify the run
  HAPPENED (freshness) separately from whether it PASSED, which an exit code alone cannot express.
  Anything it cannot observe (gh missing, unauthenticated, rate limited, workflow never run) is
  reported UNKNOWN and never blocks.
- **`scripts/bump_version.py`, the missing half of the version rule.** `scaffold_skill.py` stamped
  the five version sites once at creation and `check_conformance.py` only read them, so every
  release was five hand edits in the right order across five files, with no feedback until someone
  ran the linter. Most repos ended up drifted, usually as a half-applied release (plugin.json and
  CHANGELOG moved, the README badges and ROADMAP did not). The bumper rewrites all five together,
  demotes the previous `## vX.Y.Z (current)` ROADMAP heading, and opens a dated CHANGELOG section
  that absorbs any `## [Unreleased]` body. Two refusals are the point of it: it **exits nonzero on
  an already-drifted repo** and prints the diff, because bumping over drift greens the linter while
  erasing which site was left behind; and it **never commits, tags or pushes**, because cutting a
  release is a human decision. A badge pre-release marker (`Roadmap-v0.2.2%20alpha-purple`)
  round-trips rather than being flattened.
- `scripts/version_sites.py`, one definition of where a version lives. The scaffolder, the linter
  and the bumper now share it, so a bump cannot stamp a shape the linter rejects.
- `tests/test_bump.py`, 17 tests covering the five sites moving together, the drift refusal writing
  nothing, Unreleased absorption, pre-release round-trip, and rollback leaving no half-bumped repo.

### Fixed
- **`fleet_check.py` certified two things it never actually checked.** All three failures were the
  same shape: a PASS printed by a code path that never observed the thing on the label.
  1. *The workflow check stat()ed the local clone.* `os.path.isfile(<repo>/.github/workflows/
     pii-guard.yml)` answers "is this file on my disk", and the claim on the label was "this PUBLIC
     repo is gated by CI". Those come apart the moment a workflow is committed but not pushed, and
     they had: `claude-codex-memory-sync` is PUBLIC, its remote default branch carries only
     `test.yml`, and it scored PASS for as long as the check existed. It now interrogates the REMOTE
     default branch over `gh`, falling back to `git ls-remote` plus a local `ls-tree` when the remote
     HEAD is already in the object store, and reports UNKNOWN (never PASS) when neither can answer.
     Still no `git fetch`: the tool does not write to repos.
  2. *The CI check asked about one workflow and reported on the category.* It queried `pii-guard`
     only, under a heading claiming the guard CI was green. On 2026-07-30 it printed a single
     confident PASS for `promotion-assistant` whose `dash-guard` had been failing since 2026-07-24.
     It now queries every guard workflow found on the remote and prints one row per repo and
     workflow, named, so a red guard cannot shelter behind a green sibling.
  3. *UNKNOWN was defined as never-failing, and was carrying findings.* That reasoning is correct for
     "gh is not installed" and wrong for "this public repo has no guard workflow at all", which is a
     real finding in an UNKNOWN costume. UNKNOWN now means exactly one thing, "this run could not
     OBSERVE the answer", and a definitive negative from a remote that did answer is a FAIL. Because
     UNKNOWN can no longer carry a finding, it is genuinely safe for it not to affect the exit code.
     Unobserved rows print under their own `UNOBSERVED` heading and land in the status JSON, so a
     fleet nobody could look at cannot be mistaken for a clean one.

  Same audit, same defect class, three more paths that could report success without testing their
  label: `in_git_worktree()` collapsed "git said no" and "git could not run" into one `False`, so a
  machine with no git on PATH cleared **every** data directory in the boundary check (proven: with
  the probe forced to fail, the old code returns PASS, the new one UNKNOWN); the junctions and CI
  checks could emit zero rows, which prints as `pass 0, fail 0` and reads like a clean sheet, so an
  empty or missing skills dir now says so; and `check_conformance` silently dropped repos with no
  `plugin.json` instead of listing them, which would have hidden a repo falling out of coverage.
  The first run after the fix moved the fleet from 1 failure to 3, all of them real.
- **`check_conformance.py` reported conforming repos as broken.** The version regex demanded a bare
  `Roadmap-vX.Y.Z-purple` badge, so a repo carrying a deliberate pre-release marker
  (`Roadmap-v0.2.2%20alpha-purple`, which is how shields.io encodes `v0.2.2 alpha`) read as having
  no version at all and failed the sync check while all five of its sites agreed. Same fault in the
  Languages badge check: an exact substring test meant a repo that also shipped Spanish
  (`Languages-EN%20%2F%20CN%20%2F%20ES-blue`) was marked as missing the badge, penalizing it for
  translating more. A linter that cries wolf gets muted, which is worse than no linter.
- **The scaffolded PII gate was 113 lines behind the canonical scanner**, so every repo skill-smith
  created was born with a downgraded backstop (no cross-repo token loading, no machine-path
  detector, no repo-slug self-exclusion). `assets/pii-guard/` is re-vendored from canonical:
  `pii_guard.py` +113 lines, `test_pii_guard.py` +110, `data_boundary.py` +1, `datadir.py` reworded.

## [0.1.3] - 2026-07-16
### Added
- **Dash gate (Spec v1 section 10) is now scaffolded into every new skill.** `scaffold_skill.py`
  vendors `tools/dash_guard.py` plus a `dash-guard` CI workflow (assets under `assets/dash-guard/`),
  so a new skill is born enforcing the house rule that published prose carries no en/em dash. The
  tool de-dashes Markdown and Python COMMENTS only, leaving every string literal (docstrings and data
  such as regexes or fixtures) untouched, so a functional literal is never corrupted; the ASCII hyphen
  is never touched. `check_conformance.py` now verifies the two files exist and that the tree is
  dash-clean. Runtime output compliance stays the renderer's job (normalize dashes in `_inline`).

## [0.1.2] - 2026-06-25
### Added
- **Remote conformance is now a first-class deploy step (Gate G6b).** Root-cause fix for the
  topics=null incident: `git push` sets no GitHub topics/description/homepage, and `check_conformance.py`
  (G6) only validates LOCAL files, so repos passed G6 yet shipped with `topics=null`, violating Skill
  Repo Spec v1.
- `scripts/set_repo_metadata.py`, idempotent setter for remote topics (base-9 + domain) + description
  + homepage via `gh api PUT .../topics` and `gh repo edit`. Defaults are derived from the repo's own
  `plugin.json` (owner/repo from homepage, domain topics from keywords minus the trailing `skill`/base-9
  dups, one-line description). `--dry-run` previews; PUT replaces the whole topic set so re-runs converge.
- `scripts/check_remote_conformance.py`, Gate **G6b**: queries the live GitHub repo and asserts the
  base-9 topics are all present, >=1 domain topic exists, and description is non-empty (homepage is
  advisory). Prints an explicit **SKIP** (never a silent pass) when `gh` is missing / unauthenticated /
  offline. Self-tested read-only: PASS on a conformant repo, FAIL (exit 1) on a non-conformant one.
- `reference/deploy.md` Step 8: setting remote metadata + passing G6b is now a MANDATORY publish
  finisher (was a one-line optional `gh repo edit --add-topic`). SKILL.md invariant 5 + workflow Step 8
  and `reference/acceptance-gate.md` add G6b as the remote-layer twin of G6, both layers required,
  neither substitutes for the other.

## [0.1.1] - 2026-06-25
### Added
- **Config-bearing skills are now first-class** (config-spec E1 to E7). A skill that needs a companion
  config (keys / installed-tool registry / endpoints) must be configurable by anyone on the first try,
  generate the identical config shape, and hot-swap between two configs via one env var.
- `reference/config-spec.md`, authoritative seven-element standard (schema doc · env-var discovery
  mount · deterministic init · verify doctor · hot-swap · secrets Mode B · README Config section),
  generalized from market-intel's companion-config-spec to any skill.
- `scripts/check_config_conformance.py`, Gate **G8**: auto-detects config-bearing repos and enforces
  E1 to E7 with a live deterministic-generation test + hot-swap test (runs the repo's own init/verify).
  Non-config-bearing repos are reported and skip the gate.
- `scaffold_skill.py --with-config`, emits the config-bearing standard: `CONFIG.md`, generic
  `scripts/init_config.py` + `verify_config.py` (auto-detect skill from plugin.json), README
  `## Config`/`## 配置` section (EN+CN), and a secrets `.gitignore` (Mode B).
- `assets/config/` templates (init/verify scripts, CONFIG.md, README sections, gitignores).
- SKILL.md invariant 6 + workflow Steps 3/5/8 now treat config-bearing as a first-class case;
  acceptance-gate G8 added; `tests/test_config.py` (A-tier signal for the new gate).

## [0.1.0] - 2026-06-25
### Added
- Initial framework release.
- Thin `skills/skill-smith/SKILL.md` orchestrator: research-first create workflow (Phase 0 delegates
  landscape + frontier-design recon to `market-intel`) through scaffold, trigger-optimize, acceptance
  gate, self-evolve handoff, batch, and deploy.
- `PHILOSOPHY.md` with 6 principles (research-first; generation != usable; thin delegation;
  library-budget is the batch constraint; focused beats exhaustive; dogfood).
- Reference shards: `research-first.md`, `scaffold.md`, `triggering.md`, `acceptance-gate.md`,
  `generators.md`, `iterate-handoff.md`, `deploy.md`, `batch.md`.
- Scripts: `scaffold_skill.py` (Spec-v1 repo generator), `check_conformance.py` (Spec-v1 linter),
  `budget_check.py` (library system-prompt token budget), `dedup_check.py` (cross-library description
  overlap).
- Skill Repo Spec v1 conformance for this repo (dogfood).
- A-tier pytest suite (`tests/`) verifying the create pipeline + each tool; scripts hardened for
  UTF-8 BOM tolerance and empty-name input (found via a self-evolve iteration).
- `trim_descriptions.py`, library description-budget remediation (scan -> review -> apply, with
  per-file backups and a dry-run), the concrete fix for an over-budget skill set (Gate G3).
