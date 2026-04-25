#!/usr/bin/env bash
# new-hook-bundle.sh — scaffold a new hook bundle for the vafi-developer images.
#
# See images/developer/hooks.d/README.md for the full bundle spec.
#
# Usage:
#   ./scripts/new-hook-bundle.sh <bundle-name> [--harnesses <list>]
#
# Args:
#   <bundle-name>        short name (lowercase; alphanumeric + hyphens)
#   --harnesses <list>   comma-separated subset of {claude,pi} (default: claude,pi)
#
# Example:
#   ./scripts/new-hook-bundle.sh vtf-journal --harnesses claude

set -euo pipefail

usage() {
  sed -n '3,14p' "$0" >&2
  exit 2
}

NAME="${1:-}"
[ -z "$NAME" ] && usage
shift

HARNESSES="claude,pi"
while [ $# -gt 0 ]; do
  case "$1" in
    --harnesses) HARNESSES="${2:-}"; shift 2 ;;
    -h|--help)   usage ;;
    *) echo "unknown arg: $1" >&2; usage ;;
  esac
done

if [[ ! "$NAME" =~ ^[a-z][a-z0-9-]*$ ]]; then
  echo "ERROR: bundle name must be lowercase alphanumeric with hyphens (got '$NAME')" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
HOOKS_D="${REPO_ROOT}/images/developer/hooks.d"
BUNDLE_DIR="${HOOKS_D}/${NAME}"

if [ -e "$BUNDLE_DIR" ]; then
  echo "ERROR: ${BUNDLE_DIR} already exists" >&2
  exit 1
fi

mkdir -p "$BUNDLE_DIR"

cat > "${BUNDLE_DIR}/bundle.json" <<EOF
{
  "name": "${NAME}",
  "version": "0.1.0",
  "description": "TODO: describe what this bundle does",
  "priority": 50
}
EOF

if [[ ",${HARNESSES}," == *",claude,"* ]]; then
  mkdir -p "${BUNDLE_DIR}/claude"

  cat > "${BUNDLE_DIR}/claude/hooks.json" <<'EOF'
{
  "hooks": {
    "Stop": [
      {
        "matcher": "*",
        "hooks": [
          { "type": "command", "command": "{{DIR}}/on-stop.sh", "timeout": 30 }
        ]
      }
    ]
  }
}
EOF

  cat > "${BUNDLE_DIR}/claude/on-stop.sh" <<EOF
#!/usr/bin/env bash
# Claude Stop hook for bundle: ${NAME}
#
# Input: JSON on stdin with transcript_path, session_id, stop_hook_active, ...
# Output: JSON on stdout — {} to let Stop proceed, or
#         {"decision":"block","reason":"..."} to have the AI do work and retry.
#
# State dir for this bundle: \$VF_BUNDLE_STATE_DIR  (same as {{STATE}})
# Log suggestion:            \$VF_BUNDLE_STATE_DIR/log

set -e

STATE="\${VF_BUNDLE_STATE_DIR:-\$HOME/.vf-hook-state/${NAME}}"
mkdir -p "\$STATE"
LOG="\$STATE/log"

# TODO: replace with real logic
{
  echo "[\$(date -Iseconds)] ${NAME} stop hook fired"
} >> "\$LOG" 2>&1

echo "{}"
EOF
  chmod +x "${BUNDLE_DIR}/claude/on-stop.sh"
fi

if [[ ",${HARNESSES}," == *",pi,"* ]]; then
  mkdir -p "${BUNDLE_DIR}/pi/extensions"
  cat > "${BUNDLE_DIR}/pi/extensions/${NAME}-hooks.ts" <<EOF
import { execSync } from "node:child_process";

// Pi extension for bundle: ${NAME}
// Events available: session_shutdown (≈ Stop), session_before_compact (≈ PreCompact).
export default (pi: any) => {
  pi.on("session_shutdown", async () => {
    try {
      // TODO: implement
      console.error("[${NAME}] session_shutdown");
    } catch {
      // Don't block shutdown on failure
    }
  });
};
EOF
fi

cat <<EOF

Created: ${BUNDLE_DIR}

Next steps:
  1. Edit ${BUNDLE_DIR}/bundle.json (description, version).
  2. Replace the TODOs in the hook script(s) with real logic.
  3. Test without rebuilding the image:
       mkdir -p ~/DR/home/agent/.vf-hooks.d
       cp -r ${BUNDLE_DIR} ~/DR/home/agent/.vf-hooks.d/
       ogdr bash
       vf-hooks                      # verify bundle detected
       # trigger Stop by exiting claude; then:
       tail ~/.vf-hook-state/${NAME}/log
  4. When happy, rebuild for the baked-in version:
       ./scripts/build-developer-images.sh base && ./scripts/build-developer-images.sh claude
EOF
