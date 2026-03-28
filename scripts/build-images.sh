#!/usr/bin/env bash
set -euo pipefail

REGISTRY="${VAFI_REGISTRY:-vafi}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

echo "==> Building vafi-base"
docker build -t "${REGISTRY}/vafi-base:latest" "${REPO_ROOT}/images/base"

echo "==> Building vafi-claude"
docker build \
    --build-arg "REGISTRY=${REGISTRY}" \
    -t "${REGISTRY}/vafi-claude:latest" \
    "${REPO_ROOT}/images/claude"

echo "==> Building vafi-agent"
docker build \
    --build-arg "REGISTRY=${REGISTRY}" \
    -t "${REGISTRY}/vafi-agent:latest" \
    -f "${REPO_ROOT}/images/agent/Dockerfile" \
    "${REPO_ROOT}"

echo "==> Done"
docker images | grep vafi
