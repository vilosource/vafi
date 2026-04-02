ARG REGISTRY=vafi
FROM ${REGISTRY}/vafi-pi:latest

USER root

# Install bridge dependencies
RUN pip install --break-system-packages fastapi uvicorn httpx kubernetes_asyncio pyyaml

# Copy bridge source
COPY src/bridge/ /opt/vf-bridge/src/bridge/

USER agent

EXPOSE 8080

CMD ["uvicorn", "bridge.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--log-level", "info"]

ENV PYTHONPATH=/opt/vf-bridge/src
