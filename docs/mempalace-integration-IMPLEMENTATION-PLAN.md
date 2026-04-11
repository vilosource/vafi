# MemPalace Integration — Implementation Plan

**Date:** 2026-04-11
**Design:** mempalace-integration-DESIGN.md
**Repo:** vilosource/vafi

## Definition of Done

The integration is done when:

1. **A vafi-claude-mempalace image exists** in Harbor with mempalace installed and the embedding model pre-downloaded. Building it is a single `make` target.

2. **A developer can run `claude-mempalace` from any terminal** and get an interactive Claude Code session with mempalace MCP tools available. Auth comes from the host `~/.claude` directory. No manual setup beyond pulling the image.

3. **Palace isolation works.** Two sessions launched with different palace names have completely separate memory. A session launched with the default palace cannot see data from a customer palace.

4. **Multiple concurrent sessions work.** Three terminals running `claude-mempalace default` simultaneously can all read/write to the same palace without corruption.

5. **k8s agent pods can opt in** to mempalace via Helm values. When enabled, agents have persistent memory across task executions.

### Acceptance Criteria

**AC-1: Image builds cleanly**
`make build-mempalace` produces `vafi/vafi-claude-mempalace:latest`. Image size is under 800MB. `mempalace --help` works inside the container.

**AC-2: Local interactive session**
Run `claude-mempalace`. Claude Code starts with mempalace MCP tools visible. Search, diary write, and knowledge graph tools all work. Exit and run again — memories persist.

**AC-3: Palace isolation**
Run `claude-mempalace default` and add a memory. Run `claude-mempalace customer-x` and search for that memory — not found. Run `claude-mempalace default` again — memory is there.

**AC-4: Concurrent sessions**
Open two terminals. Both run `claude-mempalace default`. Both can search and write memories. No SQLite locking errors. Memories written in one session are findable in the other.

**AC-5: k8s agent pod**
Deploy executor with mempalace enabled to vafi-dev. Agent claims a task, uses mempalace tools during execution. After task completes, launch another task — agent can find memories from the previous execution.

**AC-6: Agent image parameterization**
`vafi-agent-mempalace` builds from `vafi-claude-mempalace` using the existing `HARNESS_IMAGE` build arg. Controller, methodologies, and entrypoint all work unchanged.

---

## Phase 1: Image Layer

**Goal:** Build vafi-claude-mempalace image with mempalace installed and working.

**Files:**

```
images/mempalace/Dockerfile    — new, mempalace layer on vafi-claude
Makefile                       — add build-mempalace target
scripts/build-images.sh        — add mempalace to build chain
```

**Dockerfile:**

```dockerfile
ARG REGISTRY=vafi
FROM ${REGISTRY}/vafi-claude:latest

USER root
RUN pip install --break-system-packages mempalace

USER agent
RUN python3 -c "from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2; \
    ef = ONNXMiniLM_L6_V2(); ef._download_model_if_not_exists()"
RUN mkdir -p ~/.mempalace
```

**Makefile targets:**

```makefile
build-mempalace:
	docker build -t $(REGISTRY)/vafi-claude-mempalace:latest \
		--build-arg REGISTRY=$(REGISTRY) \
		-f images/mempalace/Dockerfile .

build-agent-mempalace:
	docker build -t $(REGISTRY)/vafi-agent-mempalace:latest \
		--build-arg HARNESS_IMAGE=$(REGISTRY)/vafi-claude-mempalace:latest \
		-f images/agent/Dockerfile .
```

**Verification:**

```bash
# Image builds
make build-mempalace

# mempalace CLI works
docker run --rm vafi/vafi-claude-mempalace:latest mempalace --help

# MCP server module loads
docker run --rm vafi/vafi-claude-mempalace:latest \
    python3 -c "from mempalace.mcp_server import TOOLS; print(f'{len(TOOLS)} tools')"

# Embedding model is pre-downloaded (no network fetch)
docker run --rm --network none vafi/vafi-claude-mempalace:latest \
    python3 -c "from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2; \
    ef = ONNXMiniLM_L6_V2(); print('model ready')"
```

**Done when:** AC-1 passes. Image builds, mempalace works, embedding model is baked in.

---

## Phase 2: MCP Registration in init.sh

**Goal:** When `MEMPALACE_ENABLED=true`, init.sh registers mempalace as an MCP server in Claude Code config.

**Files:**

```
images/claude/init.sh          — add mempalace MCP registration block
```

**Change:** Add a block after the existing cxdb MCP registration:

```python
mempalace = os.environ.get("MEMPALACE_ENABLED", "")
if mempalace.lower() in ("true", "1", "yes"):
    cfg.setdefault("mcpServers", {})["mempalace"] = {
        "command": "python3",
        "args": ["-m", "mempalace.mcp_server"]
    }
```

Gated on `MEMPALACE_ENABLED` so existing images that source init.sh are unaffected.

**Verification:**

```bash
# With flag: mempalace registered
docker run --rm -e MEMPALACE_ENABLED=true vafi/vafi-claude-mempalace:latest \
    bash -c "source /opt/vf-harness/init.sh && python3 -c \"
import json
with open('/home/agent/.claude.json') as f:
    print('mempalace' in json.load(f).get('mcpServers', {}))
\""
# → True

# Without flag: mempalace not registered
docker run --rm vafi/vafi-claude-mempalace:latest \
    bash -c "source /opt/vf-harness/init.sh && python3 -c \"
import json
with open('/home/agent/.claude.json') as f:
    print('mempalace' in json.load(f).get('mcpServers', {}))
\""
# → False
```

**Done when:** init.sh registers mempalace MCP when env var is set, does nothing when unset.

---

## Phase 3: Local Entrypoint + Shell Wrapper

**Goal:** A developer runs `claude-mempalace` and gets an interactive session with auth from host `~/.claude` and mempalace tools available.

**Files:**

```
images/mempalace/entrypoint-local.sh   — copies host auth, injects MCP, drops to agent
scripts/claude-mempalace               — shell wrapper for local use
```

**Entrypoint** (runs as root to handle mode-600 credentials, drops to agent):

1. Copy `~/.claude-host.json` → `~/.claude.json` (writable)
2. Copy `.credentials.json` and `settings.json` from mounted `.claude-host/` (root reads mode-600, copies with agent ownership)
3. Symlink remaining `.claude-host/` subdirs into `.claude/`
4. Inject mempalace MCP server into `.claude.json`
5. Trust the `/workspace` project directory
6. `exec su agent` to run the command

**Shell wrapper:**

```bash
#!/bin/bash
# claude-mempalace — Claude Code with persistent MemPalace memory
#
# Usage:
#   claude-mempalace [palace] [workdir]
#   claude-mempalace                          # default palace, current dir
#   claude-mempalace customer-acme ~/project  # isolated palace, specific dir

set -euo pipefail

PALACE="${1:-default}"
WORKDIR="${2:-.}"
IMAGE="${MEMPALACE_IMAGE:-harbor.viloforge.com/vafi/vafi-claude-mempalace:latest}"

exec docker run -it --rm \
    --name "claude-mp-$$-$(date +%s)" \
    -v "${HOME}/.claude:/home/agent/.claude-host:ro" \
    -v "${HOME}/.claude.json:/home/agent/.claude-host.json:ro" \
    -v "mempalace-${PALACE}:/home/agent/.mempalace" \
    -v "$(realpath "$WORKDIR"):/workspace" \
    --entrypoint /opt/mempalace/entrypoint-local.sh \
    "$IMAGE" \
    claude --dangerously-skip-permissions
```

**Verification:**

```bash
# AC-2: Interactive session works
claude-mempalace
# → Claude Code starts, mempalace tools visible in /mcp

# AC-3: Palace isolation
claude-mempalace alpha   # write a memory
claude-mempalace beta    # search for it → not found
claude-mempalace alpha   # search for it → found

# AC-4: Concurrent sessions
# Terminal 1:
claude-mempalace default
# Terminal 2:
claude-mempalace default
# Both running, both can read/write
```

**Done when:** AC-2, AC-3, AC-4 pass.

---

## Phase 4: Push to Harbor

**Goal:** Images are available in Harbor for pull without local builds.

**Commands:**

```bash
make build-mempalace
make build-agent-mempalace
docker tag vafi/vafi-claude-mempalace:latest harbor.viloforge.com/vafi/vafi-claude-mempalace:latest
docker tag vafi/vafi-agent-mempalace:latest harbor.viloforge.com/vafi/vafi-agent-mempalace:latest
docker push harbor.viloforge.com/vafi/vafi-claude-mempalace:latest
docker push harbor.viloforge.com/vafi/vafi-agent-mempalace:latest
```

Add to `scripts/push-images.sh` alongside existing images.

**Done when:** `docker pull harbor.viloforge.com/vafi/vafi-claude-mempalace:latest` works from any machine with Harbor access.

---

## Phase 5: k8s Helm Integration

**Goal:** Agent pods can opt in to mempalace via Helm values.

**Files:**

```
charts/vafi/values.yaml                        — add mempalace section
charts/vafi/templates/mempalace-pvc.yaml       — new, org palace PVC
charts/vafi/templates/executor-deployment.yaml — conditional mempalace volume mount
charts/vafi/templates/judge-deployment.yaml    — conditional mempalace volume mount
charts/vafi/templates/_helpers.tpl             — add MEMPALACE_ENABLED env var
```

**Values:**

```yaml
mempalace:
  enabled: false
  storage: 5Gi
  storageClassName: ""
  image:
    agent:
      repository: vafi-agent-mempalace
      tag: latest
```

When `mempalace.enabled: true`:
- Create `mempalace-org` PVC
- Mount it at `/home/agent/.mempalace` in executor and judge pods
- Set `MEMPALACE_ENABLED=true` env var
- Use `mempalace.image.agent` instead of default `image.agent`

**Verification:**

```bash
# Helm template renders correctly
helm template vafi charts/vafi --set mempalace.enabled=true | grep -A5 mempalace

# AC-5: Deploy to vafi-dev, run a task with mempalace
helm upgrade vafi charts/vafi -n vafi-dev --set mempalace.enabled=true
# Submit task → executor uses mempalace → memories persist across tasks

# AC-6: Agent image works
# vafi-agent-mempalace runs controller, claims tasks, completes them
```

**Done when:** AC-5, AC-6 pass. Mempalace is opt-in with zero impact on existing deployments.

---

## Phase Summary

| Phase | What | Depends on | Effort |
|---|---|---|---|
| 1 | Image layer (Dockerfile + Makefile) | Nothing | Low |
| 2 | MCP registration in init.sh | Phase 1 | Low |
| 3 | Local entrypoint + shell wrapper | Phase 2 | Medium |
| 4 | Push to Harbor | Phase 3 | Low |
| 5 | k8s Helm integration | Phase 4 | Medium |

Phases 1-4 deliver the local developer workflow. Phase 5 adds k8s fleet support.
