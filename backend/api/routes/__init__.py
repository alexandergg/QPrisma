"""
API Routes Package

This package contains all the route modules for the QPrisma API.
Each module handles a specific domain of functionality.
"""

from api.routes.a2a_routes import router as a2a_router
from api.routes.auth_routes import router as auth_router
from api.routes.batch_routes import router as batch_router
from api.routes.benchmark_routes import router as benchmark_router
from api.routes.cache_routes import router as cache_router
from api.routes.chat_routes import router as chat_router
from api.routes.chunked_upload_routes import router as chunked_upload_router
from api.routes.graph_routes import router as graph_router
from api.routes.jobs_routes import router as jobs_router
from api.routes.media_routes import router as media_router
from api.routes.processing_routes import router as processing_router
from api.routes.storage_routes import router as storage_router
from api.routes.structure_routes import router as structure_router
from api.routes.websocket_routes import router as websocket_router

__all__ = [
    "a2a_router",
    "auth_router",
    "batch_router",
    "benchmark_router",
    "cache_router",
    "chat_router",
    "chunked_upload_router",
    "graph_router",
    "jobs_router",
    "media_router",
    "processing_router",
    "storage_router",
    "structure_router",
    "websocket_router",
]
