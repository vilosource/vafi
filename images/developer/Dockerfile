ARG REGISTRY=vafi
FROM ${REGISTRY}/vafi-devtools:latest

USER root

# ---------------------------------------------------------------------------
# MemPalace + embedding model
# ---------------------------------------------------------------------------
RUN pip install --break-system-packages mempalace

USER agent
RUN python3 -c "from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2; \
    ef = ONNXMiniLM_L6_V2(); ef._download_model_if_not_exists()"
RUN mkdir -p ~/.mempalace

# ---------------------------------------------------------------------------
# Shell niceties
# ---------------------------------------------------------------------------
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    vim \
    tmux \
    tree \
    dnsutils \
    netcat-openbsd \
    httpie \
    shellcheck \
    bat \
    fd-find \
    && rm -rf /var/lib/apt/lists/*

# ripgrep (rg) — already in base via Claude Code, but ensure it's available
RUN which rg || apt-get update && apt-get install -y --no-install-recommends ripgrep && rm -rf /var/lib/apt/lists/*

# fzf
ARG FZF_VERSION=0.71.0
RUN curl -fsSL "https://github.com/junegunn/fzf/releases/download/v${FZF_VERSION}/fzf-${FZF_VERSION}-linux_amd64.tar.gz" \
        -o /tmp/fzf.tar.gz \
    && tar -xzf /tmp/fzf.tar.gz -C /usr/local/bin \
    && chmod +x /usr/local/bin/fzf \
    && rm /tmp/fzf.tar.gz

# yq (YAML processor)
RUN curl -fsSL https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64 \
        -o /usr/local/bin/yq \
    && chmod +x /usr/local/bin/yq

# ---------------------------------------------------------------------------
# Python dev tools
# ---------------------------------------------------------------------------
RUN pip install --break-system-packages ruff mypy pre-commit

# ---------------------------------------------------------------------------
# MCP MediaWiki (stdio server for self-hosted wikis)
# ---------------------------------------------------------------------------
RUN pip install --break-system-packages git+https://github.com/vilosource/mcp-mediawiki.git

# ---------------------------------------------------------------------------
# Symlinks for Debian naming quirks
# ---------------------------------------------------------------------------
RUN ln -sf /usr/bin/batcat /usr/local/bin/bat 2>/dev/null || true \
    && ln -sf /usr/bin/fdfind /usr/local/bin/fd 2>/dev/null || true

# ---------------------------------------------------------------------------
# Local entrypoint (same as mempalace image)
# ---------------------------------------------------------------------------
# Entrypoint runs as agent (no root needed — credentials passed via env var)
COPY entrypoint-local.sh /opt/mempalace/entrypoint-local.sh
RUN chmod +x /opt/mempalace/entrypoint-local.sh


USER agent
WORKDIR /workspace
ENTRYPOINT ["/opt/mempalace/entrypoint-local.sh"]
CMD ["claude", "--dangerously-skip-permissions"]
