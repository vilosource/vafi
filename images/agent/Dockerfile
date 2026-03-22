ARG REGISTRY=192.168.2.90:30500
FROM ${REGISTRY}/vafi-claude:latest

# Copy controller source code
COPY src/controller/ /opt/vf-agent/controller/

# Copy methodologies and templates
COPY methodologies/ /opt/vf-agent/methodologies/
COPY templates/ /opt/vf-agent/templates/

# Copy project configuration
COPY pyproject.toml /opt/vf-agent/

# Install the controller as a Python package
USER root
RUN pip install /opt/vf-agent/
USER agent

# Copy entrypoint script
COPY images/agent/entrypoint.sh /opt/vf-agent/entrypoint.sh
USER root
RUN chmod +x /opt/vf-agent/entrypoint.sh
USER agent

# Set entrypoint
ENTRYPOINT ["/opt/vf-agent/entrypoint.sh"]