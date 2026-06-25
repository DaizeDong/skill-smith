# Step 8 — Deploy (local junction + GitHub publish)

Deploy the source as the live skill, then optionally publish the repo. Adjust paths and account
names to your own setup — nothing here is machine-specific.

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

- **Pitfall (Windows):** do NOT create the junction via git-bash `cmd //c mklink /J` — MSYS mangles
  `//c` into an interactive cmd that hangs. Use PowerShell `New-Item -ItemType Junction`.
- Before linking, list the repo's `skills/` to confirm the real skill name(s) — don't trust memory.
- If you keep a daily skill-sync script, add the repo to its list so it stays current.

## GitHub publish

```bash
gh repo create <gh-user>/<repo> --public
git remote add origin git@github.com:<gh-user>/<repo>.git   # or your own SSH host alias
git push -u origin main
# topics: base-9 + domain (Skill Repo Spec v1)
gh repo edit <gh-user>/<repo> --add-topic claude-code,claude-plugin,claude-skill,claude,ai,ai-agent,agent,llm,skill,<domain...>
```

If you maintain more than one GitHub identity, switch to the publishing account first
(`gh auth switch -u <account>`) and switch back afterward. Commit under the matching name/email.

## Post-deploy verification

- `python scripts/check_conformance.py <path-to-repo>` passes (Gate G6).
- Reload Claude / `/mcp` if the skill needs MCP servers; a freshly added skill is picked up on reload.
- Confirm the junction resolves (the live skill dir shows the source files).
