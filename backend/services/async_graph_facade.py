"""Async facade over :class:`KnowledgeGraphService`.

Wraps **every** sync method call with :func:`asyncio.to_thread` so that
FastAPI route handlers and other async code never block the event loop
on Neo4j I/O.

The underlying sync service is unchanged, so tests and sync maintenance
scripts can continue to use it directly.

Usage in route handlers::

    facade = get_async_knowledge_graph_facade()
    stats = await facade.get_stats(user_id="abc")

Design notes
------------
* ``__getattr__`` auto-wraps any method not explicitly defined, so this
  facade stays in sync with new methods added to the underlying service
  without requiring code changes here.
* Explicit properties (``is_connected``) bypass the wrapping layer.
* ``connect()`` and ``disconnect()`` are explicitly async for use in
  the FastAPI lifespan handler.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from services.knowledge_graph import KnowledgeGraphService

logger = logging.getLogger(__name__)


class AsyncKnowledgeGraphFacade:
    """Non-blocking facade for :class:`KnowledgeGraphService`.

    Every sync method on the wrapped service is dispatched to a thread
    via :func:`asyncio.to_thread`, keeping the FastAPI event loop free.
    """

    __slots__ = ("_sync", "_cache")

    def __init__(self, sync_service: KnowledgeGraphService) -> None:
        object.__setattr__(self, "_sync", sync_service)
        object.__setattr__(self, "_cache", {})

    # ------------------------------------------------------------------
    # Properties (no thread dispatch needed)
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """Check connection status (fast, non-blocking)."""
        return self._sync.is_connected

    @property
    def sync_service(self) -> KnowledgeGraphService:
        """Access the underlying sync service for tests and maintenance scripts."""
        return self._sync

    # ------------------------------------------------------------------
    # Lifecycle — explicit async wrappers
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Connect to Neo4j (runs in thread pool)."""
        return await asyncio.to_thread(self._sync.connect)

    async def disconnect(self) -> None:
        """Disconnect from Neo4j (runs in thread pool)."""
        await asyncio.to_thread(self._sync.disconnect)

    # ------------------------------------------------------------------
    # Auto-wrapping for everything else
    # ------------------------------------------------------------------

    def __getattr__(self, name: str) -> Any:
        """Wrap sync methods as async on first access, then cache."""
        cache: dict = object.__getattribute__(self, "_cache")
        if name in cache:
            return cache[name]

        attr = getattr(self._sync, name)
        if not callable(attr):
            return attr

        @functools.wraps(attr)
        async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
            return await asyncio.to_thread(attr, *args, **kwargs)

        cache[name] = _async_wrapper
        return _async_wrapper

    def __repr__(self) -> str:
        connected = self.is_connected
        return f"<AsyncKnowledgeGraphFacade connected={connected}>"


# =============================================================================
# Singleton
# =============================================================================

_async_facade: AsyncKnowledgeGraphFacade | None = None


def get_async_knowledge_graph_facade() -> AsyncKnowledgeGraphFacade:
    """Return the singleton async facade.

    The underlying sync service is created lazily on first call.  After
    that the same facade is reused for all callers.
    """
    global _async_facade
    if _async_facade is None:
        from services.knowledge_graph import get_knowledge_graph_service

        sync_svc = get_knowledge_graph_service()
        _async_facade = AsyncKnowledgeGraphFacade(sync_svc)
    return _async_facade
