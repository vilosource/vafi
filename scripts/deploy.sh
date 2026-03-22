#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# Use vafi-dev kubeconfig
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/vafi-dev.yaml}"

echo "==> Using kubeconfig: $KUBECONFIG"

# Apply namespaces first
echo "==> Creating namespaces"
kubectl apply -f "$REPO_ROOT/k8s/namespaces.yaml"

# Apply vafi-agents resources
echo "==> Deploying vafi-agents"
kubectl apply -k "$REPO_ROOT/k8s/vafi-agents/"

echo "==> Deployment complete"

# Show status
echo "==> Checking deployment status"
kubectl get pods -n vafi-agents
kubectl get pvc -n vafi-agents
kubectl get secrets -n vafi-agents