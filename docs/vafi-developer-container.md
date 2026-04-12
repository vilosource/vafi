# vafi-developer Container

The vafi-developer container is a fully-equipped Claude Code environment with persistent memory (MemPalace), infrastructure tooling, and optional MCP integrations. It is designed for local interactive developer use — isolated per customer or project via Docker volumes.

## Image Hierarchy

```
node:20-bookworm-slim
└── vafi-base          git, curl, python3, jq, openssh-client, agent user (uid=1001)
    └── vafi-claude    Claude Code CLI (npm), cxtx binary (Rust), harness scripts
        └── vafi-devtools   Azure CLI, azcopy, Terraform, Vault, Ansible, kubectl, Helm,
        │                   Go, uv, GitHub CLI (gh), GitLab CLI (glab), Docker CLI
        └── vafi-developer  MemPalace + ONNX embeddings, shell utils (vim, tmux, tree,
                            fzf, yq, bat, fd, ripgrep, httpie, shellcheck, dnsutils,
                            netcat), Python dev tools (ruff, mypy, pre-commit),
                            MCP MediaWiki
```

All images use `images/<name>/Dockerfile`. The developer layer is the final image intended for local use.

## Building

```bash
# Build the full chain (devtools is a dependency)
make build-developer        # → vafi/vafi-developer:latest

# Or build layers individually
make build-devtools         # → vafi/vafi-devtools:latest

# Push to Harbor registry
make push
```

The Makefile targets accept a `REGISTRY` variable (default: `vafi`). The push script targets `harbor.viloforge.com`.

## How It Works

### Launcher Script: `scripts/claude-mempalace`

This is the primary entry point for running the container locally.

```bash
claude-mempalace                            # default palace, current dir
claude-mempalace customer-acme              # isolated palace, current dir
claude-mempalace customer-acme ~/project    # isolated palace, specific dir
claude-mempalace --list                     # list all palaces
claude-mempalace --delete <name>            # delete a palace volume
```

What it does:
1. Resolves the workspace path (refuses to mount `$HOME` directly)
2. Auto-detects auth — reads `~/.claude/.credentials.json` for OAuth, or accepts `ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_BASE_URL` env vars for z.ai
3. Forwards optional env vars: `GITLAB_TOKEN`, `GITLAB_HOST`, `MW_API_HOST`, `MW_API_PATH`, `MW_USE_HTTPS`, `MW_BOT_USER`, `MW_BOT_PASS`, `MEMPALACE_AUTO_INIT`
4. Runs `docker run` with:
   - Home volume: `mempalace-<palace>-home` → `/home/agent` (persistent)
   - Workspace bind mount: `<host-dir>` → `/workspace` (read-write)

Image defaults to `harbor.viloforge.com/vafi/vafi-developer:latest`, overridable with `MEMPALACE_IMAGE` env var.

### Entrypoint: `images/developer/entrypoint-local.sh`

Runs as the `agent` user (no root). On startup it:

1. **Detects auth mode** — z.ai token, OAuth credentials (written to `~/.claude/.credentials.json`), or warns if neither is set
2. **Generates Claude Code config** (`~/.claude.json`) — registers MCP servers, marks `/workspace` as trusted, disables auto-updates
3. **Generates settings** (`~/.claude/settings.json`) — configures MemPalace hooks (Stop and PreCompact)
4. **Writes CLAUDE.md** (`~/.claude/CLAUDE.md`) — instructions for Claude on when/how to use MemPalace tools
5. **Configures glab** — writes GitLab CLI config if `GITLAB_TOKEN` is set
6. **Auto-inits palace** — if `MEMPALACE_AUTO_INIT=true` and no palace data exists
7. **Creates writable dirs** — `~/.claude/{session-env,projects,plans,history,cache}`
8. **Launches** — `cd /workspace && exec claude --dangerously-skip-permissions`

### Shell Shortcuts (in `~/.bashrc`)

Three convenience functions wrap `claude-mempalace`:

| Function | Auth | Behavior |
|----------|------|----------|
| `ant-mem [palace] [workspace]` | Anthropic OAuth | General-purpose launcher, passes all args through |
| `zai-mem [palace] [workspace]` | z.ai proxy | Routes through `api.z.ai` with API token |
| `ogcli` | Anthropic OAuth | Hardcoded palace `og` + workspace `~/OG` for OptiscanGroup |

All three set `MEMPALACE_IMAGE=vafi/vafi-developer:latest` and forward MediaWiki bot credentials for `wiki-api.optiscangroup.com`.

## MemPalace Integration

### Installation

The Dockerfile installs mempalace via pip and pre-downloads the ONNX embedding model (~79MB) at build time so no network call is needed on first search:

```dockerfile
RUN pip install --break-system-packages mempalace
RUN python3 -c "from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2; \
    ef = ONNXMiniLM_L6_V2(); ef._download_model_if_not_exists()"
```

### MCP Registration

The entrypoint registers mempalace as a stdio MCP server in `~/.claude.json`:

```json
{
  "mcpServers": {
    "mempalace": {
      "command": "python3",
      "args": ["-m", "mempalace.mcp_server"]
    }
  }
}
```

Claude Code spawns the `mempalace.mcp_server` process on startup. All 19+ MCP tools (search, add_drawer, kg_add, diary_write, etc.) are available immediately.

### Hooks

Two Claude Code hooks are configured in `~/.claude/settings.json`:

- **Stop** — fires every ~15 messages. Runs `mempalace hook run --hook stop --harness claude-code` to prompt Claude to save context.
- **PreCompact** — fires before context window compression. Runs the same command with `--hook precompact` to save everything before context is lost.

### Data Storage

All MemPalace data lives in `~/.mempalace/` inside the container:

```
~/.mempalace/
├── palace/
│   └── chroma.sqlite3          # ChromaDB vector store (embeddings + metadata)
├── knowledge_graph.sqlite3     # Temporal entity-relationship graph (SQLite)
├── wal/
│   └── write_log.jsonl         # Write-ahead log (audit trail)
├── config.json
└── people_map.json             # Name variant mapping
```

- **ChromaDB** — stores "drawers" (memories) with ONNX embeddings for semantic search. All local, no API calls.
- **Knowledge Graph** — SQLite with WAL journaling. Supports temporal queries ("what was true about X on date Y?").
- **Write-ahead log** — append-only JSONL audit trail of all writes.

## Volumes and Isolation

### Palace Volumes

Each palace gets its own Docker volume named `mempalace-<palace>-home`, mapped to `/home/agent`. This persists:

- `~/.mempalace/` — all MemPalace data (ChromaDB, knowledge graph, WAL)
- `~/.claude/` — Claude Code session data, settings, history
- `~/.ssh/` — SSH keys (if set up via `setup-ssh-palace`)
- `~/.config/glab-cli/` — GitLab CLI config

Palace isolation is a **hard boundary** — separate Docker volumes with no cross-palace access. Customer data in palace A is invisible from palace B.

### Workspace Mount

The host workspace directory is bind-mounted to `/workspace` (read-write). This is the only shared filesystem between host and container. The entrypoint `cd`s here before launching Claude.

## Helper Scripts

### `scripts/palace-backup` — Export/Import Palace Data

```bash
palace-backup export <palace>              # → mempalace-<palace>.tar.gz
palace-backup export <palace> <file>       # → custom path
palace-backup import <palace> <file>       # restore from backup
palace-backup list                         # show palaces with drawer counts
```

Exports only `~/.mempalace/` (not the full home volume). Import creates the volume if it doesn't exist and fixes ownership to uid 1001.

### `scripts/setup-ssh-palace` — Copy SSH Keys into a Palace

```bash
setup-ssh-palace <palace-name>
```

Copies SSH config and keys from the host `~/.ssh/` into the palace volume. Rewrites paths (`/home/jasonvi/.ssh` → `/home/agent/.ssh`), copies `known_hosts`, and fixes permissions. Run once per palace or after key rotation.

## Authentication Modes

| Mode | Env Vars | How It Works |
|------|----------|--------------|
| **OAuth** | (none — auto-detected) | `claude-mempalace` reads `~/.claude/.credentials.json` from host, passes content as `CLAUDE_CREDENTIALS` env var. Entrypoint writes it to `~/.claude/.credentials.json` inside container. |
| **z.ai** | `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL` | Passed through as env vars. Claude Code uses them directly. |
| **None** | (neither set) | Entrypoint prints a warning. Claude starts but can't make API calls. |

## Optional MCP: MediaWiki

When `MW_API_HOST` is set, the entrypoint registers a second MCP server:

```json
{
  "mediawiki": {
    "command": "mcp-mediawiki",
    "args": ["--transport", "stdio"],
    "env": {
      "MW_API_HOST": "wiki-api.optiscangroup.com",
      "MW_API_PATH": "/",
      "MW_USE_HTTPS": "true",
      "MW_BOT_USER": "...",
      "MW_BOT_PASS": "..."
    }
  }
}
```

This provides MCP tools for reading/writing self-hosted MediaWiki instances. The `mcp-mediawiki` package is installed from `github.com/vilosource/mcp-mediawiki`.

## Relationship to Fleet Images

The developer image shares the same base layers as the fleet agent images but serves a different purpose:

| Image | Purpose | Entrypoint | Volume |
|-------|---------|------------|--------|
| `vafi-developer` | Local interactive dev | `entrypoint-local.sh` → claude CLI | `mempalace-<palace>-home` |
| `vafi-agent` | Fleet executor/judge | `entrypoint.sh` → controller loop | K8s PVC per task |
| `vafi-agent-pi` | Fleet with Pi harness | `entrypoint.sh` → controller loop | K8s PVC per task |

The developer image is not used in the fleet — it has extra tooling (vim, tmux, etc.) and runs interactively with `--dangerously-skip-permissions`.
