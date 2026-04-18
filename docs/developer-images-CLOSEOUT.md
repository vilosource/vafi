# Developer Images — Close-Out Summary

**Date:** 2026-04-17
**Status:** Phases 0–3 complete. Migration (Phase 4) pending user action.

This document tracks what was built under the developer-images design, what remains, and how to adopt the new images.

---

## What was produced

### Documentation (`docs/`)

| File | Purpose |
|------|---------|
| `developer-images-DESIGN.md` | Authoritative design: layered image tree, versioning, launcher model, alternatives considered. |
| `developer-images-RUMSFELD.md` | Rumsfeld matrix. All blocking Known Unknowns resolved. |
| `developer-images-S1-REPORT.md` | Harness install recipes for Claude, Pi, Gemini; coexistence verification; flag map. |
| `developer-images-CLOSEOUT.md` | This file. |

### Image source (`images/developer/`)

```
images/developer/
├── Dockerfile.base            # shared body (from vafi-base + devtools + mempalace + vf-harness)
├── Dockerfile.claude          # claude leaf (FROM ${REGISTRY}/vafi-developer-base:${BASE_TAG})
├── Dockerfile.pi              # pi leaf (includes pi-mcp-adapter install)
├── Dockerfile.gemini          # gemini leaf
├── vf-harness/
│   ├── init.sh                # generic dispatcher — reads $VF_HARNESS
│   ├── init-claude.sh         # claude-specific auth + config writer
│   ├── init-pi.sh             # pi-specific (multi-provider)
│   ├── init-gemini.sh         # gemini-specific (GEMINI_API_KEY + MCP registration)
│   ├── connect.sh             # interactive TTY entry — dispatches per harness
│   └── run.sh                 # non-interactive one-shot — dispatches per harness
├── pi-extras/
│   ├── APPEND_SYSTEM.md       # extracted from existing vafi-developer image
│   ├── entrypoint-pi-local.sh # (legacy ref — now replaced by vf-harness/init-pi.sh)
│   └── extensions/
│       └── mempalace-hooks.ts # pi mempalace extension
└── mempalace-extras/
    └── entrypoint-local.sh    # (legacy ref — from vafi-claude-mempalace)
```

### Build + test scripts (`scripts/`)

| Script | Purpose |
|--------|---------|
| `build-developer-images.sh` | Builds `vafi-developer-base:<date>` + per-harness leaves with pinned and floating tags. |
| `smoke-test-developer.sh`   | Per-leaf smoke test: CLI version, mempalace import, bind-mount RW, devtools present, harness dispatch. |

### Launcher fragments (user shell — NOT repo-managed)

| File | Purpose |
|------|---------|
| `~/.claude/vf-launchers.sh`             | Shared `_vafi_dev_run` helper + per-context launchers (`vfdev` / `ogcli` / `ogdr` / `pidev`). |
| `~/.claude/vf-launchers-context.sh.example` | Template for per-context secrets (MediaWiki, GitLab, z.ai, Stitch, etc.). Copy to `vf-launchers-context.sh` and fill in values. |

---

## Spikes run

| ID | Subject | Outcome |
|----|---------|---------|
| **S1** | Harness install recipes | ✅ All three install via `npm install -g`. Coexist in one container. Sizes: +64/+176/+111 MB. |
| **S2** | Base inheritance (vafi-base vs node direct) | ✅ Inherit from `vafi-base` — gives `agent` user + system packages for free. |
| **S3** | Extract build-context from existing images | ✅ `docker cp` recovered `/opt/vf-harness/` (Claude-hardcoded), `/opt/pi-developer/`, `/opt/mempalace/`. Sufficient to reconstruct source. |
| **S4** | Smoke test harness | ✅ Script written. Covers CLI version, mempalace, bind-mount RW, tool inventory, dispatch. |
| **S5** | Launcher refactor | ✅ Shared `_vafi_dev_run` + thin context wrappers. Harness is first arg. |

---

## Rumsfeld matrix — final state

### All blocking unknowns resolved

- **KU-1** Launcher defaults → `claude` for `vfdev`/`ogcli`/`ogdr`, `pi` for `pidev`.
- **KU-2** Pin syntax → `vfdev claude:2.1.90` (colon).
- **KU-3** Inherit from `vafi-base` → yes.
- **KU-4** Keep `/opt/vf-harness/` name → yes, content dispatches.
- **KU-5** Gemini install → `npm install -g @google/gemini-cli`.
- **KU-11** Pi auth → standard provider env vars; z.ai works via `ANTHROPIC_AUTH_TOKEN` + `ANTHROPIC_BASE_URL`.
- **KU-12** Gemini yolo → `-y` or `--approval-mode yolo`.
- **KU-13** Gemini config → `~/.gemini/`, MCP via `gemini mcp add/remove`.
- **UU-1** Coexistence → verified, no conflicts.

### Deferred (tracked, not blocking)

- **KU-6** Per-context harness version pin file — revisit after 30 days of use if needed.
- **KU-7** Secrets out of `~/.bashrc` — partial solution: `vf-launchers-context.sh` for the laptop-launcher secrets. Broader hygiene follow-up remains.
- **KU-8** Codex / Copilot leaves — add when concrete need appears; recipe is copy-paste from `Dockerfile.gemini`.
- **KU-9** Harbor publication — keep local-only until a second developer needs the images.
- **KU-10** Retention policy — laptop default: keep last 5 pinned leaf tags per harness + last 3 base builds.

### Surfaced items from S1

- **S1-OUT-1** Pi MCP via `pi install npm:pi-mcp-adapter` — **implemented** in `Dockerfile.pi`.
- **S1-OUT-2** Pi's default provider is google → documented in `developer-images-S1-REPORT.md`.
- **S1-OUT-3** Pi has no blanket-approval flag → handled in `run.sh` via restricted `--tools` default (Pi runs with its default allow-list; no yolo bypass needed).
- **S1-OUT-4** `pidev` should migrate from fleet image to `vafi-developer:pi` → **implemented** in `vf-launchers.sh`; default harness for `pidev` is `pi`.
- **S1-OUT-5** Claude `--bare` mode → out of scope (fleet consideration).

---

## Migration steps (what the user needs to do)

### Option A — adopt immediately

1. **Source the new launchers** in `~/.bashrc`:
   ```bash
   [ -f ~/.claude/vf-launchers.sh ] && . ~/.claude/vf-launchers.sh
   ```
   Add this line to `~/.bashrc` AFTER the existing `ogcli`/`ogdr`/`vfdev`/`pidev` function definitions. New sourced functions override the old inline ones.

2. **Set up context secrets**:
   ```bash
   cp ~/.claude/vf-launchers-context.sh.example ~/.claude/vf-launchers-context.sh
   # Edit ~/.claude/vf-launchers-context.sh — move the existing secrets there:
   #   - STITCH_API_KEY from old vfdev
   #   - MW_BOT_USER / MW_BOT_PASS from old ogcli / ogdr
   #   - z.ai ANTHROPIC_AUTH_TOKEN / ANTHROPIC_BASE_URL from old pidev
   ```

3. **Delete the old inline functions** from `~/.bashrc` (lines 547–760 approximately — the `ogcli`, `ogdr`, `vfdev`, `pidev` function definitions).

4. **Test end-to-end**:
   ```bash
   vfdev claude       # should pull + run vafi-developer:claude
   vfdev pi           # same workspace, pi instead
   ogcli claude       # switch context to OG
   ```

### Option B — parallel-run (safer)

1. Source the new launchers LAST so the new definitions shadow the old ones.
2. Verify each context one at a time: `vfdev`, `ogcli`, `ogdr`, `pidev`.
3. Once all four verified, delete the old functions.
4. Retire old image tags:
   ```bash
   docker rmi vafi/vafi-developer:latest \
              vafi/vafi-pi-developer:latest \
              vafi/vafi-devtools:latest \
              vafi/vafi-pi-devtools:latest \
              vafi/vafi-claude-mempalace:latest \
              vafi/vafi-pi-devtools:latest
   ```

---

## Known gotchas

- **First run in a context** creates `~/<CTX>/home/agent/` and `~/<CTX>/workspace/` with `sudo chown 1001:1001`. Will prompt for sudo password.
- **Gemini MCP registration** in `init-gemini.sh` uses `gemini mcp add --scope user mempalace python3 -- -m mempalace.mcp_server`. The exact arg form is a best-effort from `gemini mcp --help`; if it fails silently, run `gemini mcp list` inside the container to confirm.
- **Pi with no provider env set** will start but fail at first prompt. Set at least one of `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `OPENAI_API_KEY` in your context-secrets file, or rely on the host-level `GEMINI_API_KEY` being forwarded automatically.
- **Docker socket mount** (`vfdev` only) gives the harness nested-docker access. Same exposure that existed before the refactor.

---

## What's NOT done

- **Adoption** — user must source the new launchers and delete the old. Not automated; requires reading `~/.bashrc` in context of their own customizations.
- **Harbor push** — images are local-only (KU-9 deferred).
- **Codex / Copilot leaves** — design supports them; no Dockerfile yet (KU-8 deferred).
- **Retention cron** — no automatic pruning scripted (KU-10 deferred).

---

## How to add a new harness later

1. Create `images/developer/Dockerfile.<harness>` mirroring `Dockerfile.gemini` (single `npm install -g <pkg>` + `ENV VF_HARNESS=<harness>`).
2. Create `images/developer/vf-harness/init-<harness>.sh` with auth + MCP setup.
3. Add a branch to `init.sh`, `connect.sh`, `run.sh` `case "$HARNESS"`.
4. Add `<harness>` to `vf-launchers.sh`'s regex list.
5. Add one line to `scripts/build-developer-images.sh` case.
6. Run `./scripts/build-developer-images.sh <harness>` and `./scripts/smoke-test-developer.sh <harness>`.

Total effort: ~30 minutes for a CLI that installs cleanly via `npm install -g` and has an `--api-key` or env-var auth model.
