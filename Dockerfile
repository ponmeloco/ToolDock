FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install curl for healthchecks and Node.js for external MCP servers (npx)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    nodejs \
    npm \
    && npm install -g npx \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user for security
RUN useradd -m appuser && chown -R appuser /app
USER appuser

# Expose ports for both transports
EXPOSE 8006 8007

# Default entrypoint
CMD ["python", "main.py"]
