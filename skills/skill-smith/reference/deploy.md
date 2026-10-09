# Deployment and publication

Deploy the source as the live skill and publish the repository only within the caller's existing
authorization. Substitute the correct paths and account names. Run the helper commands below
from `skills/skill-smith` in the source checkout.

## Local deployment

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

### Required remote metadata

Git push does not configure GitHub topics, description or homepage. After publication, set the
required metadata and verify it with G6b:

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
from `plugin.json` description, and homepage = `github.com/<owner>/<repo>`.
Override with `--owner/--repo/--description/--topics/--homepage` if needed.

## Post-deploy verification

- **G6 (local files):** `python scripts/check_conformance.py <path-to-repo>` passes.
- **G6b (GitHub remote metadata):** `python scripts/check_remote_conformance.py <path-to-repo>`
  passes. G6 validates local files; G6b queries live topics and description. Both are required.
  Missing `gh`, authentication or connectivity produces an explicit SKIP. Re-run the remote check
  when available before reporting deployment complete.
- Reload Claude / `/mcp` if the skill needs MCP servers; a freshly added skill is picked up on reload.
- Confirm the junction resolves (the live skill dir shows the source files).
