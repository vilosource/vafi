ARG REGISTRY=vafi
FROM ${REGISTRY}/vafi-claude:latest

USER root
RUN pip install --break-system-packages mempalace

# Pre-download the 79MB ONNX embedding model into agent's cache
USER agent
RUN python3 -c "from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2; \
    ef = ONNXMiniLM_L6_V2(); ef._download_model_if_not_exists()"
RUN mkdir -p ~/.mempalace

# Entrypoint runs as agent (no root needed — credentials passed via env var)
USER root
COPY entrypoint-local.sh /opt/mempalace/entrypoint-local.sh
RUN chmod +x /opt/mempalace/entrypoint-local.sh

RUN chmod 777 /home/agent

USER agent
WORKDIR /workspace
ENTRYPOINT ["/opt/mempalace/entrypoint-local.sh"]
CMD ["claude", "--dangerously-skip-permissions"]
