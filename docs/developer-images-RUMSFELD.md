# Rumsfeld Matrix: Developer Images

**Date:** 2026-04-17
**Subject:** Local laptop developer container family (`vafi-developer-base` + `vafi-developer:<harness>-<version>`). See [developer-images-DESIGN.md](developer-images-DESIGN.md) for the chosen architecture.

This matrix captures what we know, what we don't, what we might be missing, and what we know-but-haven't-yet-applied. It exists to make the design doc's "Open questions" section actionable and to surface risks before we build anything.

---

## Known Knowns (Verified facts)

### Current image family on this host

| # | Fact | Source |
|---|------|--------|
| KK-1 | `vafi/vafi-developer:latest` is a **Pi build**. Entrypoint `/opt/pi-developer/entrypoint-pi-local.sh`, `CMD ["pi"]`. | `docker inspect vafi/vafi-developer:latest --format '{{json .Config}}'` |
| KK-2 | `vfdev` in `~/.bashrc:659-698` hardcodes image `vafi/vafi-developer:latest`. Cannot pick a different harness at launch today. | `~/.bashrc` read directly |
| KK-3 | Current dev-family has four local tags: `vafi-developer`, `vafi-pi-developer`, `vafi-devtools`, `vafi-pi-devtools` (plus `vafi-claude-mempalace`). None have `RepoDigests` → all are **local-only, never pushed to Harbor**. | `docker inspect` |
| KK-4 | All four dev images share the same bottom 8 rootfs layers = **stock `node:20-bookworm-slim`** (Debian bookworm + node 20.20.1 + yarn 1.22.22 + `docker-entrypoint.sh` + `CMD ["node"]`). | `docker inspect --format '{{.RootFS.Layers}}'` diff against standard node image layers |
| KK-5 | `vafi-devtools` and `vafi-pi-devtools` are **parallel siblings**, not a chain. Both build on node base and install their own harness CLI directly. Diverge at layer 9. | `docker history` comparison |
| KK-6 | `vafi-developer:latest` and `vafi-pi-developer:latest` both build on **`vafi-pi-devtools`** (first 28 rootfs layers identical). Neither builds on `vafi-devtools`. | `diff` on rootfs layer lists |
| KK-7 | `vafi-devtools:latest` **has Claude Code 2.1.90** installed (`/usr/local/bin/claude`). `vafi-developer:latest` does **not** — `claude: command not found`. | `docker run --rm --entrypoint="" <img> which claude` |
| KK-8 | `vafi-pi-developer:latest` has Pi 0.66.1. | `docker run --rm --entrypoint="" vafi-pi-developer:latest pi --version` |
| KK-9 | Mempalace is pip-installed in the leaf (`-developer`) images at `/usr/local/lib/python3.11/dist-packages/mempalace/` but not in the `-devtools` siblings. | `docker run --rm --entrypoint="" <img> python3 -c "import mempalace; ..."` |

### Source / build context

| # | Fact | Source |
|---|------|--------|
| KK-10 | **Source Dockerfiles for the dev family are NOT under `~/GitHub/vafi`.** No file under `~` at depth ≤ 6 matches `Dockerfile.developer`, `Dockerfile.pi-developer`, `Dockerfile.devtools`, etc. | `find ~ -maxdepth 6 -iname "Dockerfile*"` |
| KK-11 | Three build-context files are baked into the dev images but absent on disk: `/opt/pi-developer/entrypoint-pi-local.sh`, `/opt/pi-developer/APPEND_SYSTEM.md`, `/opt/pi-developer/extensions/mempalace-hooks.ts`. | `find ~ -maxdepth 6 -name <files>` returned only runtime-copied instances in `~/VF/home/agent/.pi/agent/` |
| KK-12 | Three harness scripts `/opt/vf-harness/{init,connect,run}.sh` are baked in; **all three are Claude-specific** (hardcode `~/.claude.json`, `claude --continue`, `claude -p … --output-format json`). | `docker cp` extraction from `vafi-devtools:latest` — contents read |
| KK-13 | Build-context files **can** be recovered via `docker cp $(docker create <img>):/opt/...`. Demonstrated for `/opt/vf-harness/`. | Successfully extracted to `/tmp/vf-harness-recovered/` |

### Launcher pattern

| # | Fact | Source |
|---|------|--------|
| KK-14 | Four context launchers in `~/.bashrc` share the same shape: `vfdev` (~/VF), `ogcli` (~/OG), `ogdr` (~/DR), `pidev` (~/PI). Each: creates mount dirs if missing, chowns to uid 1001, injects context-specific env, runs `docker run -it --rm ...`. | `~/.bashrc` lines 545-760 read directly |
| KK-15 | Three of the four launchers (`ogcli`, `ogdr`, `vfdev`) currently run `vafi/vafi-developer:latest`. Only `pidev` runs a different image. | `~/.bashrc` read |
| KK-16 | `vfdev` adds `-v /var/run/docker.sock:/var/run/docker.sock` for nested docker; `ogcli` / `ogdr` do not. | `~/.bashrc` read |
| KK-17 | Per-context secrets hardcoded in `~/.bashrc` as env vars: `STITCH_API_KEY` (vfdev), `MW_BOT_PASS` (ogcli/ogdr MediaWiki bot), z.ai auth (pidev). Plaintext in the shell rc file. | `~/.bashrc` read |
| KK-18 | `gemini` CLI is used on the host (alias `gyr="gemini --yolo --resume"` at `~/.bashrc:268`). Not installed in any container image. | `~/.bashrc` read |

### Fleet (production) side

| # | Fact | Source |
|---|------|--------|
| KK-19 | The fleet image tree — `vafi-base` → `vafi-claude` / `vafi-pi` → `vafi-agent` / `vafi-agent-pi` → `vafi-bridge` — is **fully sourced** in `~/GitHub/vafi/images/{base,claude,pi,agent,bridge,cxdb-mcp}/Dockerfile`. | Filesystem read |
| KK-20 | Fleet uses `VF_HARNESS` env var + parameterized `images/agent/Dockerfile` (`ARG HARNESS_IMAGE`) to swap harness at build. Same controller on both variants. | `docs/harness-images-ARCHITECTURE.md` + `images/agent/Dockerfile` read |
| KK-21 | Fleet images use `vafi-base` which is a **minimal** Node+Python+git layer (368 MB). No dev tools (no kubectl/terraform/ansible/go/helm/etc). | `images/base/Dockerfile` read |

---

## Known Unknowns (Questions to resolve)

### Blocks first build

| # | Question | Why it blocks | How to resolve |
|---|----------|---------------|----------------|
| KU-1 | **Default harness per launcher.** Should `vfdev`/`ogcli`/`ogdr` default to `claude` when no arg given? `pidev` default to `pi`? Or always require an explicit arg? | Shapes launcher code; changes UX (backwards compat with existing `vfdev` typing habit). | Decision (5 min). Recommendation: yes, defaults — `claude` for `vfdev`/`ogcli`/`ogdr`, `pi` for `pidev`. Preserves muscle memory. |
| KU-2 | **Pin syntax at the launcher.** `vfdev claude:2.1.90` or `vfdev claude-2.1.90`? | Shapes arg-parsing regex in the shared helper. | Decision (2 min). `:` version separator mirrors Docker tag syntax (`image:tag`); `-` mirrors the tag body. Pick one, document it. |
| KU-3 | **Unify with fleet base?** Should `vafi-developer-base` `FROM vafi-base:latest` (inherit fleet's base), or `FROM node:20-bookworm-slim` directly? | Unifying would mean fleet body and laptop body share some DNA; could drift if fleet team changes `vafi-base`. | Compare `vafi-base` content against what laptop body needs. `vafi-base` is minimal and stable; inheriting saves ~10 lines of Dockerfile and keeps the user (`agent` uid 1001) + `node:20-bookworm-slim` base in sync automatically. **Recommended: inherit.** |
| KU-4 | **Retain `/opt/vf-harness/` scripts name, or rename?** The name is generic but the current content is Claude-specific. | Cosmetic but documentation-affecting. | Keep the name; change the content to dispatch on `$VF_HARNESS`. Matches fleet convention (fleet also uses `/opt/vf-harness/`). |
| KU-5 | **Gemini install command.** Not verified on this host. Google publishes multiple options (`@google/gemini-cli`, npm vs pip, etc.). | Can't author `Dockerfile.gemini` without this. | Spike: install the Gemini CLI on the host, record exact install command, note auth mechanism (API key env var). ~20 min. |

### Blocks production use (but not first build)

| # | Question | Why it matters | How to resolve |
|---|----------|----------------|----------------|
| KU-6 | **Per-context harness version pinning.** Does VF want `claude:2.1.90` while OG wants `claude:2.1.91`? | If yes, the launcher needs to read a pin from somewhere (env? per-context config file?). | Defer until a concrete need appears. Pinning via `vfdev claude:2.1.90` on-demand is enough for most rollback scenarios. |
| KU-7 | **Where do per-context secrets live?** Hardcoded in `~/.bashrc` today (MediaWiki bot password, Stitch API key, z.ai token). | Security hygiene; also blocks sharing `~/.bashrc` across machines / committing to dotfiles. | Move to `~/.vf-context/<ctx>.env` (or similar) loaded by the launcher. Out of scope for the image work, but should be flagged. |
| KU-8 | **Codex / Copilot timing.** Add in first pass? | Low marginal cost (~10 lines of Dockerfile each) but adds build/test burden. | Defer until the three-harness base is proven. New harness = one Dockerfile, per the design. |
| KU-9 | **Harbor publication.** Push `vafi-developer-base` and leaves, or keep local-only? | Sharing across machines/users requires push. Local-only keeps pull latency = 0 and side-steps access control. | Decision (5 min). Default to **local-only** until a second developer needs them. Revisit when that happens. |
| KU-10 | **Retention policy.** How many pinned leaf tags to keep per harness before pruning? | Disk-space bounded, not correctness. | Laptop default: keep last 5 per harness + last 3 base dates. Script the prune in a weekly cron. |

### Blocks specific leaves

| # | Question | Affected leaf |
|---|----------|---------------|
| KU-11 | How does Pi authenticate in a local dev context? (Fleet side uses k8s secrets; laptop needs to match the `pidev` pattern which uses z.ai.) | `Dockerfile.pi` + `entrypoint-pi.sh` |
| KU-12 | Does Gemini have a `--yolo`-style "skip permission prompt" mode? (Claude has `--dangerously-skip-permissions`; Pi has similar.) | `entrypoint-gemini.sh` |
| KU-13 | What config file path does Gemini write to for MCP/project settings? Must be covered by the bind-mounted `~/VF/home/agent/`. | `Dockerfile.gemini` |

---

## Unknown Knowns (Things we know but haven't applied)

| # | Insight | Implication |
|---|---------|-------------|
| UK-1 | The **fleet already solved multi-harness** via `VF_HARNESS` env + parameterized Dockerfile + per-harness entrypoint sections. We don't need to invent; we just need to copy the pattern for a laptop body. | The entrypoint pattern in `images/agent/entrypoint.sh` is the reference. Don't re-design; re-use. |
| UK-2 | The `/opt/vf-harness/run.sh` script ALREADY encodes the idea of a dispatcher — it's just hardcoded to claude today. The script name (`run.sh`) is harness-agnostic; only its body isn't. | Fix is a one-file edit + a `case $VF_HARNESS in` branch, not a rewrite. |
| UK-3 | The four context launchers (`ogcli`, `ogdr`, `vfdev`, `pidev`) are ~90% duplicated in `~/.bashrc`. Extracting `_vafi_dev_run` is ~50 lines removed. | Refactor is a natural side-effect of adding the harness arg. No extra design work needed. |
| UK-4 | **`APPEND_SYSTEM.md` appears at runtime** in `~/VF/home/agent/.pi/agent/APPEND_SYSTEM.md`, copied by the current Pi entrypoint from `/opt/pi-developer/`. So the "copy static file from image to user home" pattern is already in use — our entrypoint just needs to do the same thing per harness. | Entrypoint design can mirror what Pi already does: image ships defaults; entrypoint copies them into the right dotdir. |
| UK-5 | Mempalace, ssh keys, bash history, and the `.pi/` / `.claude/` / `.gemini/` dotdirs all live under `~/VF/home/agent/` (bind-mount). They persist across harness swaps automatically. | No additional work needed to make "same workspace, different driver" work — the bind-mount does it for free. |
| UK-6 | Stitch API key in `~/.bashrc:682` is **plaintext**. Every new harness/context we add is more plaintext creeping into the shell rc. | This is a pre-existing hygiene issue the current setup has. Adding harnesses doesn't worsen it, but this design is a natural point to flag it for a follow-up (KU-7). |
| UK-7 | `vafi-developer:latest` is currently the image three of the four launchers depend on. Retiring it requires the launcher refactor FIRST — order matters for the migration. | Migration plan in the design doc reflects this (step 4 before step 6). |
| UK-8 | `node:20-bookworm-slim` is the universal starting point for every image in both the fleet and dev families. A body built on `vafi-base` (which itself is `node:20-bookworm-slim` + system packages + `agent` user) gives us the `agent` uid-1001 user for free and avoids duplicating the user-creation RUN. | Strongly argues for KU-3 = "inherit from vafi-base". |

---

## Unknown Unknowns (Risks we haven't fully thought through)

These are speculative. Listing them so we have mitigation hooks, not because we know they'll hit.

| # | Area | Why it's a blind spot | Mitigation hook |
|---|------|----------------------|-----------------|
| UU-1 | **npm package conflicts.** Claude, Pi, Gemini are all npm globals in their respective leaves, but mempalace also runs a Python environment that the base body installs. A body-level change (e.g. mempalace requires a newer Python) could break a leaf silently. | Smoke test every leaf on every body rebuild. Script: `pi --version`, `claude --version`, `gemini --version`, `python3 -c "import mempalace"`. |
| UU-2 | **Harness upstream auth changes.** A harness CLI might change how it reads credentials (env var renamed, config file path moved). The current launcher injects fixed env names (`CLAUDE_CREDENTIALS`, etc.); a breaking change upstream silently leaves the container unauthenticated. | Test harness auth end-to-end in the leaf smoke test, not just `--version`. |
| UU-3 | **MCP config drift.** Each harness has its own MCP config format (`~/.claude.json` vs `~/.pi/agent/settings.json` vs unknown for gemini). If a harness changes format across versions, the entrypoint breaks for old context homes that still have the old-format file. | Entrypoint writes the MCP config **from env vars every time**, overwriting any stale version. Don't rely on `~/VF/home/agent/.claude.json` persisting across harness version bumps. |
| UU-4 | **Docker socket mount in `vfdev`.** Nested docker inside the container inherits host docker trust. If a harness prompt tricks the agent into `docker run --privileged`, the container can escape. | The current setup already has this risk with `vfdev`. Not worse after the refactor, but call it out as a known exposure. |
| UU-5 | **Body rebuild breaking cache for leaves.** If `vafi-developer-base:2026-04-17` is deleted from local disk (e.g. `docker image prune`) while leaves still reference it via `FROM`, rebuilds of those leaves fail until the base is re-pulled or rebuilt. | Retention policy (KU-10) must keep old bases until no leaves reference them. Or always rebuild from current `:latest` base and accept old leaves stay on old bases. |
| UU-6 | **Harness CLI sizes could grow.** A future `claude-3.x` or `gemini-2.x` could triple in install size. Leaves are cheap today (~150 MB per harness); this could change. | Monitor per-leaf size on rebuild. Put a soft alert at 500 MB added per leaf. |
| UU-7 | **Bind-mount permissions in WSL2.** The current `sudo chown 1001:1001` step assumes the host filesystem supports uid-based ownership. On certain WSL/Windows setups this silently fails or reverts. | The current launcher already has this risk; reproducing in the new launcher is no worse. Flag for test on Windows. |
| UU-8 | **Mempalace state format.** Mempalace is pip-installed in the base. A body bump that updates mempalace to a new version might read existing `~/VF/home/agent/.mempalace/palace/` from an older version and either migrate or break. | Not our decision here — this is mempalace-side. But worth saying: a body bump could silently alter user state. Back up `~/VF/home/agent/.mempalace/` before rolling bodies. |
| UU-9 | **`vafi-mcp` docker network dependencies.** Launchers conditionally attach to `vafi-mcp`. If MCP-server containers on that network change their IP / port conventions, the CLI inside the dev container fails silently (MCP queries just time out). | Not new. Flag for the smoke test: "from inside the leaf, can I reach the shared MCP server?" |

---

## Decisions already made (from design doc)

Recorded here so they don't re-open in this matrix:

- Layered tree: `vafi-developer-base:<body-date>` + `vafi-developer:<harness>-<cli-version>` per leaf. [Design §Image tree]
- Leaf Dockerfiles pin base with explicit date (`FROM vafi-developer-base:YYYY-MM-DD`), never `:latest`. [Design §Base/leaf coordination]
- No `vafi-developer:latest` tag. [Design §Versioning]
- In-session harness switching explicitly out of scope. [Design §Non-Goals]
- Runtime harness install explicitly out of scope. [Design §Alternatives D]
- Shared `~/<ctx>` across harness swaps within one context. [Design §Non-Goals]
- K8s fleet tree unaffected. [Design §Scope note]

## Decisions resolved 2026-04-17

- **KU-1 — Launcher defaults.** `vfdev`, `ogcli`, `ogdr` default to `claude` when no harness arg is given. `pidev` defaults to `pi` (continuity). Preserves muscle memory; explicit override always available.
- **KU-2 — Pin syntax.** `vfdev claude:2.1.90`. Colon mirrors Docker tag grammar (`repo:tag`). Launcher arg parsing: split on first `:`; left-hand is harness, right-hand (optional) is CLI version.
- **KU-4 — `/opt/vf-harness/` name retained.** The directory and script names (`init.sh`, `connect.sh`, `run.sh`) stay. Content changes to dispatch on `$VF_HARNESS`. Matches fleet convention and avoids renaming paths baked into existing images.
- **KU-5 — Gemini install.** `npm install -g @google/gemini-cli` (verified in fresh `node:20-bookworm-slim`). Binary: `gemini`. Auth: `GEMINI_API_KEY`. See S1 report for full details.
- **KU-11 — Pi auth.** Pi reads standard provider env vars (`ANTHROPIC_API_KEY`, `ANTHROPIC_OAUTH_TOKEN`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, etc.) — not a unique auth story. The `pidev` z.ai token is just an Anthropic-compatible proxy; works because Pi honors `ANTHROPIC_BASE_URL`.
- **KU-12 — Gemini skip-permissions flag.** `-y` / `--yolo` or `--approval-mode yolo`.
- **KU-13 — Gemini config path.** `~/.gemini/`. MCP servers registered via `gemini mcp add/remove` subcommands, stored inside that dir.
- **UU-1 — coexistence verified.** All three harnesses install cleanly in the same `node_modules` tree (Claude 2.1.112 + Pi 0.67.6 + Gemini 0.38.1). No binary or directory collisions. Combined size: +350 MB on top of empty node. See S1 report.
- **KU-3 — inherit from `vafi-base`.** `vafi-base:latest` (fleet image) already provides `node:20-bookworm-slim` + git/curl/python3/jq/openssh-client + `agent` uid-1001 user + `WORKDIR /home/agent`. Exactly the prelude our body needs. `Dockerfile.base` uses `FROM ${REGISTRY}/vafi-base:latest` — saves ~20 lines and keeps user/uid in sync with the fleet automatically. Verified via `docker inspect` + `docker history` on `vafi/vafi-base:latest`.

## Items surfaced by S1 spike (new)

| # | Item | Disposition |
|---|------|-------------|
| S1-OUT-1 | Pi MCP integration is a runtime `pi install npm:pi-mcp-adapter` step — not a declarative config file. `Dockerfile.pi` must include this at build time (same pattern as `images/pi/Dockerfile:21-30` in the fleet tree). | Bake into `Dockerfile.pi`. |
| S1-OUT-2 | Pi's default provider is `google` (Gemini). A laptop with only `GEMINI_API_KEY` set works for both `pi` and `gemini` out of the box. | Document in launcher README. |
| S1-OUT-3 | Pi has no `--yolo`-style blanket-approval flag; its tool model is opt-in via `--tools <list>`. The dispatcher in `/opt/vf-harness/run.sh` must restrict Pi explicitly rather than try to bypass a non-existent prompt. | Encode in dispatcher case branch. |
| S1-OUT-4 | `pidev` currently launches `vafi-agent-pi:*` (a fleet image), not a dev image. It's out of step with `ogcli` / `ogdr` / `vfdev`. | Phase 3 launcher refactor: migrate `pidev` to `vafi-developer:pi` for consistency. |
| S1-OUT-5 | Claude Code has `--bare` mode (skips auto-memory, keychain reads, hooks). Potentially useful for the k8s fleet; not applicable to interactive laptop dev. | Note for fleet team. Out of scope here. |
| LT-OUT-1 | `mempalace init` prints its multi-line banner to stdout, polluting JSON output when triggered on first run in a context (found by launcher-test). | Fixed: `init.sh` now redirects `mempalace init` output to `/dev/null`. |
| LT-OUT-2 | Launcher used `-it` unconditionally which fails `not a TTY` in non-interactive testing. | Fixed: `_vafi_dev_run` auto-detects TTY via `[ -t 0 ] && [ -t 1 ]` and uses `-i` alone when no TTY. |
| LT-OUT-3 | Pi auto-discovers providers at runtime from ALL `*_API_KEY` env vars and ignores `models.json` if OPENAI_API_KEY is also set — picks it preferentially even when GEMINI_API_KEY + google `models.json` are configured. (Found via the user having OPENAI_API_KEY=sk-or-v1... OpenRouter key on the host, forwarded by the launcher.) | Fixed: `init-pi.sh` now UNSETs competing provider env vars after selecting one, and exports `VF_PI_PROVIDER` / `VF_PI_MODEL`. `run.sh` passes them as explicit `--provider` / `--model` flags. Belt-and-braces. |

---

## Priority & order-of-operations

**Phase 0 — resolve blockers (1 short session):**
- KU-1 (defaults), KU-2 (pin syntax), KU-3 (inherit vafi-base?), KU-4 (keep vf-harness name)
- KU-5 (gemini install spike)

**Phase 1 — extract & reconstruct source:**
- `docker cp` `/opt/vf-harness/`, `/opt/pi-developer/`, `/opt/mempalace/` out of the existing images (KK-13 proven)
- Commit to `images/developer/` as starting source for Dockerfiles
- Confirm UK-2 by reviewing the extracted scripts

**Phase 2 — author base + leaves:**
- `Dockerfile.base` (reuse vafi-base per KU-3 if accepted)
- `Dockerfile.claude`, `Dockerfile.pi` first (verified install commands from KK-7, KK-8)
- `Dockerfile.gemini` after KU-5 resolved

**Phase 3 — refactor launchers:**
- `_vafi_dev_run` helper (UK-3)
- Harness arg parsing (KU-2 syntax)
- Context launchers become thin wrappers

**Phase 4 — smoke tests & migration:**
- UU-1, UU-2, UU-9 mitigations (smoke test per leaf)
- Parallel-run old `vafi/vafi-developer:latest` until each context (VF, OG, DR) verified end-to-end
- Retire old tags (KK-3)
- Update `docs/INDEX.md`

**Deferred (not blocking):**
- KU-6 (per-context pinning file) — revisit after first month of use
- KU-7 (secrets out of bashrc) — follow-up issue
- KU-8 (codex, copilot) — when a concrete need appears
- KU-9 (harbor publication) — when a second developer needs images

---

## What this matrix is for

Before building: work Phase 0 down to zero open questions.
During build: keep UU-1 through UU-9 as test hooks — actively try to trip them.
After build: prune decided items out of the matrix; keep only the live ones.
