"""
API Routes Package

This package contains all the route modules for the QPrisma API.
Each module handles a specific domain of functionality.
"""

from api.routes.auth_routes import router as auth_router
from api.routes.batch_routes import router as batch_router
from api.routes.cache_routes import router as cache_router
from api.routes.chat_routes import router as chat_router
from api.routes.editor_routes import router as editor_router
from api.routes.graph_routes import router as graph_router
from api.routes.jobs_routes import router as jobs_router
from api.routes.media_routes import router as media_router
from api.routes.processing_routes import router as processing_router
from api.routes.storage_routes import router as storage_router
from api.routes.structure_routes import router as structure_router
from api.routes.websocket_routes import router as websocket_router

__all__ = [
    "auth_router",
    "batch_router",
    "cache_router",
    "chat_router",
    "editor_router",
    "graph_router",
    "jobs_router",
    "media_router",
    "processing_router",
    "storage_router",
    "structure_router",
    "websocket_router",
]
