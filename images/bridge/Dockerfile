ARG REGISTRY=vafi
FROM ${REGISTRY}/vafi-pi:latest

USER root

# Install bridge dependencies
RUN pip install --break-system-packages fastapi uvicorn httpx kubernetes_asyncio pyyaml

# Copy bridge source + shared libs (pi_session_history is used by the
# Phase 9 GET /v1/sessions/history endpoint)
COPY src/bridge/ /opt/vf-bridge/src/bridge/
COPY src/lib/ /opt/vf-bridge/src/lib/

USER agent

EXPOSE 8080

CMD ["uvicorn", "bridge.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--log-level", "info"]

ENV PYTHONPATH=/opt/vf-bridge/src
