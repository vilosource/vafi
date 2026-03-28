#!/usr/bin/env bash
set -euo pipefail

# Smoke test for vafi executor images.
#
# Validates the full executor loop WITHOUT touching the production pool:
#   1. Creates a test task in vtf-dev
#   2. Spins up an ephemeral executor pod connected to vtf-dev
#   3. Watches the pod claim, execute, and report
#   4. Cleans up the ephemeral pod
#
# The permanent executor-pool (connected to vtf-prod) is never affected.
#
# Prerequisites:
#   - vtf-dev running in vtf-dev namespace
#   - vafi-smoke-test repo exists on GitHub
#   - ZAI_API_KEY set (for Claude access in the ephemeral pod)
#   - github-ssh secret exists in vafi-agents namespace
#
# Usage:
#   ./scripts/smoke-test.sh              # Run smoke test
#   ./scripts/smoke-test.sh --cleanup    # Delete smoke test resources

export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/vafi-dev.yaml}"

REGISTRY="${VAFI_REGISTRY:-harbor.viloforge.com/vafi}"
NAMESPACE="vafi-agents"
VTF_NAMESPACE="vtf-dev"
VTF_URL="${VTF_URL:-https://vtf.dev.viloforge.com}"

SMOKE_PROJECT_NAME="vafi-smoke-test"
SMOKE_REPO_URL="git@github.com:vilosource/vafi-smoke-test.git"
SMOKE_REPO_BRANCH="main"
EPHEMERAL_POD="smoke-test-executor"

POLL_INTERVAL=5
MAX_WAIT=300  # 5 minutes

# --- Helpers ---

die() { echo "FAIL: $*" >&2; cleanup_pod; exit 1; }
info() { echo "==> $*"; }
ok() { echo "  OK: $*"; }

vtf_api() {
    local method="$1" path="$2"
    shift 2
    curl -sf -X "$method" "${VTF_URL}${path}" \
        -H "Authorization: Token ${VTF_TOKEN}" \
        -H "Content-Type: application/json" \
        "$@"
}

cleanup_pod() {
    if kubectl get pod "$EPHEMERAL_POD" -n "$NAMESPACE" &>/dev/null; then
        info "Cleaning up ephemeral pod"
        kubectl delete pod "$EPHEMERAL_POD" -n "$NAMESPACE" --grace-period=5 2>/dev/null || true
    fi
}

# --- Cleanup mode ---

if [ "${1:-}" = "--cleanup" ]; then
    info "Cleaning up smoke test resources"
    cleanup_pod

    # Get vtf-dev token for API calls
    VTF_TOKEN=$(kubectl exec -n "$VTF_NAMESPACE" deploy/vtf-api -- \
        python /app/src/manage.py shell -c "
from rest_framework.authtoken.models import Token
from django.contrib.auth.models import User
user, _ = User.objects.get_or_create(username='admin')
token, _ = Token.objects.get_or_create(user=user)
print(token.key)
" 2>/dev/null) || { echo "Could not get token"; exit 1; }

    PROJECT_ID=$(vtf_api GET "/v1/projects/?name=${SMOKE_PROJECT_NAME}" | \
        python3 -c "import json,sys; r=json.load(sys.stdin)['results']; print(r[0]['id'] if r else '')" 2>/dev/null)
    if [ -n "$PROJECT_ID" ]; then
        vtf_api DELETE "/v1/projects/${PROJECT_ID}/" || true
        ok "Deleted project ${PROJECT_ID}"
    else
        echo "  No smoke test project found"
    fi
    exit 0
fi

# --- Preflight checks ---

info "Preflight checks"

[ -n "${ZAI_API_KEY:-}" ] || die "ZAI_API_KEY not set"
kubectl get ns "$NAMESPACE" &>/dev/null || die "Namespace $NAMESPACE does not exist"
kubectl get ns "$VTF_NAMESPACE" &>/dev/null || die "Namespace $VTF_NAMESPACE does not exist"
kubectl get secret github-ssh -n "$NAMESPACE" &>/dev/null || die "Secret github-ssh not found — run create-secrets.sh first"
ok "Prerequisites met"

# --- Get vtf-dev token ---

info "Getting vtf-dev API token"
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
" 2>/dev/null) || die "Could not get vtf-dev token"
ok "Token: ${VTF_TOKEN:0:8}..."

vtf_api GET "/v1/projects/" > /dev/null || die "Cannot reach vtf-dev API"
ok "vtf-dev API reachable"

# --- Find or create smoke test project ---

info "Setting up smoke test project"

PROJECT_ID=$(vtf_api GET "/v1/projects/?name=${SMOKE_PROJECT_NAME}" | \
    python3 -c "import json,sys; r=json.load(sys.stdin)['results']; print(r[0]['id'] if r else '')")

if [ -n "$PROJECT_ID" ]; then
    ok "Project exists: ${PROJECT_ID}"
else
    PROJECT_ID=$(vtf_api POST "/v1/projects/" \
        -d "{\"name\":\"${SMOKE_PROJECT_NAME}\",\"repo_url\":\"${SMOKE_REPO_URL}\",\"default_branch\":\"${SMOKE_REPO_BRANCH}\"}" | \
        python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
    ok "Created project: ${PROJECT_ID}"
fi

# --- Create workplan and task ---

info "Creating workplan and task"
WORKPLAN_ID=$(vtf_api POST "/v1/workplans/" \
    -d "{\"name\":\"Smoke Test $(date +%Y%m%d-%H%M%S)\",\"project\":\"${PROJECT_ID}\"}" | \
    python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")

TASK_SPEC="Add a function called smoke_$(date +%s)() -> str to hello.py that returns 'smoke-ok'. Add a test for it in test_hello.py."
TASK_ID=$(vtf_api POST "/v1/tasks/" \
    -d "{
        \"title\":\"Smoke test: add function\",
        \"workplan\":\"${WORKPLAN_ID}\",
        \"project\":\"${PROJECT_ID}\",
        \"spec\":\"${TASK_SPEC}\",
        \"test_command\":{\"command\":\"python3 -m pytest test_hello.py -v\"},
        \"tags\":[\"executor\"],
        \"status\":\"draft\"
    }" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")

vtf_api POST "/v1/tasks/${TASK_ID}/submit/" > /dev/null
ok "Task ${TASK_ID} submitted (status: todo)"

# --- Launch ephemeral executor pod ---

info "Launching ephemeral executor pod against vtf-dev"

# Clean up any leftover pod from a previous run
cleanup_pod

kubectl run "$EPHEMERAL_POD" -n "$NAMESPACE" \
    --image="${REGISTRY}/vafi-agent:latest" \
    --restart=Never \
    --overrides="$(cat <<ENDOFOVERRIDES
{
  "spec": {
    "initContainers": [{
      "name": "setup-ssh",
      "image": "${REGISTRY}/vafi-base:latest",
      "command": ["sh", "-c", "cp /ssh-secret/ssh-privatekey /ssh-ready/id_ed25519 && cp /ssh-secret/ssh-publickey /ssh-ready/id_ed25519.pub && chmod 600 /ssh-ready/id_ed25519 && chmod 644 /ssh-ready/id_ed25519.pub && echo 'StrictHostKeyChecking no' > /ssh-ready/config && chmod 644 /ssh-ready/config"],
      "volumeMounts": [
        {"name": "ssh-secret", "mountPath": "/ssh-secret", "readOnly": true},
        {"name": "ssh-ready", "mountPath": "/ssh-ready"}
      ]
    }],
    "containers": [{
      "name": "smoke-test-executor",
      "image": "${REGISTRY}/vafi-agent:latest",
      "imagePullPolicy": "Always",
      "securityContext": {"runAsUser": 1001, "runAsNonRoot": true},
      "env": [
        {"name": "VF_AGENT_ID", "value": "smoke-test"},
        {"name": "VF_AGENT_ROLE", "value": "executor"},
        {"name": "VF_AGENT_TAGS", "value": "executor"},
        {"name": "VF_VTF_API_URL", "value": "http://vtf-api.${VTF_NAMESPACE}.svc.cluster.local:8000"},
        {"name": "VF_VTF_TOKEN", "value": "${VTF_TOKEN}"},
        {"name": "VF_POLL_INTERVAL", "value": "5"},
        {"name": "VF_TASK_TIMEOUT", "value": "300"},
        {"name": "VF_MAX_REWORK", "value": "1"},
        {"name": "VF_MAX_TURNS", "value": "30"},
        {"name": "VF_HEARTBEAT_INTERVAL", "value": "60"},
        {"name": "VF_SESSIONS_DIR", "value": "/sessions"},
        {"name": "ANTHROPIC_AUTH_TOKEN", "value": "${ZAI_API_KEY}"},
        {"name": "ANTHROPIC_BASE_URL", "value": "https://api.z.ai/api/anthropic"}
      ],
      "volumeMounts": [
        {"name": "sessions", "mountPath": "/sessions"},
        {"name": "ssh-ready", "mountPath": "/home/agent/.ssh"}
      ]
    }],
    "volumes": [
      {"name": "sessions", "emptyDir": {}},
      {"name": "ssh-secret", "secret": {"secretName": "github-ssh"}},
      {"name": "ssh-ready", "emptyDir": {}}
    ],
    "restartPolicy": "Never"
  }
}
ENDOFOVERRIDES
)" 2>&1

ok "Ephemeral pod launched"

# --- Watch for execution ---

info "Waiting for task execution (polling every ${POLL_INTERVAL}s, max ${MAX_WAIT}s)"

ELAPSED=0
LAST_STATUS=""
while [ $ELAPSED -lt $MAX_WAIT ]; do
    # Check pod is still running
    POD_PHASE=$(kubectl get pod "$EPHEMERAL_POD" -n "$NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null || echo "Missing")
    if [ "$POD_PHASE" = "Failed" ] || [ "$POD_PHASE" = "Missing" ]; then
        echo ""
        info "Pod failed! Logs:"
        kubectl logs "$EPHEMERAL_POD" -n "$NAMESPACE" --tail=30 2>/dev/null || true
        die "Ephemeral pod died (phase: $POD_PHASE)"
    fi

    STATUS=$(vtf_api GET "/v1/tasks/${TASK_ID}/" | \
        python3 -c "import json,sys; print(json.load(sys.stdin)['status'])")

    if [ "$STATUS" != "$LAST_STATUS" ]; then
        echo "  [${ELAPSED}s] status: ${STATUS}"
        LAST_STATUS="$STATUS"
    fi

    case "$STATUS" in
        done|pending_completion_review)
            echo ""
            ok "Task executed successfully in ${ELAPSED}s (status: ${STATUS})"
            info "Task notes:"
            vtf_api GET "/v1/tasks/${TASK_ID}/notes/" | \
                python3 -c "import json,sys; [print(f'  {n[\"content\"][:200]}') for n in json.load(sys.stdin).get('results',[])]" 2>/dev/null || true
            cleanup_pod
            echo ""
            info "SMOKE TEST PASSED"
            exit 0
            ;;
        failed|needs_attention)
            echo ""
            echo "  Task failed after ${ELAPSED}s (status: ${STATUS})"
            info "Failure notes:"
            vtf_api GET "/v1/tasks/${TASK_ID}/notes/" | \
                python3 -c "import json,sys; [print(n['content'][:500]) for n in json.load(sys.stdin).get('results',[])]" 2>/dev/null || true
            info "Pod logs (last 30 lines):"
            kubectl logs "$EPHEMERAL_POD" -n "$NAMESPACE" --tail=30 2>/dev/null || true
            cleanup_pod
            echo ""
            die "SMOKE TEST FAILED — task failed"
            ;;
    esac

    sleep $POLL_INTERVAL
    ELAPSED=$((ELAPSED + POLL_INTERVAL))
done

info "Pod logs (last 30 lines):"
kubectl logs "$EPHEMERAL_POD" -n "$NAMESPACE" --tail=30 2>/dev/null || true
cleanup_pod
die "Timed out after ${MAX_WAIT}s — task status: ${STATUS}"
