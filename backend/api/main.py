"""
QPrisma API - FastAPI Application
Procesamiento inteligente de contenido multimedia con Azure
"""

import os
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from openai import AzureOpenAI

# Agregar parent directory al path para imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Cargar variables de entorno
load_dotenv()

from core.config import settings
from core.logging_config import get_logger, setup_logging

# Initialize logging
setup_logging(level=settings.app.log_level)
logger = get_logger(__name__)

# =============================================================================
# Lazy Initialization of Azure Clients
# =============================================================================

_blob_service = None
_openai_client = None
_db_service = None


def get_blob_service():
    """Obtiene el cliente de Azure Blob Storage"""
    global _blob_service
    if _blob_service is None:
        conn_string = settings.azure.storage_connection_string
        if conn_string:
            _blob_service = BlobServiceClient.from_connection_string(conn_string)
    return _blob_service


def get_database_service():
    """Obtiene el servicio de PostgreSQL"""
    global _db_service
    if _db_service is None:
        from services.database_service import get_database_service as get_db

        _db_service = get_db()
    return _db_service


def get_openai_client():
    """Obtiene el cliente de Azure OpenAI"""
    global _openai_client
    if _openai_client is None:
        endpoint = settings.azure.openai_endpoint
        api_key = settings.azure.openai_api_key

        if endpoint and api_key:
            _openai_client = AzureOpenAI(
                azure_endpoint=endpoint,
                api_key=api_key,
                api_version=settings.azure.openai_api_version,
            )
    return _openai_client


# =============================================================================
# Lifespan Context Manager
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    import asyncio
    import sys

    # Fix Windows console encoding for emojis
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    # Startup
    print("=" * 50)
    print("QPrisma API v0.3.0")
    print("=" * 50)
    print(f"📍 Entorno: {settings.app.environment}")
    print(f"📊 Azure OpenAI: {'✓' if get_openai_client() else '✗'}")
    print(f"💾 Azure Storage: {'✓' if get_blob_service() else '✗'}")
    db = get_database_service()
    db_health = db.health_check() if db else {"status": "not_configured"}
    print(f"🗄️  PostgreSQL: {'✓' if db_health.get('status') == 'healthy' else '✗'}")

    # Initialize Redis Pub/Sub listener for WebSocket events from Celery
    pubsub_task = None
    try:
        from api.routes.websocket_manager import get_pubsub_manager
        pubsub_manager = await get_pubsub_manager()
        pubsub_task = asyncio.create_task(pubsub_manager.listen())
        print("📡 Redis Pub/Sub: ✓ (WebSocket sync enabled)")
    except Exception as e:
        print(f"📡 Redis Pub/Sub: ✗ ({e})")

    print("=" * 50)

    yield  # Application runs here

    # Shutdown (cleanup if needed)
    print("👋 QPrisma API shutting down...")

    # Stop Redis Pub/Sub listener
    if pubsub_task:
        pubsub_task.cancel()
        try:
            await pubsub_task
        except asyncio.CancelledError:
            pass

        try:
            from api.routes.websocket_manager import _pubsub_manager
            if _pubsub_manager:
                await _pubsub_manager.disconnect()
        except Exception:
            pass


# =============================================================================
# App Initialization
# =============================================================================

app = FastAPI(
    title="QPrisma API",
    description="Procesamiento Inteligente de Contenido Multimedia",
    version="0.2.0",
    lifespan=lifespan,
)

# Configuración CORS
allowed_origins = settings.app.cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

# =============================================================================
# Include Routers
# =============================================================================

from api.routes import (
    a2a_router,
    auth_router,
    batch_router,
    cache_router,
    chat_router,
    chunked_upload_router,
    editor_router,
    graph_router,
    jobs_router,
    media_router,
    processing_router,
    storage_router,
    structure_router,
    websocket_router,
)

# A2A Protocol routes (Agent-to-Agent communication)
app.include_router(a2a_router, tags=["A2A Protocol"])

app.include_router(auth_router, prefix="/auth", tags=["Authentication"])
app.include_router(batch_router, tags=["Batch API"])
app.include_router(cache_router, prefix="/cache", tags=["Cache"])
app.include_router(chat_router, tags=["Chat & Search"])
app.include_router(chunked_upload_router, tags=["Chunked Upload"])
app.include_router(editor_router, tags=["Video Editor"])
app.include_router(graph_router, tags=["Knowledge Graph"])
app.include_router(jobs_router, prefix="/jobs", tags=["Jobs"])
app.include_router(media_router, tags=["Media"])
app.include_router(processing_router, tags=["Processing"])
app.include_router(storage_router, tags=["Storage Tiering"])
app.include_router(structure_router, tags=["Structure"])
app.include_router(websocket_router, prefix="/ws", tags=["WebSocket"])


# =============================================================================
# Core Endpoints
# =============================================================================


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "version": "0.2.0",
        "azure_configured": bool(get_openai_client() and get_blob_service()),
    }


@app.get("/health")
async def health_check():
    """Detailed health check de todos los servicios"""
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


@app.get("/config")
async def get_config():
    """Retorna el estado de configuración"""
    db = get_database_service()
    db_healthy = db and db.health_check().get("status") == "healthy"
    return {
        "azure_openai_configured": bool(get_openai_client()),
        "azure_storage_configured": bool(get_blob_service()),
        "postgresql_configured": db_healthy,
        "knowledge_graph_configured": settings.neo4j.is_configured,
        "redis_configured": settings.redis.is_configured,
        "environment": settings.app.environment,
    }


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.app.port,
        reload=False,
    )
