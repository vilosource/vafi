FROM python:3.12-slim

# git + ca-certificates: required for pip to resolve the vtf-sdk-python
# git+https URL declared in pyproject.toml.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install the cxdb and cxdb_mcp packages
COPY pyproject.toml .
COPY src/ src/

# Add mcp SDK dependency
RUN pip install --no-cache-dir . "mcp[cli]>=1.20" httpx

EXPOSE 8090

CMD ["python", "-m", "cxdb_mcp.server"]
