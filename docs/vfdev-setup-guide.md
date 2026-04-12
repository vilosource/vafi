# vfdev Setup Guide

How to set up the `vfdev` viloforge developer environment from scratch. This covers the shell function, directory layout, shared MCP servers, SSH keys, and all the gotchas we hit.

## Prerequisites

- Docker installed and running
- `vafi/vafi-developer:latest` image built (`cd ~/GitHub/vafi && make build-developer`)
- Anthropic OAuth credentials at `~/.claude/.credentials.json` (from Claude Code login)

## Step 1: Shared MCP Servers

Start the shared Playwright MCP server **before** any dev containers. Dev containers connect to it via Docker network.

```bash
cd ~/GitHub/vafi
make mcp-up
make mcp-status   # verify: playwright-mcp running on :8931
```

This creates the `vafi-mcp` Docker network. Dev containers must join this network.

### Gotchas

- **Playwright rejects non-localhost connections**: The official image validates the `Host` header. We use `--allowed-hosts playwright-mcp:8931,localhost` to allow container-to-container access via DNS name.
- **Playwright needs a writable `/workspace`**: The image tries to `mkdir /workspace` for browser user data. We mount a `tmpfs` at `/workspace` inside the Playwright container (not related to your workspace).
- **`host.docker.internal` does NOT work for this**: Even though it resolves, Playwright rejects the Host header. Use the Docker network + container name instead.

## Step 2: Shell Function

Add `vfdev` to `~/.bashrc`:

```bash
# viloforge developer container — bind-mount layout at ~/VF
vfdev() {
  local vf_root="$HOME/VF"
  local agent_home="${vf_root}/home/agent"
  local workspace="${vf_root}/workspace"

  # First-run: create directory structure
  if [ ! -d "$agent_home" ] || [ ! -d "$workspace" ]; then
    echo "[vfdev] First run — creating ${vf_root}/{home/agent,workspace}"
    mkdir -p "$agent_home" "$workspace"
    # Container runs as agent (uid=1001) — must own its home and workspace
    sudo chown 1001:1001 "$agent_home" "$workspace"
  fi

  # OAuth auth: read credentials file and pass content as env var
  local creds="$HOME/.claude/.credentials.json"
  local env_args=()
  if [ -f "$creds" ]; then
    env_args+=(-e "CLAUDE_CREDENTIALS=$(cat "$creds")")
  else
    echo "[vfdev] WARNING: $creds not found — container will have no auth"
  fi

  # Auto-init palace on first run (when .mempalace doesn't exist yet)
  if [ ! -d "${agent_home}/.mempalace/palace" ]; then
    env_args+=(-e "MEMPALACE_AUTO_INIT=true")
  fi

  docker run -it --rm \
    --name "vfdev-$$-$(date +%s)" \
    --network vafi-mcp \
    "${env_args[@]}" \
    -v "${agent_home}:/home/agent" \
    -v "${workspace}:/workspace" \
    vafi/vafi-developer:latest \
    "$@"
}
```

Then `source ~/.bashrc`.

### Key Differences from ogcli

| | ogcli | vfdev |
|---|---|---|
| Home | Named Docker volume (`mempalace-og-home`) | Bind mount (`~/VF/home/agent`) |
| Workspace | Bind mount (`~/OG`) | Bind mount (`~/VF/workspace`) |
| Launcher | `scripts/claude-mempalace` | Direct `docker run` |
| MediaWiki | Yes (OG wiki) | No |
| Network | Default bridge | `vafi-mcp` (for Playwright) |

### Gotchas

- **UID mismatch**: Host user is uid=1000, container agent is uid=1001. Bind-mounted directories must be `chown 1001:1001` or the entrypoint fails with `Permission denied, mkdir '/home/agent/.claude'`. The function handles this on first run with `sudo chown`.
- **Both dirs need chown**: Not just `home/agent` — `workspace` also needs it. The container shows `/workspace is owned by node` (uid=1000 from the base image) otherwise.
- **`--network vafi-mcp`**: Required for Playwright MCP. If you forget this, Playwright tools won't connect (container can't resolve `playwright-mcp` hostname).

## Step 3: Directory Layout

After first run, you'll have:

```
~/VF/
├── home/
│   └── agent/                  # /home/agent inside container
│       ├── .claude/            # Claude Code config, sessions, hooks
│       ├── .claude.json        # MCP servers, project trust, runtime state
│       ├── .mempalace/         # MemPalace data (ChromaDB, knowledge graph)
│       ├── .ssh/               # SSH keys (manually provisioned, see Step 4)
│       └── .config/glab-cli/   # GitLab CLI (if GITLAB_TOKEN set)
└── workspace/                  # /workspace inside container
    └── (repos cloned here)     # directly visible on host
```

Everything under `~/VF/` is persistent across container restarts.

## Step 4: SSH Keys

The container has no SSH keys by default. Copy them from the host:

```bash
# Create .ssh dir with correct ownership
sudo mkdir -p ~/VF/home/agent/.ssh

# Copy keys
sudo cp ~/.ssh/id_rsa ~/VF/home/agent/.ssh/
sudo cp ~/.ssh/config ~/VF/home/agent/.ssh/
sudo cp ~/.ssh/known_hosts ~/VF/home/agent/.ssh/

# Copy additional keys as needed
for key in ansible.priv azure_ansible ansible_hyperv_lab kuja_ed25519 gitlab_ed25519; do
  sudo cp ~/.ssh/$key ~/VF/home/agent/.ssh/ 2>/dev/null
done

# Fix paths in config (host paths → container paths)
sudo sed -i 's|/home/jasonvi/.ssh|/home/agent/.ssh|g' ~/VF/home/agent/.ssh/config
sudo sed -i 's|~/.ssh|/home/agent/.ssh|g' ~/VF/home/agent/.ssh/config

# Fix ownership and permissions
sudo chown -R 1001:1001 ~/VF/home/agent/.ssh
sudo chmod 700 ~/VF/home/agent/.ssh
sudo chmod 600 ~/VF/home/agent/.ssh/id_rsa
sudo chmod 600 ~/VF/home/agent/.ssh/ansible.priv ~/VF/home/agent/.ssh/azure_ansible \
  ~/VF/home/agent/.ssh/ansible_hyperv_lab ~/VF/home/agent/.ssh/kuja_ed25519 \
  ~/VF/home/agent/.ssh/gitlab_ed25519 2>/dev/null
sudo chmod 644 ~/VF/home/agent/.ssh/config ~/VF/home/agent/.ssh/known_hosts
```

### Gotchas

- **Fuji uses `id_rsa`**: Not `ansible.priv` or `kuja_ed25519`. If SSH to `ansible@192.168.2.91` fails with "Permission denied", check which key the host uses: `ssh -v ansible@192.168.2.91 2>&1 | grep Offering`.
- **Path rewrite is essential**: The host SSH config references `/home/jasonvi/.ssh/` but inside the container it's `/home/agent/.ssh/`. The `sed` command fixes this.
- **No Fuji entry in SSH config**: There's no `Host` entry for 192.168.2.91 in the SSH config. SSH falls back to `id_rsa` as the default key — which is why it must be copied.

## Step 5: Verify Everything

Run these checks in order:

```bash
# 1. Shared MCP server running
make mcp-status

# 2. Launch vfdev
source ~/.bashrc
vfdev

# 3. Inside the container, check MCP servers
claude mcp list
# Should show: mempalace ✓ Connected, playwright ✓ Connected

# 4. Test Playwright
# Ask Claude to navigate to https://example.com

# 5. Test SSH
ssh -o ConnectTimeout=5 ansible@192.168.2.91 'echo connected'

# 6. Test kubectl (after fetching kubeconfig)
mkdir -p ~/.kube
ssh ansible@192.168.2.91 'sudo cat /etc/rancher/k3s/k3s.yaml' > ~/.kube/config
sed -i 's|127.0.0.1|192.168.2.91|' ~/.kube/config
kubectl get nodes
```

## MCP Server Registration — Lessons Learned

**Do NOT manually write `mcpServers` to `~/.claude.json` or `~/.claude/settings.json`.** Claude Code 2.x ignores manually written MCP server entries even though the JSON structure looks identical to what works.

**Use `claude mcp add` instead.** This is what the entrypoint does:

```bash
# stdio server
claude mcp add mempalace -- python3 -m mempalace.mcp_server

# remote HTTP server
claude mcp add --transport http playwright http://playwright-mcp:8931/mcp
```

The entrypoint runs these on every container start. They're idempotent — re-adding an existing server just overwrites it.

**Do NOT put `mcpServers` in `settings.json`.** We tried this and it caused conflicts — Claude Code ignored both the settings.json and .claude.json entries.

## Rebuilding After Changes

If you modify the entrypoint or Dockerfiles:

```bash
cd ~/GitHub/vafi
make build-developer    # rebuilds devtools → developer chain
make mcp-down && make mcp-up  # restart shared MCP servers if compose changed
```

The entrypoint regenerates config on every container start, so image rebuilds take effect immediately.

## Disabling Playwright

If the Playwright MCP server isn't running and you don't want connection warnings:

```bash
PLAYWRIGHT_MCP_URL="" vfdev
```

## Quick Recovery Checklist

If everything is wiped and you need to start over:

1. `cd ~/GitHub/vafi && make build-developer` — build the image
2. `make mcp-up` — start Playwright MCP
3. Add `vfdev` function to `~/.bashrc` (copy from above) and `source ~/.bashrc`
4. `vfdev` — first run creates `~/VF/` dirs with correct ownership
5. Exit, then copy SSH keys (Step 4 above)
6. `vfdev` again — full environment ready
