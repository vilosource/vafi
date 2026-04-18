#!/usr/bin/env bash
# Smoke test for vafi-developer:* leaf images.
#
# Tests per leaf:
#   - CLI version command succeeds
#   - mempalace Python package imports
#   - /opt/vf-harness/* dispatcher scripts exist and are executable
#   - Bind-mount RW sanity (writes to /workspace, reads back)
#   - Core devtools exist (kubectl/terraform/helm/etc.)
#
# Does NOT hit external APIs. Designed to run offline.
#
# Usage:
#   ./smoke-test-developer.sh                      # all leaves
#   ./smoke-test-developer.sh claude               # single leaf
#   VAFI_REGISTRY=harbor.viloforge.com/vafi ./smoke-test-developer.sh

set -euo pipefail

REGISTRY="${VAFI_REGISTRY:-vafi}"
TMPWS=$(mktemp -d)
# Allow the in-container agent user (uid 1001) to write into the mount.
# mktemp -d gives 0700, owned by host user — need world-writable or uid 1001.
chmod 777 "$TMPWS"
trap 'rm -rf "$TMPWS"' EXIT

PASS=0
FAIL=0

check() {
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then
    echo "  ok   — $name"
    PASS=$((PASS+1))
  else
    echo "  FAIL — $name"
    FAIL=$((FAIL+1))
  fi
}

smoke_one() {
  local harness="$1"
  local image="${REGISTRY}/vafi-developer:${harness}"

  echo
  echo "=== $image ==="
  if ! docker image inspect "$image" >/dev/null 2>&1; then
    echo "  (image missing — skipping)"; return
  fi

  # Use --entrypoint="" to bypass init.sh so tests run against a plain bash.
  # Bind-mount a fresh workspace tmp dir so RW test has something to touch.
  local run=(docker run --rm --entrypoint="" -v "$TMPWS:/workspace" "$image")

  check "harness CLI --version"                 "${run[@]}" "$harness" --version
  check "mempalace import"                      "${run[@]}" python3 -c "import mempalace"
  check "/opt/vf-harness/init.sh exists"        "${run[@]}" test -x /opt/vf-harness/init.sh
  check "/opt/vf-harness/init-${harness}.sh"    "${run[@]}" test -f "/opt/vf-harness/init-${harness}.sh"
  check "/opt/vf-harness/connect.sh exists"     "${run[@]}" test -x /opt/vf-harness/connect.sh
  check "/opt/vf-harness/run.sh exists"         "${run[@]}" test -x /opt/vf-harness/run.sh
  check "VF_HARNESS env set correctly"          "${run[@]}" bash -c "[ \"\$VF_HARNESS\" = \"$harness\" ]"
  check "bind-mount /workspace is writable"     "${run[@]}" bash -c 'echo ok > /workspace/.smoke && cat /workspace/.smoke | grep -q ok'
  check "kubectl exists"                        "${run[@]}" which kubectl
  check "terraform exists"                      "${run[@]}" which terraform
  check "helm exists"                           "${run[@]}" which helm
  check "gh exists"                             "${run[@]}" which gh
  check "glab exists"                           "${run[@]}" which glab
  check "go exists"                             "${run[@]}" which go
  check "uv exists"                             "${run[@]}" which uv
  check "docker CLI exists"                     "${run[@]}" which docker
  check "ripgrep exists"                        "${run[@]}" which rg
  check "ENTRYPOINT dispatches harness init" bash -c '
    out=$(docker run --rm -e MEMPALACE_AUTO_INIT=false '"$image"' bash -c "echo harness=\$VF_HARNESS" 2>&1)
    echo "$out" | grep -q "harness='"$harness"'"
  '

  rm -f "$TMPWS/.smoke"
}

main() {
  if [ $# -eq 0 ]; then
    smoke_one claude
    smoke_one pi
    smoke_one gemini
  else
    for h in "$@"; do smoke_one "$h"; done
  fi

  echo
  echo "=== Summary: $PASS passed, $FAIL failed ==="
  [ "$FAIL" -eq 0 ]
}

main "$@"
