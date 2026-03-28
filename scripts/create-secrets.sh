#!/usr/bin/env bash
set -euo pipefail

# Create vafi-agents secrets from local credentials.
# Idempotent — deletes and recreates if they already exist.
#
# Usage:
#   ./scripts/create-secrets.sh          # Create secrets with vtf-prod token (default)
#   ./scripts/create-secrets.sh --dev    # Create secrets with vtf-dev token (for smoke-test)
#
# Required environment:
#   ZAI_API_KEY     — z.ai API key for Claude access
#
# Required files:
#   ~/.ssh/github     — SSH private key for git clone
#   ~/.ssh/github.pub — SSH public key

export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/vafi-dev.yaml}"

NAMESPACE="vafi-agents"
ZAI_BASE_URL="${ZAI_BASE_URL:-https://api.z.ai/api/anthropic}"

# Default: vtf-prod. --dev flag switches to vtf-dev.
VTF_NAMESPACE="vtf-prod"
if [ "${1:-}" = "--dev" ]; then
    VTF_NAMESPACE="vtf-dev"
fi

die() { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }
ok() { echo "  OK: $*"; }

# --- Validate prerequisites ---

[ -n "${ZAI_API_KEY:-}" ] || die "ZAI_API_KEY not set"
[ -f "$HOME/.ssh/github" ] || die "SSH key not found: ~/.ssh/github"
[ -f "$HOME/.ssh/github.pub" ] || die "SSH public key not found: ~/.ssh/github.pub"

kubectl get ns "$NAMESPACE" &>/dev/null || die "Namespace $NAMESPACE does not exist"
kubectl get ns "$VTF_NAMESPACE" &>/dev/null || die "Namespace $VTF_NAMESPACE does not exist"

info "Creating secrets for vafi-agents (vtf target: $VTF_NAMESPACE)"

# --- Get or create vtf token ---

if [ -z "${VTF_TOKEN:-}" ]; then
    info "Creating vafi-agent user in $VTF_NAMESPACE"
    VTF_TOKEN=$(kubectl exec -n "$VTF_NAMESPACE" deploy/vtf-api -- \
        python /app/src/manage.py shell -c "
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token
user, created = User.objects.get_or_create(username='vafi-agent', defaults={'is_staff': False})
if created:
    user.set_unusable_password()
    user.save()
token, _ = Token.objects.get_or_create(user=user)
print(token.key)
" 2>/dev/null) || die "Could not create vafi-agent token in $VTF_NAMESPACE"
    ok "vafi-agent token from $VTF_NAMESPACE: ${VTF_TOKEN:0:8}..."
fi

# --- Create vafi-secrets ---

info "Creating secret: vafi-secrets"
kubectl delete secret vafi-secrets -n "$NAMESPACE" 2>/dev/null || true
kubectl create secret generic vafi-secrets -n "$NAMESPACE" \
    --from-literal=anthropic-auth-token="$ZAI_API_KEY" \
    --from-literal=anthropic-base-url="$ZAI_BASE_URL" \
    --from-literal=vtf-token="$VTF_TOKEN"
ok "vafi-secrets created"

# --- Create github-ssh ---

info "Creating secret: github-ssh"
kubectl delete secret github-ssh -n "$NAMESPACE" 2>/dev/null || true
kubectl create secret generic github-ssh -n "$NAMESPACE" \
    --from-file=ssh-privatekey="$HOME/.ssh/github" \
    --from-file=ssh-publickey="$HOME/.ssh/github.pub"
ok "github-ssh created"

# --- Verify ---

info "Secrets in ${NAMESPACE}:"
kubectl get secrets -n "$NAMESPACE" --no-headers | awk '{print "  " $1}'
