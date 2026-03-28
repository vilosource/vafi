#!/usr/bin/env bash
set -euo pipefail

REGISTRY="${VAFI_REGISTRY:-vafi}"

echo "==> Pushing vafi-base"
docker push "${REGISTRY}/vafi-base:latest"

echo "==> Pushing vafi-claude"
docker push "${REGISTRY}/vafi-claude:latest"

# Push vafi-agent only if it exists
if docker image inspect "${REGISTRY}/vafi-agent:latest" &>/dev/null; then
    echo "==> Pushing vafi-agent"
    docker push "${REGISTRY}/vafi-agent:latest"
else
    echo "==> Skipping vafi-agent (not built yet)"
fi

echo "==> Done"
