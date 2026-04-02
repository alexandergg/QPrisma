"""
Foundry Memory Store Service
=============================

Wraps the Azure AI Foundry Memory Store API for long-term user memory.

Memory is scoped per Entra ID user (``{tid}_{oid}`` format) and automatically
summarises conversation topics, extracts user preferences, and provides
semantic search across past interactions.

This replaces the previous Mem0-based memory implementation.

Usage::

    from services.foundry_memory_service import get_foundry_memory_service

    service = get_foundry_memory_service()
    if service.enabled:
        await service.update_memories(scope="tid_oid", messages=[...])
        results = await service.search_memories(scope="tid_oid", query="coffee preferences")
"""

import asyncio
import logging
from typing import Any

from core.config import settings

logger = logging.getLogger(__name__)


class FoundryMemoryService:
    """
    Long-term memory via Azure AI Foundry Memory Store.

    Uses ``project_client.beta.memory_stores`` to store and retrieve
    per-user memories. Memory extraction runs asynchronously after each
    conversation turn (fire-and-forget) so it does not block responses.
    """

    def __init__(
        self,
        *,
        project_endpoint: str | None = None,
        memory_store_name: str | None = None,
        chat_model: str | None = None,
        embedding_model: str | None = None,
    ):
        self._project_endpoint = project_endpoint or settings.foundry.project_endpoint
        self._memory_store_name = memory_store_name or settings.foundry.memory_store_name
        self._chat_model = chat_model or settings.foundry.memory_chat_model
        self._embedding_model = embedding_model or settings.foundry.memory_embedding_model
        self._project_client = None

    @property
    def enabled(self) -> bool:
        """True if memory store is configured."""
        return bool(
            self._project_endpoint
            and self._memory_store_name
            and self._chat_model
            and self._embedding_model
        )

    def _get_project_client(self):
        """Lazy-initialise the AIProjectClient."""
        if self._project_client is not None:
            return self._project_client

        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential

        self._project_client = AIProjectClient(
            endpoint=self._project_endpoint,
            credential=DefaultAzureCredential(),
        )
        return self._project_client

    async def ensure_memory_store(self) -> dict[str, Any]:
        """
        Create the memory store if it does not exist (idempotent).

        Returns:
            Dict with 'name', 'id', and 'description' of the store.
        """
        if not self.enabled:
            return {"error": "Memory store not configured"}

        client = self._get_project_client()

        try:
            store = await asyncio.to_thread(
                client.beta.memory_stores.get,
                self._memory_store_name,
            )
            logger.info(
                "Memory store already exists: %s (%s)",
                store.name,
                store.id,
            )
            return {"name": store.name, "id": store.id, "description": store.description}
        except Exception:
            logger.debug("Memory store '%s' not found — will create", self._memory_store_name)

        try:
            from azure.ai.projects.models import (
                MemoryStoreDefaultDefinition,
                MemoryStoreDefaultOptions,
            )

            options = MemoryStoreDefaultOptions(
                user_profile_enabled=True,
                user_profile_details=(
                    "Video analysis preferences, preferred languages, "
                    "topics of interest, and interaction patterns"
                ),
                chat_summary_enabled=True,
            )
            definition = MemoryStoreDefaultDefinition(
                chat_model=self._chat_model,
                embedding_model=self._embedding_model,
                options=options,
            )
            store = await asyncio.to_thread(
                client.beta.memory_stores.create,
                name=self._memory_store_name,
                description="QPrisma user memory store",
                definition=definition,
            )
            logger.info(
                "Created memory store: %s (%s)",
                store.name,
                store.id,
            )
            return {"name": store.name, "id": store.id, "description": store.description}

        except Exception as e:
            logger.error("Failed to create memory store: %s", e)
            return {"error": str(e)}

    async def update_memories(
        self,
        scope: str,
        messages: str | list[dict[str, str]],
        *,
        update_delay: int = 0,
        previous_update_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Extract and store memories from conversation messages.

        Args:
            scope: User scope — typically ``{tid}_{oid}`` from Entra ID token.
            messages: Plain text or list of message dicts to extract memories from.
            update_delay: Seconds of inactivity before processing (0 = immediate).
            previous_update_id: Chain with a previous update for batching.

        Returns:
            Dict with 'update_id' and 'status'.
        """
        if not self.enabled:
            return {"skipped": True, "reason": "Memory store not configured"}

        client = self._get_project_client()

        try:
            kwargs: dict[str, Any] = {
                "name": self._memory_store_name,
                "scope": scope,
                "items": messages,
                "update_delay": update_delay,
            }
            if previous_update_id:
                kwargs["previous_update_id"] = previous_update_id

            poller = await asyncio.to_thread(
                client.beta.memory_stores.begin_update_memories,
                **kwargs,
            )

            logger.info(
                "Scheduled memory update (id=%s, scope=%s)",
                poller.update_id,
                scope,
            )
            return {"update_id": poller.update_id, "status": poller.status()}

        except Exception as e:
            logger.warning("Memory update failed (non-blocking): %s", e)
            return {"error": str(e)}

    async def search_memories(
        self,
        scope: str,
        query: str,
        *,
        max_memories: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Search stored memories for a user.

        Args:
            scope: User scope (Entra ID ``{tid}_{oid}``).
            query: Natural language search query.
            max_memories: Maximum number of memories to return.

        Returns:
            List of memory dicts with 'memory_id' and 'content'.
        """
        if not self.enabled:
            return []

        client = self._get_project_client()

        try:
            from azure.ai.projects.models import MemorySearchOptions

            response = await asyncio.to_thread(
                client.beta.memory_stores.search_memories,
                name=self._memory_store_name,
                scope=scope,
                items=query,
                options=MemorySearchOptions(max_memories=max_memories),
            )

            memories = [
                {
                    "memory_id": m.memory_item.memory_id,
                    "content": m.memory_item.content,
                }
                for m in response.memories
            ]

            logger.info(
                "Found %d memories for scope=%s query=%r",
                len(memories),
                scope,
                query[:50],
            )
            return memories

        except Exception as e:
            logger.warning("Memory search failed: %s", e)
            return []

    async def delete_user_memories(self, scope: str) -> bool:
        """Delete all memories for a user scope."""
        if not self.enabled:
            return False

        client = self._get_project_client()

        try:
            await asyncio.to_thread(
                client.beta.memory_stores.delete_scope,
                name=self._memory_store_name,
                scope=scope,
            )
            logger.info("Deleted memories for scope=%s", scope)
            return True
        except Exception as e:
            logger.warning("Failed to delete memories for scope=%s: %s", scope, e)
            return False


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_memory_service: FoundryMemoryService | None = None


def get_foundry_memory_service() -> FoundryMemoryService:
    """Get or create the global Foundry Memory Service."""
    global _memory_service

    if _memory_service is None:
        _memory_service = FoundryMemoryService()
        if _memory_service.enabled:
            logger.info(
                "Foundry Memory Service initialized (store=%s)",
                settings.foundry.memory_store_name,
            )
        else:
            logger.info("Foundry Memory Service disabled (not configured)")

    return _memory_service
