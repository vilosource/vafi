# vafi-developer — single consolidated image for cluster-resident dev contexts.
#
# Built once per push to vilosource/vafi:main by vafi-developer-sensor.yaml,
# tagged with the full git SHA at harbor.viloforge.com/vafi/vafi-developer.
# Consumed by the per-context StatefulSets defined in vafi-deploy (vfdev,
# ogcli, future siblings).
#
# Harness selection happens at RUNTIME, not build time. All three CLIs
# (claude, pi, gemini) are pre-installed; the StatefulSet sets
# VF_HARNESS=<harness> and /opt/vf-harness/init.sh dispatches accordingly.
# This is design O1: one Sensor, one image, one tag, runtime-selected
# variant. The local-laptop chain (Dockerfile.base + Dockerfile.<harness>)
# stays in this directory for the docker-on-host launcher path until
# vfdev / ogcli migrate to the cluster, at which point those go away.
#
# This Dockerfile is design O2 "flattened": FROM vafi-base directly, no
# separate vafi-developer-base image in Harbor. Mirrors the chain depth
# of vafi-claude / vafi-bridge.
#
# Design: viloforge-platform/docs/developer-pods-DESIGN.md
# Build context: repo root. Sensor passes REGISTRY build-arg.

ARG REGISTRY=vafi
FROM ${REGISTRY}/vafi-base:latest

USER root

ARG FZF_VERSION=0.71.0
ARG GO_VERSION=1.24.4
ARG GLAB_VERSION=1.92.1

# --- Editor + shell conveniences ---
RUN apt-get update && apt-get install -y --no-install-recommends \
      vim tmux tree dnsutils netcat-openbsd httpie shellcheck \
      bat fd-find ripgrep \
      apt-transport-https gnupg lsb-release software-properties-common \
      unzip wget make \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/batcat /usr/local/bin/bat \
    && ln -sf /usr/bin/fdfind /usr/local/bin/fd

# --- Python quality tools + mcp-mediawiki ---
RUN pip install --break-system-packages ruff mypy pre-commit \
    && pip install --break-system-packages git+https://github.com/vilosource/mcp-mediawiki.git

# --- yq ---
RUN curl -fsSL https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64 \
      -o /usr/local/bin/yq && chmod +x /usr/local/bin/yq

# --- fzf ---
RUN curl -fsSL "https://github.com/junegunn/fzf/releases/download/v${FZF_VERSION}/fzf-${FZF_VERSION}-linux_amd64.tar.gz" \
      -o /tmp/fzf.tar.gz \
    && tar -xzf /tmp/fzf.tar.gz -C /usr/local/bin \
    && chmod +x /usr/local/bin/fzf \
    && rm /tmp/fzf.tar.gz

# --- uv (python package manager) ---
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv \
    && mv /root/.local/bin/uvx /usr/local/bin/uvx

# --- GitHub CLI ---
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      -o /usr/share/keyrings/githubcli.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# --- GitLab CLI ---
RUN curl -fsSL -L "https://gitlab.com/gitlab-org/cli/-/releases/v${GLAB_VERSION}/downloads/glab_${GLAB_VERSION}_linux_amd64.tar.gz" \
      -o /tmp/glab.tar.gz \
    && tar -xzf /tmp/glab.tar.gz -C /tmp \
    && mv /tmp/bin/glab /usr/local/bin/glab \
    && chmod +x /usr/local/bin/glab \
    && rm -rf /tmp/glab.tar.gz /tmp/bin

# --- Go ---
RUN curl -fsSL "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz" -o /tmp/go.tar.gz \
    && tar -C /usr/local -xzf /tmp/go.tar.gz \
    && rm /tmp/go.tar.gz
ENV PATH=/usr/local/go/bin:/home/agent/go/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ENV GOPATH=/home/agent/go

# --- Azure CLI + azcopy ---
RUN pip install --break-system-packages azure-cli
RUN curl -sL https://aka.ms/downloadazcopy-v10-linux -o /tmp/azcopy.tar.gz \
    && tar -xzf /tmp/azcopy.tar.gz -C /tmp --strip-components=1 \
    && mv /tmp/azcopy /usr/local/bin/azcopy \
    && chmod +x /usr/local/bin/azcopy \
    && rm -f /tmp/azcopy.tar.gz

# --- HashiCorp (terraform + vault) ---
RUN curl -fsSL https://apt.releases.hashicorp.com/gpg | gpg --dearmor -o /usr/share/keyrings/hashicorp.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/hashicorp.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" \
      > /etc/apt/sources.list.d/hashicorp.list \
    && apt-get update && apt-get install -y --no-install-recommends terraform vault \
    && rm -rf /var/lib/apt/lists/* \
    && setcap -r /usr/bin/vault

# --- Ansible ---
RUN pip install --break-system-packages ansible

# --- kubectl ---
RUN curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.31/deb/Release.key | gpg --dearmor -o /usr/share/keyrings/kubernetes.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/kubernetes.gpg] https://pkgs.k8s.io/core:/stable:/v1.31/deb/ /" \
      > /etc/apt/sources.list.d/kubernetes.list \
    && apt-get update && apt-get install -y --no-install-recommends kubectl \
    && rm -rf /var/lib/apt/lists/*

# --- Helm ---
RUN curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# --- MemPalace (installs chromadb transitively — needed before prefetch below) ---
# Pinned to a fork commit so cache invalidates on bump. Bump the SHA to pull
# new fork/develop fixes.
ARG MEMPALACE_REF=6fd1d5b
RUN pip install --break-system-packages "git+https://github.com/vilosource/mempalace.git@${MEMPALACE_REF}"

# --- Pre-fetch chromadb ONNX embedding model (fast & offline mempalace startup) ---
RUN mkdir -p /home/agent/.mempalace \
    && python3 -c "from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2; \
                   ef = ONNXMiniLM_L6_V2(); \
                   ef._download_model_if_not_exists()" \
    && chown -R agent:agent /home/agent/.mempalace

# --- All three harness CLIs (runtime selection via VF_HARNESS) ---
# Image carries claude + pi + gemini. The StatefulSet sets VF_HARNESS and
# init.sh execs the matching init-<harness>.sh. Marginal image size cost
# (~150-200MB total) is negligible vs the ~1.5GB devtools layer above and
# saves us three Sensors / three Harbor repos / three tag streams.

ARG CLAUDE_VERSION=latest
RUN if [ "$CLAUDE_VERSION" = "latest" ]; then \
      npm install -g @anthropic-ai/claude-code; \
    else \
      npm install -g @anthropic-ai/claude-code@${CLAUDE_VERSION}; \
    fi

ARG PI_VERSION=latest
RUN if [ "$PI_VERSION" = "latest" ]; then \
      npm install -g @mariozechner/pi-coding-agent; \
    else \
      npm install -g @mariozechner/pi-coding-agent@${PI_VERSION}; \
    fi
# pi-mcp-adapter writes settings.json under root's home; migrate to agent's.
RUN pi install npm:pi-mcp-adapter \
    && mkdir -p /home/agent/.pi/agent \
    && cp /root/.pi/agent/settings.json /home/agent/.pi/agent/settings.json \
    && chown -R agent:agent /home/agent/.pi

ARG GEMINI_VERSION=latest
RUN if [ "$GEMINI_VERSION" = "latest" ]; then \
      npm install -g @google/gemini-cli; \
    else \
      npm install -g @google/gemini-cli@${GEMINI_VERSION}; \
    fi

# Hand global npm dirs to agent so any of the three CLIs can be re-installed
# at runtime without EACCES (mirrors the per-harness leaves).
RUN chown -R agent:agent /usr/local/lib/node_modules /usr/local/bin

# --- vf-harness dispatcher scripts + pi extras + hook bundles ---
# Build context is the repo root (Sensor passes build-context="."), so paths
# are relative to /vafi/, not /vafi/images/developer/.
COPY images/developer/vf-harness/ /opt/vf-harness/
COPY images/developer/pi-extras/  /opt/vf-harness/pi-extras/
COPY images/developer/hooks.d/    /opt/vf-harness/hooks.d/
RUN chmod +x /opt/vf-harness/*.sh /opt/vf-harness/vf-hooks \
    && ln -sf /opt/vf-harness/vf-hooks /usr/local/bin/vf-hooks

# --- Fetch mempalace hook scripts pinned to $MEMPALACE_REF (matches pip install above) ---
RUN for f in mempal_save_hook.sh mempal_precompact_hook.sh; do \
      curl -fsSL "https://raw.githubusercontent.com/vilosource/mempalace/${MEMPALACE_REF}/hooks/$f" \
        -o "/opt/vf-harness/hooks.d/mempalace/claude/${f#mempal_}"; \
    done \
    && chmod +x /opt/vf-harness/hooks.d/mempalace/claude/*.sh

# --- Verification ---
RUN az version --output tsv 2>/dev/null | head -1 \
    && terraform version | head -1 \
    && vault version \
    && ansible --version | head -1 \
    && kubectl version --client=true 2>/dev/null | head -1 || true \
    && helm version --short \
    && go version \
    && uv --version \
    && gh --version | head -1 \
    && glab --version | head -1 \
    && azcopy --version \
    && yq --version \
    && fzf --version \
    && claude --version \
    && pi --version \
    && gemini --version \
    && python3 -c "import mempalace; print('mempalace: OK')" \
    && echo "vafi-developer (consolidated) tools verified"

USER agent

WORKDIR /workspace

# VF_HARNESS is intentionally NOT set in the image. The StatefulSet must
# provide it (claude | pi | gemini) so init.sh can dispatch. init.sh
# refuses to run with an empty / unrecognized VF_HARNESS — the failure is
# loud and immediate at pod startup rather than mid-session.
ENTRYPOINT ["/opt/vf-harness/init.sh"]
CMD ["bash"]
