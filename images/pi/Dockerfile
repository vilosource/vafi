ARG REGISTRY=vafi

# Stage 1: Build cxtx from cxdb source
FROM rust:1.86-bookworm AS cxtx-builder
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 https://github.com/vilosource/cxdb.git /build/cxdb
WORKDIR /build/cxdb
RUN cargo build -p cxtx --release

# Stage 2: vafi-pi image
ARG REGISTRY
FROM ${REGISTRY}/vafi-base:latest

ARG PI_VERSION=0.59.0
USER root

# Install Pi coding agent
RUN npm install -g @mariozechner/pi-coding-agent@${PI_VERSION}

# Install pi-mcp-adapter (writes settings.json to $HOME/.pi/agent/)
RUN pi install npm:pi-mcp-adapter

# Install cxtx binary from builder stage
COPY --from=cxtx-builder /build/cxdb/target/release/cxtx /usr/local/bin/cxtx
RUN chmod +x /usr/local/bin/cxtx

# Copy settings to agent user (pi install runs as root, writes to /root/.pi/)
RUN mkdir -p /home/agent/.pi/agent && \
    cp /root/.pi/agent/settings.json /home/agent/.pi/agent/settings.json && \
    chown -R agent:agent /home/agent/.pi/agent

# Allow agent to reinstall/update pi-mcp-adapter at runtime without EACCES.
# Pi's package-manager runs `npm install -g` on referenced packages which
# needs write access to the npm global prefix.
RUN chown -R agent:agent /usr/local/lib/node_modules /usr/local/bin

USER agent

# Verify
RUN pi --version
RUN cxtx --help > /dev/null 2>&1 || true
