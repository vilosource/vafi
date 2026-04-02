ARG REGISTRY=vafi

# Stage 1: Build cxtx from cxdb source
FROM rust:1.86-bookworm AS cxtx-builder
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 https://github.com/vilosource/cxdb.git /build/cxdb
WORKDIR /build/cxdb
RUN cargo build -p cxtx --release

# Stage 2: vafi-claude image
ARG REGISTRY
FROM ${REGISTRY}/vafi-base:latest

# Install Claude Code CLI globally
USER root
RUN npm install -g @anthropic-ai/claude-code

# Install cxtx binary from builder stage
COPY --from=cxtx-builder /build/cxdb/target/release/cxtx /usr/local/bin/cxtx
RUN chmod +x /usr/local/bin/cxtx

## Harness boundary scripts
COPY init.sh connect.sh run.sh /opt/vf-harness/
RUN chmod +x /opt/vf-harness/init.sh /opt/vf-harness/connect.sh /opt/vf-harness/run.sh

USER agent

# Verify both tools are available
RUN claude --version
RUN cxtx --help > /dev/null 2>&1 || true
