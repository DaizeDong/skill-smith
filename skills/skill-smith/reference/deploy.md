# Step 8 — Deploy (junction + GitHub publish)

Reuse the maintainer's existing mechanism — see memories `reference_skill_sync_junctions` and
`user_github_identity`. Do NOT invent a new deploy path.

## Local deploy = PowerShell junction (source = deployment)

Source lives in `CodesSelf/<name>`; deploy to `~/.claude/skills/<name>` via a junction so source and
live are the same files.

```powershell
New-Item -ItemType Junction `
  -Path "C:\Users\<username>\.claude\skills\<name>" `
  -Target "C:\Users\<username>\CodesSelf\<name>\skills\<name>"     # plugin-style: <repo>/skills/<name>
# root-skill style (SKILL.md at repo root, like self-evolve): Target the repo root instead.
```

- **Pitfall (hard-won):** do NOT use git-bash `cmd //c mklink /J` — MSYS mangles `//c` into an
  interactive cmd that hangs. Use PowerShell `New-Item -ItemType Junction`.
- Before creating, `ls CodesSelf/<name>/skills` to confirm the real skill list (don't trust memory).
- Add the repo to `the skill-sync script` `$repos` so `SyncClaudeSkills` (daily 09:00,
  `git pull --ff-only`, never push) keeps it synced.

## GitHub publish (DaizeDong account)

```bash
gh auth switch -u DaizeDong
gh repo create DaizeDong/<name> --public
git remote add origin git@daizedong:DaizeDong/<name>.git      # SSH host alias -> SSH key
git -c user.name="DaizeDong" -c user.email="DaizeDong@users.noreply.github.com" commit ...
git push -u origin main
# topics: base-9 + domain (Skill Repo Spec v1)
gh repo edit DaizeDong/<name> --add-topic claude-code,claude-plugin,claude-skill,claude,ai,ai-agent,agent,llm,skill,<domain...>
gh auth switch -u <account>                                  # restore default
```

## Post-deploy verification

- `python scripts/check_conformance.py ~/CodesSelf/<name>` passes (G6).
- Restart Claude / `/mcp` if the skill needs MCPs; a freshly added skill is picked up on reload.
- Confirm the junction resolves (`ls ~/.claude/skills/<name>` shows the live files).
