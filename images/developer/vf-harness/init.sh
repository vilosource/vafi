#!/bin/bash
# vf-harness init.sh — generic entrypoint for vafi-developer images.
#
# Dispatches harness-specific setup based on $VF_HARNESS (set by the leaf's ENV),
# then runs common post-init (glab, mempalace auto-init), then execs the CMD.
#
# Runs as agent user (NO ROOT).
set -e

mkdir -p "$HOME/.config"

HARNESS="${VF_HARNESS:-claude}"

# --- Harness-specific setup ---

case "$HARNESS" in
  claude)
    source /opt/vf-harness/init-claude.sh
    ;;
  pi)
    source /opt/vf-harness/init-pi.sh
    ;;
  gemini)
    source /opt/vf-harness/init-gemini.sh
    ;;
  *)
    echo >&2 "[vf-harness] Unknown VF_HARNESS=$HARNESS — skipping harness init"
    ;;
esac

# --- Common: glab (GitLab CLI) ---

if [ -n "${GITLAB_TOKEN:-}" ]; then
  mkdir -p "$HOME/.config/glab-cli"
  cat > "$HOME/.config/glab-cli/config.yml" <<GLEOF
hosts:
  ${GITLAB_HOST:-gitlab.optiscangroup.com}:
    token: ${GITLAB_TOKEN}
    api_host: ${GITLAB_HOST:-gitlab.optiscangroup.com}
    api_protocol: https
    git_protocol: ssh
GLEOF
  chmod 600 "$HOME/.config/glab-cli/config.yml"
  echo >&2 "[vf-harness] glab: configured for ${GITLAB_HOST:-gitlab.optiscangroup.com}"
fi

# --- Common: mempalace auto-init ---
# mempalace init prints a multi-line banner to stdout. That would mangle the
# JSON output of /opt/vf-harness/run.sh in non-interactive use. Suppress all
# of it — we log our own short "Auto-initializing" note to stderr.

if [ ! -d "$HOME/.mempalace/palace" ] && [ "${MEMPALACE_AUTO_INIT:-false}" = "true" ]; then
  echo >&2 "[vf-harness] Auto-initializing empty mempalace"
  mempalace init /workspace --yes >/dev/null 2>&1 || true
fi

# --- Launch ---

cd /workspace
exec "$@"
