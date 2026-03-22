#!/usr/bin/env bash
# vtf-connect.sh — Establish and maintain a port-forward to vtf-api on k8s.
# Usage: ./scripts/vtf-connect.sh [local_port] [remote_port]
#   Defaults: local_port=8002, remote_port=8000
#
# Retries on failure, auto-reconnects when the connection drops.
# Kill with Ctrl+C or: pkill -f "vtf-connect"

set -euo pipefail

LOCAL_PORT="${1:-8002}"
REMOTE_PORT="${2:-8000}"
NAMESPACE="vafi-system"
SERVICE="svc/vtf-api"
KUBECONFIG="${KUBECONFIG:-$HOME/.kube/vafi-dev.yaml}"
MAX_RETRIES=10
RETRY_DELAY=5

export KUBECONFIG

check_pod_ready() {
    kubectl get pods -n "$NAMESPACE" -l app=vtf-api -o jsonpath='{.items[0].status.conditions[?(@.type=="Ready")].status}' 2>/dev/null
}

wait_for_pod() {
    echo "Waiting for vtf-api pod to be ready..."
    for i in $(seq 1 30); do
        if [ "$(check_pod_ready)" = "True" ]; then
            echo "Pod ready."
            return 0
        fi
        sleep 2
    done
    echo "Timed out waiting for pod." >&2
    return 1
}

kill_existing() {
    pkill -f "kubectl port-forward.*${SERVICE}.*${LOCAL_PORT}" 2>/dev/null || true
    sleep 1
}

health_check() {
    curl -s --connect-timeout 3 "http://localhost:${LOCAL_PORT}/v1/" >/dev/null 2>&1
}

echo "vtf-connect: forwarding localhost:${LOCAL_PORT} -> ${NAMESPACE}/${SERVICE}:${REMOTE_PORT}"

retry=0
while [ $retry -lt $MAX_RETRIES ]; do
    kill_existing

    if ! wait_for_pod; then
        retry=$((retry + 1))
        echo "Retry $retry/$MAX_RETRIES in ${RETRY_DELAY}s..."
        sleep "$RETRY_DELAY"
        continue
    fi

    echo "Starting port-forward..."
    kubectl port-forward -n "$NAMESPACE" "$SERVICE" "${LOCAL_PORT}:${REMOTE_PORT}" &
    PF_PID=$!

    sleep 2

    if health_check; then
        echo "Connected. VTF_API_URL=http://localhost:${LOCAL_PORT}"
        retry=0
    fi

    # Monitor — if port-forward dies, loop restarts it
    wait $PF_PID 2>/dev/null || true
    echo "Port-forward dropped. Reconnecting..."
    retry=$((retry + 1))
    sleep "$RETRY_DELAY"
done

echo "Failed after $MAX_RETRIES retries." >&2
exit 1
