#!/usr/bin/env bash
set -euo pipefail

REGISTRY="${VAFI_REGISTRY:-192.168.2.90:30500}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

echo "==> Building vafi-base"
docker build -t "${REGISTRY}/vafi-base:latest" "${REPO_ROOT}/images/base"

echo "==> Building vafi-claude"
docker build \
    --build-arg "REGISTRY=${REGISTRY}" \
    -t "${REGISTRY}/vafi-claude:latest" \
    "${REPO_ROOT}/images/claude"

# vafi-agent requires controller source (M2)
if [ -f "${REPO_ROOT}/images/agent/Dockerfile" ] && \
   [ -d "${REPO_ROOT}/src/controller" ] && \
   [ -f "${REPO_ROOT}/src/controller/__main__.py" ]; then
    echo "==> Building vafi-agent"
    docker build \
        --build-arg "REGISTRY=${REGISTRY}" \
        -t "${REGISTRY}/vafi-agent:latest" \
        -f "${REPO_ROOT}/images/agent/Dockerfile" \
        "${REPO_ROOT}"
else
    echo "==> Skipping vafi-agent (controller source not yet available)"
fi

echo "==> Done"
docker images | grep vafi
