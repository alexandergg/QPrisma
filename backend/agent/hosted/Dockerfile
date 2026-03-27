# QPrisma Video Agent — Azure AI Foundry Hosted Agent Container
# ==============================================================
# Builds a linux/amd64 image for deployment as a Foundry Hosted Agent.
#
# Build:
#   docker build --platform linux/amd64 -t qprisma-video-agent -f agent/hosted/Dockerfile .
#
# Run locally:
#   docker run --platform linux/amd64 -p 8088:8088 --env-file .env qprisma-video-agent
#
# The container exposes port 8088 (Foundry hosting adapter default).

FROM python:3.11-slim AS base

# System dependencies for Neo4j driver, Redis, PostgreSQL
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv && \
    uv pip install --system --no-cache -e ".[hosted]"

# Copy application code
# Only copy modules needed by the hosted agent (not api/, tasks/)
COPY core/ core/
COPY models/ models/
COPY agent/ agent/
COPY services/ services/

# Hosted agent entry point
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

EXPOSE 8088

CMD ["python", "-m", "agent.hosted.main"]
