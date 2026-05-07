"""
QPrisma API - FastAPI Application
Intelligent multimedia content processing with Azure
"""

import importlib.metadata
import os
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime

try:
    _VERSION = importlib.metadata.version("qprisma-backend")
except importlib.metadata.PackageNotFoundError:
    _VERSION = "0.0.0-dev"

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables
load_dotenv()

from api.openapi_responses import SERVICE_RESPONSES
from core.config import settings
from core.logging_config import get_logger, setup_logging
from models.core_schemas import ConfigStatusResponse, HealthCheckResponse, RootStatusResponse

# Initialize logging
setup_logging(level=settings.app.log_level)
logger = get_logger(__name__)

# =============================================================================
# Service Getters (consolidated in api.dependencies)
# =============================================================================

from api.dependencies import get_blob_service, get_openai_client
from services.database_service import get_database_service

# =============================================================================
# Telemetry (Azure Monitor + OpenTelemetry)
# =============================================================================


def _setup_telemetry() -> None:
    """Configure Azure Monitor and OpenAI instrumentation if a connection string is set."""
    import os

    conn_str = settings.telemetry.applicationinsights_connection_string
    if not conn_str:
        logger.info("Application Insights: not configured (no connection string)")
        return

    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        from opentelemetry.instrumentation.openai_v2 import OpenAIInstrumentor

        # Control GenAI content capture (prompts/completions may contain PII)
        os.environ.setdefault(
            "AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED",
            str(settings.telemetry.enable_content_recording).lower(),
        )
        os.environ.setdefault("OTEL_SERVICE_NAME", settings.telemetry.otel_service_name)

        configure_azure_monitor(connection_string=conn_str)
        OpenAIInstrumentor().instrument()

        # Register span processor so gen_ai.conversation.id appears in Foundry traces
        try:
            from agent.utils.observability import ConversationIdSpanProcessor
            from opentelemetry.trace import get_tracer_provider

            provider = get_tracer_provider()
            if hasattr(provider, "add_span_processor"):
                provider.add_span_processor(ConversationIdSpanProcessor())
                logger.info("ConversationIdSpanProcessor: registered")
        except Exception as e:
            logger.warning("ConversationIdSpanProcessor: failed to register (%s)", e)

        logger.info(
            "Application Insights: enabled (service=%s)",
            settings.telemetry.otel_service_name,
        )
    except ImportError:
        logger.warning(
            "Application Insights: packages not installed "
            "(pip install azure-monitor-opentelemetry opentelemetry-instrumentation-openai-v2)"
        )
    except Exception as e:
        logger.warning("Application Insights: failed to initialize (%s)", e)


# =============================================================================
# Lifespan Context Manager
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    import sys

    # Fix Windows console encoding for emojis
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # --- Azure Monitor / OpenTelemetry tracing ---
    _setup_telemetry()

    # Startup
    logger.info("=" * 50)
    logger.info("QPrisma API v%s", _VERSION)
    logger.info("=" * 50)
    logger.info("Environment: %s", settings.app.environment)
    disable_startup_checks = settings.app.disable_startup_healthchecks
    if disable_startup_checks:
        logger.info("Azure OpenAI: skipped (startup checks disabled)")
        logger.info("Azure Storage: skipped (startup checks disabled)")
        logger.info("PostgreSQL: skipped (startup checks disabled)")
    else:
        logger.info("Azure OpenAI: %s", "ok" if get_openai_client() else "not configured")
        logger.info("Azure Storage: %s", "ok" if get_blob_service() else "not configured")
        db = get_database_service()
        db_health = db.health_check() if db else {"status": "not_configured"}
        logger.info(
            "PostgreSQL: %s",
            "ok" if db_health.get("status") == "healthy" else "not configured",
        )

    logger.info("=" * 50)

    # --- Neo4j Knowledge Graph ---
    if disable_startup_checks:
        logger.info("Neo4j Knowledge Graph: skipped (startup checks disabled)")
    else:
        try:
            from services.async_graph_facade import get_async_knowledge_graph_facade

            kg_facade = get_async_knowledge_graph_facade()
            connected = await kg_facade.connect()
            logger.info(
                "Neo4j Knowledge Graph: %s",
                "ok" if connected else "connection failed",
            )
        except Exception as e:
            logger.warning("Neo4j Knowledge Graph: failed (%s)", e)

    yield  # Application runs here

    # Shutdown (cleanup if needed)
    logger.info("QPrisma API shutting down...")

    # Disconnect Neo4j (only if we connected during startup)
    if not disable_startup_checks:
        try:
            from services.async_graph_facade import get_async_knowledge_graph_facade

            kg_facade = get_async_knowledge_graph_facade()
            if kg_facade.is_connected:
                await kg_facade.disconnect()
                logger.info("Neo4j disconnected")
        except Exception:
            logger.debug("Neo4j disconnect failed during shutdown", exc_info=True)


# =============================================================================
# App Initialization
# =============================================================================

app = FastAPI(
    title="QPrisma API",
    description="Intelligent Multimedia Content Processing",
    version=_VERSION,
    lifespan=lifespan,
)

# Rate Limiting
from api.rate_limit import limiter

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS Configuration
allowed_origins = settings.app.cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Content-Type", "Authorization"],
    max_age=600,
)


# Security Headers Middleware
# NOTE: Placed after CORS middleware so it executes before CORS in the
# middleware stack (FastAPI middleware order is LIFO).
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security headers to every response."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if settings.app.environment.lower() not in ("dev", "development", "test", "local"):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# =============================================================================
# Include Routers
# =============================================================================

from api.routes import (
    a2a_router,
    auth_router,
    benchmark_router,
    cache_router,
    chunked_upload_router,
    graph_router,
    media_router,
    processing_router,
    storage_router,
    structure_router,
)

# A2A Protocol routes (Agent-to-Agent communication)
app.include_router(a2a_router, tags=["A2A Protocol"])

app.include_router(auth_router, prefix="/auth", tags=["Authentication"])
app.include_router(benchmark_router, tags=["Benchmark"])
app.include_router(cache_router, prefix="/cache", tags=["Cache"])
app.include_router(chunked_upload_router, tags=["Chunked Upload"])
app.include_router(graph_router, tags=["Knowledge Graph"])
app.include_router(media_router, tags=["Media"])
app.include_router(processing_router, tags=["Processing"])
app.include_router(storage_router, tags=["Storage Tiering"])
app.include_router(structure_router, tags=["Structure"])


# =============================================================================
# Core Endpoints
# =============================================================================


@app.get(
    "/",
    response_model=RootStatusResponse,
    summary="Public API liveness",
    description="Public liveness endpoint used by startup probes and simple availability checks.",
)
async def root():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "version": _VERSION,
        "azure_configured": bool(get_openai_client() and get_blob_service()),
    }


@app.get(
    "/health",
    response_model=HealthCheckResponse,
    summary="Public API readiness",
    description=(
        "Public readiness endpoint used by Docker, Azure Container Apps probes, and deployment "
        "health checks. The response shape remains probe-compatible."
    ),
    responses=SERVICE_RESPONSES,
)
async def health_check():
    """Detailed health check of all services"""
    services = {
        "api": "healthy",
        "blob_storage": "not_configured",
        "postgresql": "not_configured",
        "openai": "not_configured",
        "knowledge_graph": "not_configured",
    }

    if get_blob_service():
        services["blob_storage"] = "configured"

    db = get_database_service()
    if db:
        db_health = db.health_check()
        services["postgresql"] = db_health.get("status", "unknown")

    if get_openai_client():
        services["openai"] = "configured"

    if settings.neo4j.is_configured:
        services["knowledge_graph"] = "configured"

    return {"status": "healthy", "services": services, "timestamp": datetime.now(UTC).isoformat()}


@app.get(
    "/config",
    response_model=ConfigStatusResponse,
    summary="Public configuration status",
    description=(
        "Public, non-secret configuration status for diagnostics. Do not expose tenant IDs, "
        "connection strings, endpoints, or other sensitive values here."
    ),
)
async def get_config():
    """Returns the configuration status"""
    db = get_database_service()
    db_healthy = db and db.health_check().get("status") == "healthy"
    return {
        "azure_openai_configured": bool(get_openai_client()),
        "azure_storage_configured": bool(get_blob_service()),
        "postgresql_configured": db_healthy,
        "knowledge_graph_configured": settings.neo4j.is_configured,
        "cache_backend": "memory",
    }


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",  # noqa: S104 — bind all interfaces for container deployment
        port=settings.app.port,
        reload=False,
    )
