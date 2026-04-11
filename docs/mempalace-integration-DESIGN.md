# MemPalace Integration — Persistent Agent Memory Design

Status: Draft (2026-04-11)

## Problem

Every agent session starts cold. The executor doesn't know that "k8s label values can't start with hyphens" caused a production bug last week. The judge doesn't remember that it flagged the same heartbeat timeout edge case three tasks ago. The architect makes decisions that contradict choices from previous sessions because there's no memory of what was decided.

This knowledge exists — but it dies when the session ends. Claude Code's built-in memory (`~/.claude/memory/`) is per-installation and doesn't carry into containers. The context file (`.vafi/context.md`) only contains the current task's history, not accumulated project knowledge. mykb is personal and file-based — agents can't access it.

The result: agents rediscover what was already known, repeat mistakes that were already caught, and make decisions that contradict earlier choices. Every session is a cold start.

## What MemPalace Is

MemPalace is an open-source persistent memory system for AI coding agents (MIT, github.com/milla-jovovich/mempalace). It stores knowledge locally in ChromaDB (vector search) and SQLite (knowledge graph), exposed as 19 MCP tools via stdio transport. No API keys required — embeddings run locally via ONNX.

Key capabilities relevant to vafi:

| Capability | What it does | Why it matters |
|---|---|---|
| **Semantic search** | Find memories by meaning, not just keywords | Agent asks "what went wrong with k8s labels" and finds the gotcha |
| **Knowledge graph** | Temporal entity-relationship triples with validity windows | Track decisions that change over time ("we used X, then switched to Y") |
| **Agent diaries** | Per-agent persistent notes across sessions | Executor builds expertise, judge remembers past reviews |
| **Wake-up context** | ~170 token summary loaded at session start | Minimal cold-start cost, search on demand |
| **Palace structure** | Wings (projects), rooms (topics), halls (knowledge types) | Metadata filtering improves retrieval by 34% over flat search |

MemPalace runs as a stdio MCP subprocess inside the agent container. No network service, no API dependency. Storage is a directory (`~/.mempalace/`) that can be mounted as a volume for persistence.

## Design

### Image Layer

Add a mempalace layer to the vafi image hierarchy:

```
vafi-base (node:20 + git + python + system tools)
└── vafi-claude (+ Claude Code CLI + cxtx)
    └── vafi-claude-mempalace (+ mempalace + embedding model)
        └── vafi-agent-mempalace (+ controller + methodologies)
```

New file: `images/mempalace/Dockerfile`

```dockerfile
ARG REGISTRY=vafi
FROM ${REGISTRY}/vafi-claude:latest

USER root
RUN pip install --break-system-packages mempalace

# Pre-download the 79MB embedding model so first search doesn't timeout
USER agent
RUN python3 -c "from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2; \
    ef = ONNXMiniLM_L6_V2(); ef._download_model_if_not_exists()"
RUN mkdir -p ~/.mempalace
```

The agent Dockerfile is already parameterized by `HARNESS_IMAGE`:

```bash
# Standard agent (no mempalace)
docker build --build-arg HARNESS_IMAGE=vafi/vafi-claude:latest -t vafi/vafi-agent:latest ...

# Agent with mempalace
docker build --build-arg HARNESS_IMAGE=vafi/vafi-claude-mempalace:latest -t vafi/vafi-agent-mempalace:latest ...
```

### MCP Registration

The entrypoint injects mempalace into the Claude Code MCP config at container start. This follows the same pattern as vtf and cxdb MCP registration in `images/claude/init.sh`:

```python
# In init.sh, alongside existing vtf/cxdb MCP registration
cfg.setdefault("mcpServers", {})["mempalace"] = {
    "command": "python3",
    "args": ["-m", "mempalace.mcp_server"]
}
```

Stdio transport — Claude Code spawns the process, communicates via stdin/stdout. No network service needed.

### Palace Scoping

Not everything shares one brain. Palaces are isolated at the storage level — separate volumes, hard boundaries.

| Scope | What it contains | Storage | Who accesses it |
|---|---|---|---|
| **Personal default** | Developer's general knowledge | Named volume `mempalace-default` | All local `claude-mempalace` sessions |
| **Customer isolated** | Sensitive customer project data | Named volume `mempalace-{customer}` | Only sessions launched for that customer |
| **Org shared (k8s)** | Cross-project patterns, gotchas | PVC `mempalace-org` | All vafi agent pods |
| **Project scoped (k8s)** | Project-specific decisions, conventions | PVC `mempalace-proj-{slug}` | Agents working on that project |

Palace selection is a launch-time parameter. The container image is identical — only the volume mount for `~/.mempalace` changes.

Customer isolation is a hard requirement: customer knowledge must never leak into the default palace or other customer palaces. This is enforced by mounting different volumes, not by in-application access control.

### Local Developer Usage

A shell function launches the container as if running `claude` natively:

```bash
claude-mempalace() {
    local palace="${1:-default}"
    local workdir="${2:-.}"

    docker run -it --rm \
        --name "claude-mp-$$-$(date +%s)" \
        -v "${HOME}/.claude:/home/agent/.claude-host:ro" \
        -v "${HOME}/.claude.json:/home/agent/.claude-host.json:ro" \
        -v "mempalace-${palace}:/home/agent/.mempalace" \
        -v "$(realpath "$workdir"):/workspace" \
        harbor.viloforge.com/vafi/vafi-claude-mempalace:latest
    }
```

Usage:

```bash
# Default palace — general development knowledge
claude-mempalace

# Customer project — isolated memory
claude-mempalace customer-acme ~/projects/acme-app

# Specific vtf project
claude-mempalace vtf-grafana-alerts ~/GitHub/grafana-alerts
```

Multiple terminals, multiple instances, all running concurrently. Instances sharing the same palace name share the same memory. Instances with different palace names are fully isolated.

Auth comes from the mounted `~/.claude` directory (config-dir pattern). The entrypoint runs as root to copy the mode-600 `.credentials.json`, injects the mempalace MCP server, then drops to the `agent` user.

### k8s / vafi Fleet Usage

Agent pods mount a mempalace PVC alongside the existing sessions PVC:

```yaml
# In Helm chart values
mempalace:
  enabled: false          # opt-in
  orgPalace:
    enabled: true
    storage: 5Gi
```

When enabled, executor and judge deployments get an additional volume mount:

```yaml
volumeMounts:
  - name: sessions
    mountPath: /sessions
  - name: mempalace
    mountPath: /home/agent/.mempalace
```

The controller doesn't need changes — mempalace is an MCP tool available to the agent, not a controller concern. The agent decides when to search, write, or read from memory based on its methodology.

### What This Does NOT Do

- **Replace vfkb** — MemPalace is local agent memory. vfkb is organizational knowledge with REST API, multi-user access, and curator workflows. They serve different purposes and may eventually feed each other.
- **Network service** — MemPalace MCP is stdio-only. Shared memory comes from shared volumes, not from a server.
- **Automatic knowledge extraction** — Agents use mempalace tools explicitly. Automatic summarization into mempalace (post-task mining) is future work.
- **Cross-palace search** — Each palace is fully isolated. No federated search across palaces.

## Implementation Sequence

1. `images/mempalace/Dockerfile` — mempalace layer on vafi-claude
2. `images/agent/Dockerfile` — verify HARNESS_IMAGE parameterization works with mempalace layer
3. `images/claude/init.sh` — add mempalace MCP registration (gated on `MEMPALACE_ENABLED` env var)
4. Build + push to Harbor
5. Shell wrapper `claude-mempalace` for local use
6. Test: local interactive session with palace persistence across restarts
7. Test: two concurrent sessions sharing a palace
8. Test: isolated palace for customer project
9. Helm chart changes for k8s (opt-in mempalace PVC)
10. Test: agent pod with mempalace in vafi-dev

## Open Questions

1. **Palace management CLI** — How does a user list, delete, export palaces? Thin wrapper around `docker volume ls/rm` for local, `kubectl get pvc` for k8s? Or a subcommand of `claude-mempalace`?

2. **Methodology updates** — Should agent methodologies (executor.md, judge.md) include instructions for when to read/write mempalace? Or let agents discover the tools organically via MCP?

3. **Mining existing data** — Should the entrypoint auto-mine the workdir on startup (`mempalace mine /workspace`)? Or leave it to the agent to decide?

4. **Image size** — MemPalace adds ChromaDB, onnxruntime, numpy, tokenizers (~200MB). Acceptable for pods with mempalace, but should not bloat the standard vafi-claude image. The separate layer ensures opt-in.

5. **Embedding model updates** — The ONNX MiniLM-L6-V2 model is baked into the image. How do we handle model updates? Rebuild the image, or download at runtime from a cache?
