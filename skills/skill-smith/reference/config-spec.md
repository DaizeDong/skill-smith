# Config-bearing skills — the standard skill-smith enforces

A **config-bearing skill** needs per-user / per-machine state (API keys, installed-tool registry,
endpoints, account prefs) that does NOT belong in the public skill repo. The moment a skill ships a
companion-config repo, a secrets template, a `registry.json`, or otherwise tells the user "set up your
own config", it is config-bearing — and it MUST satisfy the **seven-element standard** below.

This generalizes market-intel's `companion-config-spec` (v1) to *any* skill. market-intel is a
conforming instance, not the definition. The root-cause rule: **a config-bearing skill is only "done"
when a stranger can configure it right on the first try, two people independently generate the same
config shape, and either config can be hot-swapped in by pointing one env var at it.** Anything less
re-creates the "works on my machine" failure the standard exists to kill.

> Hard invariant (skill-smith I6): a config-bearing skill that fails any of E1–E7 is **rejected** at
> the acceptance gate (G8). Generation != configurable. See `acceptance-gate.md`.

---

## The seven elements (E1–E7)

| # | Element | One line |
|---|---|---|
| **E1** | **Schema documented** | Every config field (name/type/required/example) is written down in `CONFIG.md` or the README Config section — not folklore. |
| **E2** | **Discovery convention (mount)** | The skill finds its config by a documented env var `<SKILL>_CONFIG` first, then a default path fallback `~/.<skill>-config/`. The order is written down. |
| **E3** | **First-time success** | An `init` script stamps a spec-shaped config skeleton from a template; a `verify`/`doctor` script validates it and names exactly what is missing. |
| **E4** | **Same-spec generation** | init is **template-driven and deterministic** — anyone's init produces the identical structure, byte-for-byte. |
| **E5** | **Hot-swap between two configs** | A config is self-contained (no hardcoded absolute paths, no external coupling); switching is just pointing the env var at another dir. A programmatic swap test proves it. |
| **E6** | **Secrets isolation (Mode B)** | Secrets never enter git (gitignored), and the config repo is **separate** from the skill repo. |
| **E7** | **README Config section** | The README carries a `## Config` section: schema + mount + first-time steps + switch instructions, EN and CN. |

---

## E1 — Schema documented

Ship a `CONFIG.md` (preferred) **or** a README `## Config` section that documents, at minimum:

- the **discovery env var** name and the full fallback order (E2),
- the **`registry.json`** top-level shape (`schema_version` int, `skill` string, `tools[]`/`entries[]`),
- each per-entry / per-field **name · type · required? · example**,
- where **secrets** live (`secrets/<slug>.env`, gitignored) and the **Mode** in force (B by default),
- a worked example of one entry.

Reuse market-intel `companion-config-spec.md` §3/§4 as the field reference where a skill needs MCP-tool
entries; a simpler skill MAY define a smaller schema, but it MUST still document every field it reads.

## E2 — Discovery convention (the mount method)

The skill MUST resolve its config dir in this order, and MUST document it:

1. **`$<SKILL>_CONFIG`** env var (UPPER_SNAKE of the skill name + `_CONFIG`; highest priority).
2. **`$<SKILL>_CONFIG_DIR`** (accepted alias).
3. **`~/.<skill>-config/`** (dotfile-in-home; universal fallback).
4. **`~/.config/<skill>-config/`** (XDG-style; Linux/macOS).

Example: skill `acme-tools` → env var `ACME_TOOLS_CONFIG`, default `~/.acme-tools-config/`.
If none resolves, the skill MUST degrade gracefully (state it ran without config) — config is optional,
never a hard crash. (market-intel's `$MARKET_INTEL_CONFIG` is exactly this rule.)

## E3 — First-time success (init + verify)

Two scripts ship in the skill repo's `scripts/`:

- **`init_config.py`** — stamps a conformant, empty config skeleton at the target dir (default = the
  discovery path). Mode B by default. Auto-detects the skill name from the nearest `plugin.json` so the
  same generic script works for any skill.
- **`verify_config.py`** (the doctor) — resolves the config dir via the E2 discovery order, validates it
  against the spec, and prints **PASS/FAIL per check + the exact missing piece**. Exit 0 = ready, 1 = not.

"First try succeeds" = `clone → python scripts/init_config.py → fill secrets → python scripts/verify_config.py`
passes, with no hidden manual steps.

## E4 — Same-spec generation (deterministic)

init is **template-driven**: two people who run `init_config.py` for the same skill get a byte-identical
skeleton (registry.json shape, dir layout, `.gitignore`, secrets README). No interactive divergence, no
machine-specific content baked in. The gate proves this by running init twice into temp dirs and diffing.

## E5 — Hot-swap between two independent configs

A config dir is **self-contained**: it embeds no absolute paths, no `C:\`/`/home/`/`/Users/` literals, no
coupling to the machine it was made on. Switching configs is *only* repointing the env var:

```bash
export ACME_TOOLS_CONFIG=~/configs/work     # config A
export ACME_TOOLS_CONFIG=~/configs/personal # config B — same skill, different state
```

**Swap-test (programmatic, the acceptance criterion):** init two configs A and B → `verify_config.py`
passes on each → set the env var to A then to B and confirm `verify_config.py` resolves and validates the
one the env var points at, both times. If both legs pass, the skill is hot-swappable.

## E6 — Secrets isolation (Mode B)

- The **config repo is separate** from the (public) skill repo — never commit user secrets into the skill.
- **Mode B is the default**: `secrets/*` is gitignored; real values live out-of-band (cloud sync /
  encrypted drive). Mode A (committed secrets in a private repo) is allowed only for low-stakes
  data-API keys per market-intel spec §5.3, declared in `secrets/README.md`.
- Required `.gitignore` patterns (both the skill repo and the generated config repo):
  ```
  secrets/*
  !secrets/README.md
  !secrets/.gitkeep
  *.env
  !*.env.template
  !env.template
  claude.json
  .claude.json
  ```
- **Secrets never echo, never enter git, never appear in a report.** (skill-smith G5 + user invariant.)

## E7 — README Config section

`README.md` and `README_CN.md` MUST each carry a `## Config` / `## 配置` section containing, in order:

1. **Spec** — link to `CONFIG.md` (or inline the schema) and name the env var.
2. **Mount** — the E2 discovery order.
3. **First-time** — the `init → fill secrets → verify` three-liner.
4. **Switch** — how to hot-swap two configs via the env var.

A config-bearing skill whose README lacks this section is non-conformant even if every script works —
because the next person can't find any of it.

---

## Standard file list — what a config-bearing skill ships

In the **skill repo** (in addition to the Skill-Repo-Spec-v1 seven files):

```
<skill-repo>/
├── CONFIG.md                         # E1 schema + E2 mount + E5 switch (authoritative config doc)
├── .gitignore                        # E6 secrets patterns (defense in depth)
├── scripts/
│   ├── init_config.py                # E3/E4 deterministic skeleton stamper (generic, auto-detects skill)
│   └── verify_config.py              # E3 doctor: discovery + validate + name-the-missing
└── README.md / README_CN.md          # E7 `## Config` / `## 配置` section
```

The **generated config repo** (output of `init_config.py`, a *separate* private repo — E6):

```
<skill>-config/                       # discovered via $<SKILL>_CONFIG (E2)
├── registry.json                     # {"schema_version":1,"skill":"<skill>","tools":[]}
├── .gitignore                        # E6 secrets gate
├── tools/                            # per-entry config (claude.json.template + env.template per slug)
│   └── .gitkeep
└── secrets/                          # Mode B: gitignored
    ├── README.md                     # declares the active mode (B)
    └── .gitkeep
```

For MCP-tool-bearing skills, the per-`tools/<slug>/` template shape (`claude.json.template`,
`env.template`, placeholder syntax, BOM rule) is market-intel `companion-config-spec.md` §4 — reuse it
verbatim rather than re-deriving.

---

## How skill-smith makes this first-class

- **Scaffold (Step 3):** `python scripts/scaffold_skill.py <name> --with-config` emits the standard file
  list above (CONFIG.md, init/verify scripts, README Config section EN+CN, secrets `.gitignore`).
- **Gate (Step 5, G8):** `python scripts/check_config_conformance.py <repo>` auto-detects whether a repo
  is config-bearing and, if so, checks E1–E7 with PASS/FAIL per element (including a live deterministic
  + swap test by running the repo's own init/verify). A config-bearing repo failing any element is an
  explicit reject. A non-config-bearing repo is reported as such and skips the gate.
- **Deploy (Step 8):** publishing a config-bearing skill is incomplete until G8 passes and the README
  Config section is live, so the next person can mount their own config.
