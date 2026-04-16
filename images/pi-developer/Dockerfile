ARG REGISTRY=vafi
FROM ${REGISTRY}/vafi-pi-devtools:latest

USER root

# ---------------------------------------------------------------------------
# MemPalace + embedding model
# ---------------------------------------------------------------------------
RUN pip install --break-system-packages git+https://github.com/vilosource/mempalace.git@develop

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

# ripgrep — PI doesn't bundle rg like Claude Code does
RUN which rg || (apt-get update && apt-get install -y --no-install-recommends ripgrep && rm -rf /var/lib/apt/lists/*)

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
# MemPalace system prompt + lifecycle extension
# ---------------------------------------------------------------------------
COPY APPEND_SYSTEM.md /opt/pi-developer/APPEND_SYSTEM.md
COPY extensions/mempalace-hooks.ts /opt/pi-developer/extensions/mempalace-hooks.ts

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
COPY entrypoint-pi-local.sh /opt/pi-developer/entrypoint-pi-local.sh
RUN chmod +x /opt/pi-developer/entrypoint-pi-local.sh

USER agent
WORKDIR /workspace
ENTRYPOINT ["/opt/pi-developer/entrypoint-pi-local.sh"]
CMD ["pi"]
