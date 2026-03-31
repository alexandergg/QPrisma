# Dockerfile para QPrisma Backend API
# FastAPI application with Azure integrations

FROM python:3.14-slim

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Directorio de trabajo
WORKDIR /app

# Copiar pyproject.toml y código fuente (necesario para editable install)
COPY pyproject.toml .
COPY api/ ./api/
COPY agent/ ./agent/
COPY core/ ./core/
COPY models/ ./models/
COPY services/ ./services/
COPY tasks/ ./tasks/
COPY evaluation/ ./evaluation/

# Instalar uv y dependencias
RUN pip install --no-cache-dir uv && \
    uv pip install --system -e .

# Copiar el resto del código (scripts, tests, etc.)
COPY . .

# Variables de entorno
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Create non-root user for security
RUN adduser --disabled-password --gecos '' --uid 1001 appuser && \
    chown -R appuser:appuser /app && \
    mkdir -p /tmp/qprisma && chown appuser:appuser /tmp/qprisma
USER appuser

# Puerto de la API
EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Comando por defecto (uvicorn con auto-reload deshabilitado para producción)
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
