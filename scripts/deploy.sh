#!/usr/bin/env bash
set -euo pipefail

# Deploy vafi executor-pool to k8s cluster.
#
# Usage:
#   ./scripts/deploy.sh           # Apply manifests (no restart)
#   ./scripts/deploy.sh --restart # Apply manifests and rollout restart
#
# Secrets must be created first with: ./scripts/create-secrets.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/vafi-dev.yaml}"

info() { echo "==> $*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

info "Using kubeconfig: $KUBECONFIG"

# --- Verify cluster access ---

kubectl cluster-info &>/dev/null || die "Cannot reach cluster"

# --- Apply namespaces ---

info "Creating namespaces"
kubectl apply -f "$REPO_ROOT/k8s/namespaces.yaml"

# --- Verify secrets exist ---

if ! kubectl get secret vafi-secrets -n vafi-agents &>/dev/null; then
    die "Secret 'vafi-secrets' not found in vafi-agents. Run: ./scripts/create-secrets.sh"
fi
if ! kubectl get secret github-ssh -n vafi-agents &>/dev/null; then
    die "Secret 'github-ssh' not found in vafi-agents. Run: ./scripts/create-secrets.sh"
fi

# --- Apply vafi-agents resources ---

info "Deploying vafi-agents"
kubectl apply -k "$REPO_ROOT/k8s/vafi-agents/"

# --- Optional rollout restart (after image push) ---

if [ "${1:-}" = "--restart" ]; then
    info "Restarting executor-pool"
    kubectl rollout restart deploy/executor-pool -n vafi-agents
    info "Waiting for rollout"
    kubectl rollout status deploy/executor-pool -n vafi-agents --timeout=120s
fi

# --- Show status ---

info "Deployment status"
kubectl get pods -n vafi-agents
kubectl get pvc -n vafi-agents
kubectl get secrets -n vafi-agents --no-headers | awk '{print "  secret/" $1}'
