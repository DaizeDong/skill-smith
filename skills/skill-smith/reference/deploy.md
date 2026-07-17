# Step 8, Deploy (local junction + GitHub publish)

Deploy the source as the live skill, then optionally publish the repo. Adjust paths and account
names to your own setup, nothing here is machine-specific.

## Local deploy = junction (source = deployment)

Keep the source in your skills-source directory and link it into `~/.claude/skills/<name>` so the
live skill and the source are the same files (edits flow both ways).

PowerShell (Windows):

```powershell
New-Item -ItemType Junction `
  -Path   "$HOME\.claude\skills\<name>" `
  -Target "<your-skills-source>\<repo>\skills\<name>"   # plugin-style: <repo>/skills/<name>
# root-skill style (SKILL.md at the repo root): target the repo root instead.
```

macOS / Linux:

```bash
ln -s <your-skills-source>/<repo>/skills/<name> ~/.claude/skills/<name>
```

- **Pitfall (Windows):** do NOT create the junction via git-bash `cmd //c mklink /J`, MSYS mangles
  `//c` into an interactive cmd that hangs. Use PowerShell `New-Item -ItemType Junction`.
- Before linking, list the repo's `skills/` to confirm the real skill name(s), don't trust memory.
- If you keep a daily skill-sync script, add the repo to its list so it stays current.

## GitHub publish

```bash
gh repo create <gh-user>/<repo> --public
git remote add origin git@github.com:<gh-user>/<repo>.git   # or your own SSH host alias
git push -u origin main
```

If you maintain more than one GitHub identity, switch to the publishing account first
(`gh auth switch -u <account>`) and switch back afterward. Commit under the matching name/email.

### MANDATORY remote metadata (the root-cause fix, `git push` does NOT set this)

A plain push leaves **topics = null and description/homepage unset** on GitHub. That is a Spec-v1
violation and was the cause of the topics=null incident. So the publish is **not finished** until you
set the remote metadata and verify it lives on GitHub, this is a required deploy step, not an
optional afterthought:

```bash
# (1) set remote topics (base-9 + domain) + description + homepage, from the repo's own plugin.json
python scripts/set_repo_metadata.py <path-to-repo>
#     --dry-run first to preview; idempotent (PUT replaces the whole topic set); re-runnable.

# (2) verify it actually landed on the remote (Gate G6b)
python scripts/check_remote_conformance.py <path-to-repo>     # must PASS
```

`set_repo_metadata.py` derives owner/repo from `plugin.json` homepage, the **base-9** topics
(`claude-code claude-plugin claude-skill claude ai ai-agent agent llm skill`) plus domain topics from
`plugin.json` keywords (dropping the trailing `skill` and any base-9 dups), the one-line description
from `plugin.json` description, and homepage = `github.com/<owner>/<repo>`, so you rarely hand-type
anything. Override with `--owner/--repo/--description/--topics/--homepage` if needed.

## Post-deploy verification

- **G6 (local files):** `python scripts/check_conformance.py <path-to-repo>` passes.
- **G6b (GitHub remote metadata):** `python scripts/check_remote_conformance.py <path-to-repo>`
  passes. **Both are required, they are two different layers.** G6 lints the files you committed;
  G6b queries the live repo and proves topics/description actually got set. The topics=null incident
  happened precisely because only G6 existed. If `gh` is missing/unauthenticated/offline, G6b prints
  an explicit SKIP (never a silent pass), re-run it once connectivity is back, before calling the
  deploy done.
- Reload Claude / `/mcp` if the skill needs MCP servers; a freshly added skill is picked up on reload.
- Confirm the junction resolves (the live skill dir shows the source files).
