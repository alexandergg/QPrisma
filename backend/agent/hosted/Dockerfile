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

# uv — pinned binary from official distroless image
COPY --from=ghcr.io/astral-sh/uv:0.11.2 /uv /uvx /bin/

# System dependencies for Neo4j driver, Redis, PostgreSQL
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Resolve and install deps only — no project build (PYTHONPATH handles imports)
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip compile pyproject.toml --extra hosted --prerelease=allow \
        --python-version 3.11 --no-header -o /tmp/requirements.txt && \
    uv pip install --system -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# Copy application code (only modules needed by the hosted agent)
COPY core/ core/
COPY models/ models/
COPY agent/ agent/
COPY services/ services/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

EXPOSE 8088

CMD ["python", "-m", "agent.hosted.main"]
