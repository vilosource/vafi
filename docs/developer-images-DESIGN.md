# Developer Images Design

Last updated: 2026-04-17
Status: Draft — pending approval before implementation.

> **Scope note.** This doc describes **local laptop developer containers** used for interactive ViloForge / OptiscanGroup / related work. It is distinct from the Kubernetes agent fleet — that architecture lives in [harness-images-ARCHITECTURE.md](harness-images-ARCHITECTURE.md) and is unaffected by anything here.

---

## Problem Statement

The current local developer container family is broken along five axes:

1. **Naming no longer matches content.** The tag `vafi/vafi-developer:latest` sounds harness-agnostic but actually ships Pi: its entrypoint is `/opt/pi-developer/entrypoint-pi-local.sh` and `CMD` is `["pi"]`. Running `vfdev` launches Pi regardless of intent.

2. **Source is not in the repo.** The build context for `vafi-developer:latest`, `vafi-pi-developer:latest`, `vafi-devtools:latest`, and `vafi-pi-devtools:latest` is not under `~/GitHub/vafi`. Three files baked into these images (`/opt/pi-developer/entrypoint-pi-local.sh`, `APPEND_SYSTEM.md`, `extensions/mempalace-hooks.ts`) and three harness scripts (`/opt/vf-harness/{init,connect,run}.sh`) exist only inside the images. Rebuilding today is not reproducible from on-disk sources.

3. **Only one harness is supported at a time.** The original goal — *"a developer harness I can use with claude, gemini, or pi, picking at any given time"* — is not met. Today you get Pi or nothing. Claude Code is installed in `vafi-devtools:latest` but no mempalace/dev leaf exists on the claude branch. Gemini is not in any image. Codex-cli and Copilot-cli are not planned for anywhere.

4. **Growth path is blocked.** Adding a new harness today means duplicating a full image family. Release cadences differ wildly (Claude ships near-daily, Pi roughly weekly, Gemini monthly, future CLIs unknown), so any scheme that couples body rebuild to harness rebuild imposes a maintenance cost that scales with `harnesses × their release frequency`.

5. **Rollback is not possible.** Floating `:latest` tags drift as the body rebuilds, so "go back to what I ran yesterday" has no referent. Any harness version pinning that lives only as a tag on an image whose body can change underneath is a false pin.

This design replaces the ad-hoc family with a reproducible, rollback-safe, growth-friendly image tree and a uniform launcher model for the existing context launchers (`vfdev`, `ogcli`, `ogdr`, `pidev`).

---

## Goals

- **One body, many heads.** Share the AI-agnostic devtools / mempalace / system layer across every harness.
- **Swap harness at launch** via a first-argument to any context launcher: `vfdev claude`, `ogcli pi`, `vfdev gemini`.
- **Decouple release cadences.** A Claude release rebuilds the claude leaf only. The body doesn't churn.
- **Add a harness cheaply.** New CLI = one Dockerfile (~10 lines) + one build-script entry. No body work.
- **True rollback.** Any pinned tag is bit-for-bit reproducible on pull, including the body it was built against.
- **Reproducibility from source.** Every image in the family must have its Dockerfile in `~/GitHub/vafi/images/developer/`.

## Non-Goals

- **K8s fleet architecture is unchanged.** `vafi-base`, `vafi-claude`, `vafi-pi`, `vafi-agent*`, `vafi-bridge` remain as-is; see the existing harness-images doc.
- **In-session harness switching.** To change harness you exit and relaunch. Considered (section "Alternatives") and rejected — the tradeoff against image size and rollback cleanliness wasn't worth it.
- **Per-harness mount roots.** `~/VF`, `~/OG`, etc. are context roots, shared across harness swaps within a context. Mempalace, shell history, ssh keys persist.
- **Runtime harness install** (pulling the CLI on first use into the bind-mount). Considered and rejected — breaks rollback, depends on upstream registry availability.

---

## Design

### Image tree

```
vafi-developer-base:<body-date>                # shared body; rebuilt only on body changes
    ├── vafi-developer:claude-<cli-version>    # FROM base:<pinned-date>
    ├── vafi-developer:pi-<cli-version>        # FROM base:<pinned-date>
    ├── vafi-developer:gemini-<cli-version>    # FROM base:<pinned-date>
    └── vafi-developer:<future-harness>-...    # FROM base:<pinned-date>
```

Two tag families, one repo per family:

| Repo | Role | Tag convention | Rebuild trigger |
|------|------|----------------|-----------------|
| `vafi-developer-base` | Shared body (devtools, mempalace, system packages, `/opt/vf-harness/`) | `YYYY-MM-DD` (e.g. `2026-04-17`); optional `.N` suffix for same-day rebuilds | Body content changes |
| `vafi-developer` | Harness leaf (body + one CLI) | `<harness>-<cli-version>` (e.g. `claude-2.1.90`) | Harness CLI release or body bump |

Plus floating tags that point at the latest:

- `vafi-developer-base:latest`
- `vafi-developer:claude`
- `vafi-developer:pi`
- `vafi-developer:gemini`

**No `vafi-developer:latest`.** Ambiguous in a multi-harness world.

### Base / leaf coordination (the critical rule)

Every leaf Dockerfile pins its base explicitly:

```dockerfile
FROM vafi-developer-base:2026-04-17
```

**Never** `FROM vafi-developer-base:latest` in a leaf. That would let the body drift under a stable leaf tag, making rollback meaningless.

Once a leaf is built and pushed, Docker embeds the base layers directly — the `FROM` line is not re-resolved on pull. So `vafi-developer:claude-2.1.90` is bit-for-bit identical whenever pulled, regardless of what happens to `vafi-developer-base:2026-04-17` afterward.

### Versioning

Pinned tags are artifacts (never move after push). Floating tags are pointers (advance with new builds).

| Tag | Type | Example | Meaning |
|-----|------|---------|---------|
| `vafi-developer-base:YYYY-MM-DD` | Pinned | `2026-04-17` | One specific body build. Immutable. |
| `vafi-developer-base:latest` | Floating | — | Most recent base build. Do not use as a rollback reference. |
| `vafi-developer:<h>-<v>` | Pinned | `claude-2.1.90` | One specific harness build on one specific body. Immutable. |
| `vafi-developer:<h>` | Floating | `claude` | Most recent leaf for this harness. |

If you need to rebuild the same harness version against a newer body (rare — usually only for a system-level fix), create a compound tag rather than overwriting: `claude-2.1.90-b2026-04-25`.

**Retention** (laptop): keep the last 5 pinned leaves per harness and the last 3 base builds; `docker image prune` the rest weekly.

### Launcher model

Each context launcher sets its mount root + environment. The first positional argument selects the harness.

```bash
vfdev  [harness[:version]] [cmd…]     # ViloForge work   — ~/VF
ogcli  [harness[:version]] [cmd…]     # OptiscanGroup    — ~/OG
ogdr   [harness[:version]] [cmd…]     # OG disaster-rec. — ~/DR
pidev  [harness[:version]] [cmd…]     # (retained; default harness may be `pi` for continuity)
```

Resolution:

- `vfdev claude`          → image `vafi-developer:claude` (floating)
- `vfdev claude:2.1.90`   → image `vafi-developer:claude-2.1.90` (pinned)
- `vfdev`                 → default harness per launcher (configurable; recommended default `claude` for `vfdev` / `ogcli` / `ogdr`, `pi` for `pidev`)
- `vfdev -- cmd…`         → use default harness, pass the rest through

Context-specific details (mount root, network membership, auth/env vars, Stitch/MediaWiki/GitLab/z.ai secrets) stay per-launcher. The harness-to-image mapping is shared — all four launchers resolve against the same `vafi-developer:*` tag namespace.

The current four launchers are ~90% duplicated. This refactor extracts the shared `docker run` invocation into a single helper (`_vafi_dev_run`) in `~/.bashrc`. Each launcher becomes a 5–10 line wrapper that supplies its context-specific env and defers the rest.

### Harness auth

Each launcher unconditionally injects all env vars relevant to its context (matching current behavior). The running image only *uses* the env vars whose corresponding CLI is installed — one CLI per leaf image, so no cross-contamination. Example:

- `vfdev` sets `CLAUDE_CREDENTIALS`, `STITCH_API_KEY`, `MEMPALACE_AUTO_INIT`, etc.
- Inside the `claude` leaf, the entrypoint writes `~/.claude/.credentials.json` from `CLAUDE_CREDENTIALS`.
- Inside the `pi` leaf, the entrypoint sets up Pi auth from its own env vars; `CLAUDE_CREDENTIALS` is simply ignored.

The entrypoint is harness-specific and lives in each leaf (`images/developer/entrypoint-claude.sh`, `entrypoint-pi.sh`, etc.), not in the base.

### Repository layout

```
~/GitHub/vafi/images/developer/
├── Dockerfile.base            # ARG BODY_VERSION; body content
├── Dockerfile.claude          # FROM vafi-developer-base:<pinned>; npm i -g @anthropic-ai/claude-code
├── Dockerfile.pi              # FROM vafi-developer-base:<pinned>; npm i -g @mariozechner/pi-coding-agent
├── Dockerfile.gemini          # FROM vafi-developer-base:<pinned>; gemini install TBD
├── entrypoint-claude.sh       # per-harness init
├── entrypoint-pi.sh
├── entrypoint-gemini.sh
├── vf-harness/                # scripts baked into the base — generic init/connect/run helpers
│   ├── init.sh
│   ├── connect.sh
│   └── run.sh
└── README.md
```

The `vf-harness/` scripts are currently hardcoded for Claude even though they live under a generic name (see "Current state" below). As part of this design they become harness-dispatching: `run.sh` reads `$VF_HARNESS` (set by the leaf's entrypoint) and dispatches to the right CLI invocation.

### Build script

`scripts/build-developer-images.sh` (new; separate from the existing `build-images.sh` which handles the fleet tree):

```bash
# Rebuild body only
./scripts/build-developer-images.sh base

# Rebuild a single harness leaf against the current :latest base
./scripts/build-developer-images.sh claude

# Rebuild a leaf against a specific body
./scripts/build-developer-images.sh claude --base 2026-04-17

# Rebuild all leaves against the current :latest base
./scripts/build-developer-images.sh all
```

Each leaf build:
- Pulls or uses cached `vafi-developer-base:<body>`.
- Reads the installed harness CLI version (`claude --version`, `pi --version`, etc.).
- Tags both the pinned tag (`claude-<cli-version>`) and the floating tag (`claude`).

---

## Rollback

- **Harness version revert:** `docker pull vafi-developer:claude-2.1.89`. Base is embedded in the pinned tag; works offline after pull.
- **Body revert:** `docker pull vafi-developer-base:2026-04-10`, then rebuild the leaves you care about against it. Uncommon; usually triggered by a regression in mempalace or a devtools package.
- **Same harness version on a newer body** (rare): new compound tag `claude-2.1.90-b2026-04-25`. Do not overwrite `claude-2.1.90`.

At the launcher:

```bash
vfdev claude:2.1.89       # pin to a specific historical build, one-shot
```

---

## Adding a new harness

Example: adding Gemini when we have the install command verified.

1. Create `images/developer/Dockerfile.gemini`:
   ```dockerfile
   FROM vafi-developer-base:<current-body-date>
   USER root
   RUN <gemini install command>
   USER agent
   COPY entrypoint-gemini.sh /opt/vf-harness/entrypoint-gemini.sh
   ENTRYPOINT ["/opt/vf-harness/entrypoint-gemini.sh"]
   ```
2. Create `images/developer/entrypoint-gemini.sh` — materialize auth from env, set `VF_HARNESS=gemini`, `exec "$@"`.
3. Add `gemini` to the case in `scripts/build-developer-images.sh`.
4. Add one line to the launcher helper to accept `gemini` as a valid harness.

No base changes, no other leaf changes, no launcher rewrite.

---

## Current state → target state (migration)

| Tag today | Content | Disposition |
|-----------|---------|-------------|
| `vafi/vafi-developer:latest` | Pi + mempalace build from 2026-04-16 (source missing from disk) | Retire after `vafi-developer:pi` is available and launchers are migrated. Keep locally until migration is verified end-to-end. |
| `vafi/vafi-pi-developer:latest` | Pi + mempalace, older (2026-04-13) | Retire alongside the above. |
| `vafi/vafi-devtools:latest` | Claude Code + devtools, but no mempalace/dev leaf | Source to reverse-engineer as the starting point for `Dockerfile.base` + `Dockerfile.claude`. Extract via `docker cp`. |
| `vafi/vafi-pi-devtools:latest` | Pi + devtools (no mempalace) | Source to reverse-engineer for `Dockerfile.pi`. |
| `vafi/vafi-claude-mempalace:latest` | Older Claude + mempalace (2026-04-11) | Reference for entrypoint behavior (`/opt/mempalace/entrypoint-local.sh`). Retire after migration. |
| `vfcode:latest` | Orphan early spike (2026-04-02), 5.47 GB | Delete; unused by any current launcher. |
| `vafi-bash-agent:latest` | Unused | Delete. |

Migration steps, in order:

1. **Extract existing content** with `docker cp` from `vafi-devtools:latest`, `vafi-developer:latest`, and `vafi-claude-mempalace:latest`. Commit `/opt/vf-harness/`, `/opt/pi-developer/`, `/opt/mempalace/` to `images/developer/` as the starting source.
2. **Write `Dockerfile.base`** reconstructing the body from the extracted layers and the existing `images/base/` + `images/claude/` / `images/pi/` primitives. Verify by building and shelling into it.
3. **Write the three leaf Dockerfiles**, each `FROM vafi-developer-base:<today>`.
4. **Refactor `~/.bashrc`** — introduce `_vafi_dev_run`, rewrite `vfdev` / `ogcli` / `ogdr` / `pidev` as thin wrappers, add harness argument handling.
5. **Parallel-run**: keep the old `vafi-developer:latest` tag until the new launcher works end-to-end for each context (VF, OG, DR).
6. **Cutover**: delete the old launchers' hardcoded image reference (already done by step 4) and the retired tags from step 1 above.
7. **Update `docs/INDEX.md`** to list this doc under Active Documents.

---

## Alternatives considered

### A. Single fat image with all harnesses baked in

`vafi-developer:<body-date>` containing `claude`, `pi`, `gemini`. User picks CLI in-session.

Rejected because: one harness release forces a full-image rebuild and push. Cost scales as `total harnesses × their combined release frequency`. Breaks as the set of supported harnesses grows.

### B. Three separate image repos (one per harness)

`vafi-developer-claude`, `vafi-developer-pi`, `vafi-developer-gemini`.

Rejected because: "these are three products" is the wrong mental model for one swappable-head developer container. Tag hygiene across three repos is harder than one. Pruning/retention is N-way.

### C. Tag variants without explicit base pin

`vafi-developer:claude-2.1.90` built with `FROM vafi-developer-base:latest`.

Rejected because: body drifts under the leaf tag. `docker pull claude-2.1.90` on day N returns a different artifact than on day N+30. False rollback.

### D. Runtime harness install into the bind-mount

Image ships no harnesses; a `vfh install claude` command `npm install`s into `~/VF/home/agent/.local/bin` on first use.

Rejected because: rollback depends on upstream package-registry persistence (claude 2.1.89 being available when 2.1.91 is broken). First-run latency. Offline breakage. Reproducibility-from-image-tag is lost entirely.

The chosen layered design (this doc) was the only option among these four that addressed every concern simultaneously.

---

## Open questions

1. **Default harness per launcher.** `vfdev` and `ogcli` — default `claude`? `pidev` — default `pi` (continuity)? Or always require an explicit harness arg (no default)?
2. **Harness-version pin at the launcher.** `vfdev claude:2.1.90` — syntax OK? Or use `vfdev claude-2.1.90` to match the tag form exactly?
3. **Gemini install command.** Not yet verified on this host. Needs to be resolved before `Dockerfile.gemini` can be authored.
4. **Codex / Copilot timing.** Add in first pass or defer until the three-harness base is stable?
5. **Harbor publication.** These are laptop images today. Do we push `vafi-developer-base` and the leaves to Harbor for sharing with other developers, or keep them local-only?
6. **Parity with k8s fleet images.** Should `vafi-developer-base` eventually become the base that the k8s fleet also consumes (unifying the two trees), or remain separate? The fleet side has stricter size/cold-start constraints that probably rule this out, but worth confirming.
