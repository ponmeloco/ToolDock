# ==================================================
# ToolDock Dockerfile
# Multi-tenant MCP Server with Web GUI
# ==================================================

FROM python:3.12-slim

# Prevent Python from writing .pyc files and ensure immediate log output
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# npm configuration for non-root user (needed for npx MCP servers)
ENV NPM_CONFIG_PREFIX=/home/appuser/.npm-global
ENV PATH=$PATH:/home/appuser/.npm-global/bin

WORKDIR /app

# 1. Install system dependencies and Node.js 20 LTS
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    git \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 2. Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 3. Create non-root user for security
RUN useradd -m -s /bin/bash appuser && \
    mkdir -p /home/appuser/.npm-global/lib && \
    mkdir -p /home/appuser/.npm-global/bin

# 4. Copy application code
COPY --chown=appuser:appuser . .

# 5. Set ownership
RUN chown -R appuser:appuser /app /home/appuser

# Switch to non-root user
USER appuser

# Expose ports:
# - 8006: OpenAPI/REST (configurable via OPENAPI_PORT)
# - 8007: MCP HTTP (configurable via MCP_PORT)
# - 8080: Web GUI (configurable via WEB_PORT)
EXPOSE 8006 8007 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${MCP_PORT:-8007}/health || exit 1

# Start server
CMD ["python", "main.py"]
