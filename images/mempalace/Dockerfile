ARG REGISTRY=vafi
FROM ${REGISTRY}/vafi-claude:latest

USER root
RUN pip install --break-system-packages mempalace

# Pre-download the 79MB ONNX embedding model into agent's cache
# so first mine/search doesn't require network access
USER agent
RUN python3 -c "from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2; \
    ef = ONNXMiniLM_L6_V2(); ef._download_model_if_not_exists()"
RUN mkdir -p ~/.mempalace

# Local entrypoint: copies host auth, injects mempalace MCP, drops to agent.
# Stays as root in image — entrypoint needs root to read mode-600 credentials,
# then drops to agent user before exec'ing the command.
USER root
COPY entrypoint-local.sh /opt/mempalace/entrypoint-local.sh
RUN chmod +x /opt/mempalace/entrypoint-local.sh
