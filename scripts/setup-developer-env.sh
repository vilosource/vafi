#!/usr/bin/env bash
# setup-developer-env.sh — install vafi-developer launcher scripts and wire ~/.bashrc.
#
# Safe to re-run (idempotent). Never overwrites vf-launchers-context.sh if it exists.
#
# Usage:
#   ./scripts/setup-developer-env.sh
#
# After running:
#   1. Fill in ~/.claude/vf-launchers-context.sh with your secrets
#   2. source ~/.bashrc  (or open a new shell)
#   3. Build images: ./scripts/build-developer-images.sh
#   4. vfdev            # launch claude developer container

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
CLAUDE_DIR="$HOME/.claude"
BASHRC="$HOME/.bashrc"
SOURCE_LINE='[ -f "$HOME/.claude/vf-launchers.sh" ] && . "$HOME/.claude/vf-launchers.sh"'

green() { printf '\033[32m✓\033[0m %s\n' "$*"; }
blue()  { printf '\033[36m-->\033[0m %s\n' "$*"; }
warn()  { printf '\033[33m!\033[0m %s\n' "$*"; }

mkdir -p "$CLAUDE_DIR"

# 1. Install launcher
blue "Installing vf-launchers.sh → $CLAUDE_DIR/vf-launchers.sh"
cp "$REPO_ROOT/scripts/vf-launchers.sh" "$CLAUDE_DIR/vf-launchers.sh"
green "vf-launchers.sh installed"

# 2. Install context template
blue "Installing vf-launchers-context.sh.example → $CLAUDE_DIR/"
cp "$REPO_ROOT/scripts/vf-launchers-context.sh.example" "$CLAUDE_DIR/vf-launchers-context.sh.example"
green "context template installed"

# 3. Create context secrets file from example if not present
if [ -f "$CLAUDE_DIR/vf-launchers-context.sh" ]; then
  green "vf-launchers-context.sh already exists (not overwritten)"
else
  cp "$REPO_ROOT/scripts/vf-launchers-context.sh.example" "$CLAUDE_DIR/vf-launchers-context.sh"
  warn "Created $CLAUDE_DIR/vf-launchers-context.sh from example — fill in your secrets before launching."
fi

# 4. Wire ~/.bashrc
if grep -qF 'vf-launchers.sh' "$BASHRC" 2>/dev/null; then
  green "~/.bashrc already sources vf-launchers.sh"
else
  blue "Adding source line to $BASHRC"
  printf '\n# vafi developer image launchers (vfdev, ogcli, ogdr, pidev)\n%s\n' "$SOURCE_LINE" >> "$BASHRC"
  green "~/.bashrc updated"
fi

echo ""
echo "Setup complete. Next steps:"
echo "  1. Edit ~/.claude/vf-launchers-context.sh  — fill in context-specific secrets"
echo "  2. source ~/.bashrc                         — activate launchers in current shell"
echo "  3. ./scripts/build-developer-images.sh      — build the container images"
echo "  4. vfdev                                    — launch claude developer container"
