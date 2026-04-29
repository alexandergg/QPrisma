# syntax=docker/dockerfile:1.7
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

FROM python:3.11-slim AS builder

# uv — pinned binary from official distroless image
COPY --from=ghcr.io/astral-sh/uv:0.11.2 /uv /uvx /bin/

# Build dependencies for packages that may not have wheels on every linux/amd64 resolver path.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps from pre-compiled lock file for reproducible builds.
# To regenerate: cd backend && uv pip compile pyproject.toml --extra hosted --prerelease=allow --python-version 3.11 -o agent/hosted/requirements-hosted.txt
COPY agent/hosted/requirements-hosted.txt /tmp/requirements.txt
RUN python -m venv /opt/venv
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python /opt/venv/bin/python -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

FROM python:3.11-slim AS runtime

# Runtime-only native libraries. Keep build toolchains out of the final image.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/* && \
    groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --create-home --shell /usr/sbin/nologin appuser

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

# Copy application code (only modules needed by the hosted agent)
COPY --chown=appuser:appgroup core/ core/
COPY --chown=appuser:appgroup models/ models/
COPY --chown=appuser:appgroup agent/ agent/
COPY --chown=appuser:appgroup services/ services/

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app
ENV PATH="/opt/venv/bin:${PATH}"
ENV HOME=/home/appuser

EXPOSE 8088

USER appuser

CMD ["python", "-m", "agent.hosted.main"]
