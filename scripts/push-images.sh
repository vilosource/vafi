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

# Push mempalace images if built
if docker image inspect "${REGISTRY}/vafi-claude-mempalace:latest" &>/dev/null; then
    echo "==> Pushing vafi-claude-mempalace"
    docker push "${REGISTRY}/vafi-claude-mempalace:latest"
else
    echo "==> Skipping vafi-claude-mempalace (not built yet)"
fi

if docker image inspect "${REGISTRY}/vafi-agent-mempalace:latest" &>/dev/null; then
    echo "==> Pushing vafi-agent-mempalace"
    docker push "${REGISTRY}/vafi-agent-mempalace:latest"
else
    echo "==> Skipping vafi-agent-mempalace (not built yet)"
fi

echo "==> Done"
