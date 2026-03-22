ARG REGISTRY=192.168.2.90:30500
FROM ${REGISTRY}/vafi-base:latest

# Install Claude Code CLI globally (runs as root, then switch back)
USER root
RUN npm install -g @anthropic-ai/claude-code
USER agent

# Verify claude is available
RUN claude --version
