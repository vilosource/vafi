# vf-harness init-claude.sh — Claude Code setup.
# Sourced by /opt/vf-harness/init.sh. Runs as agent user.
#
# Auth sources (first match wins):
#   CLAUDE_CREDENTIALS   — full JSON blob written to ~/.claude/.credentials.json
#   ANTHROPIC_OAUTH_TOKEN — OAuth token
#   ANTHROPIC_API_KEY    — direct API key
#   ANTHROPIC_AUTH_TOKEN + ANTHROPIC_BASE_URL — z.ai or other Anthropic-compat proxy

if [ -n "${CLAUDE_CREDENTIALS:-}" ]; then
  mkdir -p "$HOME/.claude"
  echo "$CLAUDE_CREDENTIALS" > "$HOME/.claude/.credentials.json"
  chmod 600 "$HOME/.claude/.credentials.json"
  unset CLAUDE_CREDENTIALS
  echo >&2 "[claude] Auth: OAuth credentials"
elif [ -n "${ANTHROPIC_OAUTH_TOKEN:-}" ]; then
  echo >&2 "[claude] Auth: ANTHROPIC_OAUTH_TOKEN"
elif [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  echo >&2 "[claude] Auth: ANTHROPIC_API_KEY"
elif [ -n "${ANTHROPIC_AUTH_TOKEN:-}" ]; then
  echo >&2 "[claude] Auth: ANTHROPIC_AUTH_TOKEN (proxy: ${ANTHROPIC_BASE_URL:-unset})"
else
  echo >&2 "[claude] WARNING: No Claude auth configured"
fi

# Build ~/.claude.json with onboarding flags + mempalace MCP
python3 <<'PYEOF'
import json, os

cfg_path = os.path.expanduser("~/.claude.json")
try:
    with open(cfg_path) as f:
        cfg = json.load(f)
except Exception:
    cfg = {}

cfg["hasCompletedOnboarding"] = True
cfg["autoUpdates"] = False
cfg["installMethod"] = "npm"

servers = cfg.setdefault("mcpServers", {})
servers.setdefault("mempalace", {
    "command": "python3",
    "args": ["-m", "mempalace.mcp_server"],
})

mw_host = os.environ.get("MW_API_HOST", "")
if mw_host:
    servers["mediawiki"] = {
        "command": "mcp-mediawiki",
        "args": ["--transport", "stdio"],
        "env": {
            "MW_API_HOST": mw_host,
            "MW_API_PATH": os.environ.get("MW_API_PATH", "/"),
            "MW_USE_HTTPS": os.environ.get("MW_USE_HTTPS", "true"),
            "MW_BOT_USER": os.environ.get("MW_BOT_USER", ""),
            "MW_BOT_PASS": os.environ.get("MW_BOT_PASS", ""),
        },
    }

vtf_url = os.environ.get("VF_VTF_MCP_URL", "")
vtf_token = os.environ.get("VF_VTF_TOKEN", "")
if vtf_url and vtf_token:
    servers["vtf"] = {
        "type": "http",
        "url": vtf_url,
        "headers": {"Authorization": f"Token {vtf_token}"},
    }

playwright_url = os.environ.get("VF_PLAYWRIGHT_MCP_URL", "")
if playwright_url:
    servers["playwright"] = {
        "type": "http",
        "url": playwright_url,
    }

projects = cfg.setdefault("projects", {})
projects["/workspace"] = {
    "hasTrustDialogAccepted": True,
    "hasCompletedProjectOnboarding": True,
}

with open(cfg_path, "w") as f:
    json.dump(cfg, f, indent=2)

os.makedirs(os.path.expanduser("~/.claude"), exist_ok=True)
PYEOF

# Writable runtime dirs Claude expects
for d in session-env projects plans history cache; do
  mkdir -p "$HOME/.claude/$d"
done

# --- Wire hook bundles into ~/.claude/settings.json ---
# See /opt/vf-harness/hooks.d/README.md for the bundle spec.
python3 <<'PYEOF'
import json, os, sys

HOME = os.path.expanduser("~")
STATE_ROOT = f"{HOME}/.vf-hook-state"
os.makedirs(STATE_ROOT, exist_ok=True)
try:
    os.chmod(STATE_ROOT, 0o700)
except OSError:
    pass

settings = {"skipDangerousModePermissionPrompt": True}

disabled_raw = os.environ.get("VF_DISABLE_HOOKS", "").strip()
disable_all = (disabled_raw == "all")
disabled_set = set(
    x.strip() for x in disabled_raw.split(",") if x.strip() and x.strip() != "all"
)

def load_bundles():
    seen = {}
    for root in ["/opt/vf-harness/hooks.d", f"{HOME}/.vf-hooks.d"]:
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            bdir = os.path.join(root, name)
            if not os.path.isdir(bdir):
                continue
            # User-tree bundle with same name overrides image-tree bundle.
            seen[name] = bdir
    entries = list(seen.items())

    def priority(entry):
        name, bdir = entry
        meta = os.path.join(bdir, "bundle.json")
        try:
            with open(meta) as f:
                return int(json.load(f).get("priority", 50))
        except Exception:
            return 50

    entries.sort(key=lambda e: (priority(e), e[0]))
    return entries

def subst(text, bundle_dir, bundle_name):
    state_dir = f"{STATE_ROOT}/{bundle_name}"
    os.makedirs(state_dir, exist_ok=True)
    return (text
        .replace("{{DIR}}", bundle_dir)
        .replace("{{BUNDLE}}", bundle_name)
        .replace("{{STATE}}", state_dir)
        .replace("{{WORKSPACE}}", "/workspace")
        .replace("{{HOME}}", HOME))

merged_hooks = {}
if not disable_all:
    for name, bdir in load_bundles():
        if name in disabled_set:
            print(f"[vf-harness] hooks: skipping {name} (disabled)", file=sys.stderr)
            continue
        harness_dir = os.path.join(bdir, "claude")
        frag_path = os.path.join(harness_dir, "hooks.json")
        if not os.path.isfile(frag_path):
            continue
        try:
            with open(frag_path) as f:
                raw = f.read()
            frag = json.loads(subst(raw, harness_dir, name))
        except Exception as e:
            print(f"[vf-harness] WARN: bundle {name} skipped (invalid claude/hooks.json: {e})", file=sys.stderr)
            continue
        for event, entries in (frag.get("hooks") or {}).items():
            merged_hooks.setdefault(event, []).extend(entries)
        print(f"[vf-harness] hooks: wired {name} (claude)", file=sys.stderr)
else:
    print("[vf-harness] hooks: disabled via VF_DISABLE_HOOKS=all", file=sys.stderr)

if merged_hooks:
    settings["hooks"] = merged_hooks

with open(f"{HOME}/.claude/settings.json", "w") as f:
    json.dump(settings, f, indent=2)
PYEOF

export VF_HARNESS=claude
