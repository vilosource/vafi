FROM node:20-bookworm-slim

# System tools needed by agents
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    openssh-client \
    jq \
    python3 \
    python3-pip \
    python3-venv \
    python3-pytest \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for agent execution
# node:20 base image already has uid=1000 (node), agent gets uid=1001
RUN useradd -m -s /bin/bash agent

# Agent home and workdir are separate (key architectural decision)
# $HOME = /home/agent (credentials, config, methodology)
# workdir = /sessions/<milestone>/<task>/ (dynamic, per task)
WORKDIR /home/agent

USER agent
