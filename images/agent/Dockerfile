ARG REGISTRY=vafi
ARG HARNESS_IMAGE=${REGISTRY}/vafi-claude:latest
FROM ${HARNESS_IMAGE}

# Copy controller source code (pyproject.toml expects src/ layout)
COPY src/ /opt/vf-agent/src/

# Copy methodologies and templates
COPY methodologies/ /opt/vf-agent/methodologies/
COPY templates/ /opt/vf-agent/templates/

# Copy project configuration
COPY pyproject.toml /opt/vf-agent/

# Install the controller as a Python package
USER root
RUN pip install --break-system-packages /opt/vf-agent/
USER agent

# Copy agent scripts
COPY images/agent/pi_config.py /opt/vf-agent/pi_config.py
COPY images/agent/hydrate_context.py /opt/vf-agent/hydrate_context.py

# Copy entrypoint script
COPY images/agent/entrypoint.sh /opt/vf-agent/entrypoint.sh
USER root
RUN chmod +x /opt/vf-agent/entrypoint.sh
USER agent

# Set entrypoint
ENTRYPOINT ["/opt/vf-agent/entrypoint.sh"]