"""Mem0 semantic memory service for compact long-term retrieval."""

import asyncio
import logging
from typing import Any

from core.config import settings

logger = logging.getLogger(__name__)


class Mem0MemoryService:
    """Thin wrapper over Mem0 for add/search memory operations."""

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        api_key: str | None = None,
        top_k: int | None = None,
        client: Any | None = None,
    ):
        self.enabled = settings.mem0.enabled if enabled is None else enabled
        self.api_key = settings.mem0.api_key if api_key is None else api_key
        self.top_k = settings.mem0.top_k if top_k is None else top_k
        self._client = client
        self._client_init_failed = False

    def _scope_user_id(self, user_id: str | None, session_id: str | None) -> str:
        if user_id:
            return user_id
        if session_id:
            return f"session:{session_id}"
        return "anonymous"

    def _build_metadata(
        self,
        *,
        session_id: str | None,
        media_id: str | None,
        project_id: str | None,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        merged: dict[str, Any] = {
            "session_id": session_id,
            "media_id": media_id,
            "project_id": project_id,
        }
        if metadata:
            merged.update(metadata)
        return merged

    def _create_client(self) -> Any:
        """Create a Mem0 client trying the most common SDK entrypoints."""
        try:
            from mem0 import MemoryClient  # type: ignore[import-not-found]

            if self.api_key:
                return MemoryClient(api_key=self.api_key)
            return MemoryClient()
        except (ImportError, AttributeError):
            pass

        from mem0 import Memory  # type: ignore[import-not-found]

        if self.api_key:
            try:
                return Memory(api_key=self.api_key)
            except TypeError:
                pass

        return Memory()

    async def _get_client(self) -> Any | None:
        if not self.enabled:
            return None
        if self._client is not None:
            return self._client
        if self._client_init_failed:
            return None

        try:
            self._client = await asyncio.to_thread(self._create_client)
            return self._client
        except (ImportError, AttributeError, TypeError, ValueError) as exc:
            logger.warning(f"Mem0 client initialization failed: {exc}")
            self._client_init_failed = True
            return None

    def _normalize_results(self, raw_results: Any) -> list[dict[str, Any]]:
        if isinstance(raw_results, dict):
            candidates = (
                raw_results.get("results")
                or raw_results.get("memories")
                or raw_results.get("data")
                or []
            )
        elif isinstance(raw_results, list):
            candidates = raw_results
        else:
            candidates = []

        normalized: list[dict[str, Any]] = []
        for item in candidates:
            if isinstance(item, str):
                normalized.append({"memory": item, "metadata": {}, "score": None, "id": None})
                continue
            if not isinstance(item, dict):
                continue

            memory_text = (
                item.get("memory")
                or item.get("text")
                or item.get("content")
                or item.get("summary")
            )
            if not isinstance(memory_text, str) or not memory_text:
                continue

            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            normalized.append(
                {
                    "id": item.get("id"),
                    "memory": memory_text,
                    "score": item.get("score"),
                    "metadata": metadata,
                }
            )

        return normalized

    async def add_memory(
        self,
        *,
        content: str,
        user_id: str | None,
        session_id: str | None,
        media_id: str | None = None,
        project_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Persist a compact semantic memory entry in Mem0."""
        if not content:
            return None

        client = await self._get_client()
        if client is None:
            return None

        scoped_user = self._scope_user_id(user_id, session_id)
        merged_metadata = self._build_metadata(
            session_id=session_id,
            media_id=media_id,
            project_id=project_id,
            metadata=metadata,
        )

        def _add():
            try:
                return client.add(
                    messages=[{"role": "user", "content": content}],
                    user_id=scoped_user,
                    metadata=merged_metadata,
                    infer=False,
                    async_mode=False,
                )
            except TypeError:
                pass

            try:
                return client.add(content, user_id=scoped_user, metadata=merged_metadata)
            except TypeError:
                return client.add(messages=content, user_id=scoped_user, metadata=merged_metadata)

        try:
            result = await asyncio.to_thread(_add)
            if isinstance(result, dict):
                return result
            return {"result": result}
        except (TypeError, ValueError, RuntimeError) as exc:
            logger.warning(f"Failed to add memory to Mem0: {exc}")
            return None

    async def search_memories(
        self,
        *,
        query: str,
        user_id: str | None,
        session_id: str | None,
        media_id: str | None = None,
        project_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Search semantically relevant memories from Mem0."""
        if not query:
            return []

        client = await self._get_client()
        if client is None:
            return []

        scoped_user = self._scope_user_id(user_id, session_id)
        search_limit = limit or self.top_k
        search_filters: dict[str, Any] = {"user_id": scoped_user}
        if project_id:
            search_filters["project_id"] = project_id

        def _search():
            try:
                return client.search(
                    query=query,
                    filters=search_filters,
                    top_k=search_limit,
                )
            except TypeError:
                pass

            try:
                return client.search(query, user_id=scoped_user, limit=search_limit)
            except TypeError:
                return client.search(query=query, user_id=scoped_user, top_k=search_limit)

        try:
            raw_results = await asyncio.to_thread(_search)
            normalized = self._normalize_results(raw_results)
        except (TypeError, ValueError, RuntimeError) as exc:
            logger.warning(f"Failed to search memories from Mem0: {exc}")
            return []

        filtered: list[dict[str, Any]] = []
        for item in normalized:
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            if media_id and metadata.get("media_id") not in (None, media_id):
                continue
            if project_id and metadata.get("project_id") not in (None, project_id):
                continue
            if session_id and metadata.get("session_id") not in (None, session_id):
                continue
            filtered.append(item)

        return filtered[:search_limit]


_mem0_memory_service: Mem0MemoryService | None = None


async def get_mem0_memory_service() -> Mem0MemoryService:
    """Get or create Mem0MemoryService singleton."""
    global _mem0_memory_service
    if _mem0_memory_service is None:
        _mem0_memory_service = Mem0MemoryService()
    return _mem0_memory_service
