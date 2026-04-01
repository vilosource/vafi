FROM python:3.12-slim

WORKDIR /app

# Install the cxdb and cxdb_mcp packages
COPY pyproject.toml .
COPY src/ src/

# Add mcp SDK dependency
RUN pip install --no-cache-dir . "mcp[cli]>=1.20" httpx

EXPOSE 8090

CMD ["python", "-m", "cxdb_mcp.server"]
