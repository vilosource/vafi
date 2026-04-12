ARG REGISTRY=vafi
FROM ${REGISTRY}/vafi-claude:latest

USER root

# ---------------------------------------------------------------------------
# System packages
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    apt-transport-https \
    ca-certificates \
    gnupg \
    lsb-release \
    software-properties-common \
    unzip \
    wget \
    make \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Azure CLI (pip install is more reliable in Docker than the deb script)
# ---------------------------------------------------------------------------
RUN pip install --break-system-packages azure-cli

# ---------------------------------------------------------------------------
# azcopy
# ---------------------------------------------------------------------------
RUN curl -sL https://aka.ms/downloadazcopy-v10-linux -o /tmp/azcopy.tar.gz \
    && tar -xzf /tmp/azcopy.tar.gz -C /tmp --strip-components=1 \
    && mv /tmp/azcopy /usr/local/bin/azcopy \
    && chmod +x /usr/local/bin/azcopy \
    && rm -f /tmp/azcopy.tar.gz

# ---------------------------------------------------------------------------
# HashiCorp Vault + Terraform
# ---------------------------------------------------------------------------
RUN curl -fsSL https://apt.releases.hashicorp.com/gpg | gpg --dearmor -o /usr/share/keyrings/hashicorp.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/hashicorp.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" \
        > /etc/apt/sources.list.d/hashicorp.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends terraform vault \
    && rm -rf /var/lib/apt/lists/* \
    && setcap -r /usr/bin/vault

# ---------------------------------------------------------------------------
# Ansible
# ---------------------------------------------------------------------------
RUN pip install --break-system-packages ansible

# ---------------------------------------------------------------------------
# kubectl
# ---------------------------------------------------------------------------
RUN curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.31/deb/Release.key | gpg --dearmor -o /usr/share/keyrings/kubernetes.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/kubernetes.gpg] https://pkgs.k8s.io/core:/stable:/v1.31/deb/ /" \
        > /etc/apt/sources.list.d/kubernetes.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends kubectl \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Helm
# ---------------------------------------------------------------------------
RUN curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# ---------------------------------------------------------------------------
# Go
# ---------------------------------------------------------------------------
ARG GO_VERSION=1.24.4
RUN curl -fsSL "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz" -o /tmp/go.tar.gz \
    && tar -C /usr/local -xzf /tmp/go.tar.gz \
    && rm /tmp/go.tar.gz
ENV PATH="/usr/local/go/bin:/home/agent/go/bin:${PATH}"
ENV GOPATH="/home/agent/go"

# ---------------------------------------------------------------------------
# Python: uv (fast pip replacement + venv manager)
# ---------------------------------------------------------------------------
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv \
    && mv /root/.local/bin/uvx /usr/local/bin/uvx

# ---------------------------------------------------------------------------
# GitHub CLI (gh)
# ---------------------------------------------------------------------------
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        -o /usr/share/keyrings/githubcli.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# GitLab CLI (glab)
# ---------------------------------------------------------------------------
ARG GLAB_VERSION=1.92.1
RUN curl -fsSL -L "https://gitlab.com/gitlab-org/cli/-/releases/v${GLAB_VERSION}/downloads/glab_${GLAB_VERSION}_linux_amd64.tar.gz" \
        -o /tmp/glab.tar.gz \
    && tar -xzf /tmp/glab.tar.gz -C /tmp \
    && mv /tmp/bin/glab /usr/local/bin/glab \
    && chmod +x /usr/local/bin/glab \
    && rm -rf /tmp/glab.tar.gz /tmp/bin

# ---------------------------------------------------------------------------
# Docker CLI (for socket mount, not Docker-in-Docker)
# ---------------------------------------------------------------------------
RUN curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /usr/share/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

USER agent

# Verify key tools (each on its own line for easier debugging)
RUN az version --output tsv \
    && terraform version \
    && which vault \
    && ansible --version | head -1 \
    && kubectl version --client=true 2>/dev/null \
    && helm version --short \
    && go version \
    && uv --version \
    && gh --version | head -1 \
    && glab --version \
    && docker --version \
    && azcopy --version \
    && echo "All tools verified" \
    && rm -rf ~/.config
