# vf-harness init-pi.sh — Pi coding agent setup.
# Sourced by /opt/vf-harness/init.sh. Runs as agent user.
#
# Pi supports multiple providers via env vars (ANTHROPIC_API_KEY, GEMINI_API_KEY,
# OPENAI_API_KEY, ...). Default provider is google (Gemini).

mkdir -p "$HOME/.pi/agent/extensions"

# Ensure pi-mcp-adapter is in settings.json packages (merge, don't overwrite)
python3 <<'PYEOF'
import json, os

settings_path = os.path.expanduser("~/.pi/agent/settings.json")
try:
    with open(settings_path) as f:
        settings = json.load(f)
except Exception:
    settings = {}

packages = settings.get("packages", [])
if "npm:pi-mcp-adapter" not in packages:
    packages.append("npm:pi-mcp-adapter")
settings["packages"] = packages

with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
PYEOF

cp /opt/vf-harness/pi-extras/APPEND_SYSTEM.md \
   "$HOME/.pi/agent/APPEND_SYSTEM.md" 2>/dev/null || true

# --- Wire hook bundles into ~/.pi/agent/extensions/ ---
# See /opt/vf-harness/hooks.d/README.md for the bundle spec.
# Idempotent: strip prior vf-managed extensions, copy fresh from active bundles.
rm -f "$HOME/.pi/agent/extensions/vf-"*.ts 2>/dev/null || true

mkdir -p "$HOME/.vf-hook-state"
chmod 700 "$HOME/.vf-hook-state" 2>/dev/null || true

if [ "${VF_DISABLE_HOOKS:-}" = "all" ]; then
  echo >&2 "[vf-harness] hooks: disabled via VF_DISABLE_HOOKS=all"
else
  # User-tree bundles (~/.vf-hooks.d/) override image-tree (/opt/vf-harness/hooks.d/)
  # when they share a name. Track seen names to dedupe.
  _seen=""
  for root in /opt/vf-harness/hooks.d "$HOME/.vf-hooks.d"; do
    [ -d "$root" ] || continue
    for bdir in "$root"/*/; do
      [ -d "$bdir" ] || continue
      bname=$(basename "$bdir")
      case ",${VF_DISABLE_HOOKS:-}," in
        *",${bname},"*)
          echo >&2 "[vf-harness] hooks: skipping ${bname} (disabled)"
          continue ;;
      esac
      ext_dir="${bdir}pi/extensions"
      [ -d "$ext_dir" ] || continue
      mkdir -p "$HOME/.vf-hook-state/${bname}"
      # Copy all .ts files with vf-<bundle>- prefix
      wired=0
      for src in "$ext_dir"/*.ts; do
        [ -f "$src" ] || continue
        fname=$(basename "$src")
        cp "$src" "$HOME/.pi/agent/extensions/vf-${bname}-${fname}" 2>/dev/null && wired=1
      done
      [ $wired -eq 1 ] && echo >&2 "[vf-harness] hooks: wired ${bname} (pi)"
    done
  done
fi

# --- Auth ---
# Pi auto-discovers providers from env vars at runtime AND can override
# models.json selections. Pick ONE provider based on the first env var we
# see (priority: anthropic > gemini > openai), write models.json for it,
# and UNSET competing provider env vars so pi doesn't try them.
# Export VF_PI_PROVIDER / VF_PI_MODEL so run.sh can pass --provider explicitly.

if [ -n "${ANTHROPIC_AUTH_TOKEN:-}" ]; then
  python3 <<'PYEOF'
import json, os
provider = os.environ.get("VF_PI_PROVIDER", "anthropic")
model = os.environ.get("VF_PI_MODEL", "claude-sonnet-4-20250514")
base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.z.ai/api/anthropic")
models = {"providers": {provider: {
    "api": "anthropic-messages",
    "apiKey": "ANTHROPIC_AUTH_TOKEN",
    "models": [{"id": model, "name": model}],
    "baseUrl": base_url,
}}}
os.makedirs(os.path.expanduser("~/.pi/agent"), exist_ok=True)
with open(os.path.expanduser("~/.pi/agent/models.json"), "w") as f:
    json.dump(models, f, indent=2)
PYEOF
  echo >&2 "[pi] Auth: ANTHROPIC_AUTH_TOKEN via ${ANTHROPIC_BASE_URL:-z.ai}"
  unset GEMINI_API_KEY OPENAI_API_KEY GROQ_API_KEY OPENAI_BASE_URL OPENAI_API_BASE
  export VF_PI_PROVIDER="${VF_PI_PROVIDER:-anthropic}"
  export VF_PI_MODEL="${VF_PI_MODEL:-claude-sonnet-4-20250514}"
elif [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  python3 <<'PYEOF'
import json, os
model = os.environ.get("VF_PI_MODEL", "claude-sonnet-4-20250514")
models = {"providers": {"anthropic": {
    "api": "anthropic-messages",
    "apiKey": "ANTHROPIC_API_KEY",
    "models": [{"id": model, "name": model}],
}}}
os.makedirs(os.path.expanduser("~/.pi/agent"), exist_ok=True)
with open(os.path.expanduser("~/.pi/agent/models.json"), "w") as f:
    json.dump(models, f, indent=2)
PYEOF
  echo >&2 "[pi] Auth: ANTHROPIC_API_KEY"
  unset GEMINI_API_KEY OPENAI_API_KEY GROQ_API_KEY OPENAI_BASE_URL OPENAI_API_BASE ANTHROPIC_AUTH_TOKEN
  export VF_PI_PROVIDER="${VF_PI_PROVIDER:-anthropic}"
  export VF_PI_MODEL="${VF_PI_MODEL:-claude-sonnet-4-20250514}"
elif [ -n "${GEMINI_API_KEY:-}" ]; then
  python3 <<'PYEOF'
import json, os
model = os.environ.get("VF_PI_MODEL", "gemini-2.5-flash")
models = {"providers": {"google": {
    "api": "google-generative-ai",
    "apiKey": "GEMINI_API_KEY",
    "models": [{"id": model, "name": model}],
}}}
os.makedirs(os.path.expanduser("~/.pi/agent"), exist_ok=True)
with open(os.path.expanduser("~/.pi/agent/models.json"), "w") as f:
    json.dump(models, f, indent=2)
PYEOF
  echo >&2 "[pi] Auth: GEMINI_API_KEY (google provider)"
  unset OPENAI_API_KEY GROQ_API_KEY OPENAI_BASE_URL OPENAI_API_BASE ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_OAUTH_TOKEN
  export VF_PI_PROVIDER="${VF_PI_PROVIDER:-google}"
  export VF_PI_MODEL="${VF_PI_MODEL:-gemini-2.5-flash}"
elif [ -n "${OPENAI_API_KEY:-}" ]; then
  python3 <<'PYEOF'
import json, os
model = os.environ.get("VF_PI_MODEL", "gpt-4o-mini")
models = {"providers": {"openai": {
    "api": "openai-responses",
    "apiKey": "OPENAI_API_KEY",
    "models": [{"id": model, "name": model}],
}}}
os.makedirs(os.path.expanduser("~/.pi/agent"), exist_ok=True)
with open(os.path.expanduser("~/.pi/agent/models.json"), "w") as f:
    json.dump(models, f, indent=2)
PYEOF
  echo >&2 "[pi] Auth: OPENAI_API_KEY"
  unset GEMINI_API_KEY GROQ_API_KEY ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_OAUTH_TOKEN
  export VF_PI_PROVIDER="${VF_PI_PROVIDER:-openai}"
  export VF_PI_MODEL="${VF_PI_MODEL:-gpt-4o-mini}"
else
  echo >&2 "[pi] WARNING: No provider env var set (tried ANTHROPIC_*, GEMINI_API_KEY, OPENAI_API_KEY)"
fi

# --- MCP servers (~/.pi/agent/mcp.json) ---

python3 <<'PYEOF'
import json, os

mcp_path = os.path.expanduser("~/.pi/agent/mcp.json")
try:
    with open(mcp_path) as f:
        cfg = json.load(f)
except Exception:
    cfg = {}

servers = cfg.get("mcpServers", {})

servers["mempalace"] = {
    "command": "python3",
    "args": ["-m", "mempalace.mcp_server"],
    "lifecycle": "eager",
}

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
        "lifecycle": "eager",
    }

cfg["mcpServers"] = servers
os.makedirs(os.path.dirname(mcp_path), exist_ok=True)
with open(mcp_path, "w") as f:
    json.dump(cfg, f, indent=2)
PYEOF

export VF_HARNESS=pi
