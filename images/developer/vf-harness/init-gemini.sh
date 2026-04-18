# vf-harness init-gemini.sh — Gemini CLI setup.
# Sourced by /opt/vf-harness/init.sh. Runs as agent user.
#
# Auth: GEMINI_API_KEY (read directly by gemini CLI — no config-file marshalling needed).

mkdir -p "$HOME/.gemini"

if [ -n "${GEMINI_API_KEY:-}" ]; then
  echo >&2 "[gemini] Auth: GEMINI_API_KEY"
else
  echo >&2 "[gemini] WARNING: GEMINI_API_KEY not set"
fi

# Register mempalace MCP server (idempotent via gemini mcp list check)
if ! gemini mcp list 2>/dev/null | grep -q mempalace; then
  gemini mcp add --scope user mempalace python3 -- -m mempalace.mcp_server 2>/dev/null || true
fi

# MediaWiki MCP server (conditional on MW_API_HOST)
if [ -n "${MW_API_HOST:-}" ]; then
  if ! gemini mcp list 2>/dev/null | grep -q mediawiki; then
    gemini mcp add --scope user mediawiki mcp-mediawiki -- --transport stdio 2>/dev/null || true
  fi
fi

export VF_HARNESS=gemini
