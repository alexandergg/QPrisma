"""Tests for Mem0MemoryService wrapper."""

import pytest

from services.mem0_memory_service import Mem0MemoryService


class FakeMem0Client:
    def __init__(self):
        self.add_calls = []
        self.search_calls = []
        self.search_response = {"results": []}

    def add(self, *args, **kwargs):
        content = args[0] if args else kwargs.get("messages", "")
        self.add_calls.append({"content": content, **kwargs})
        return {"id": "mem-1", "memory": content}

    def search(self, *args, **kwargs):
        query = args[0] if args else kwargs.get("query")
        self.search_calls.append({"query": query, **kwargs})
        return self.search_response


@pytest.mark.unit
class TestMem0MemoryService:
    @pytest.mark.asyncio
    async def test_disabled_service_is_noop(self):
        service = Mem0MemoryService(enabled=False, client=FakeMem0Client())

        add_result = await service.add_memory(
            content="tool summary",
            user_id="user-1",
            session_id="session-1",
        )
        search_result = await service.search_memories(
            query="summary",
            user_id="user-1",
            session_id="session-1",
        )

        assert add_result is None
        assert search_result == []

    @pytest.mark.asyncio
    async def test_add_memory_passes_scope_and_metadata(self):
        client = FakeMem0Client()
        service = Mem0MemoryService(enabled=True, client=client)

        await service.add_memory(
            content="search_video: retrieved 3 result(s)",
            user_id="user-2",
            session_id="session-2",
            media_id="media-2",
            project_id="project-2",
            metadata={"tool_name": "search_video", "artifact_id": "artifact-123"},
        )

        assert len(client.add_calls) == 1
        call = client.add_calls[0]
        assert call["user_id"] == "user-2"
        assert call["metadata"]["media_id"] == "media-2"
        assert call["metadata"]["project_id"] == "project-2"
        assert call["metadata"]["artifact_id"] == "artifact-123"

    @pytest.mark.asyncio
    async def test_search_memories_normalizes_and_filters_results(self):
        client = FakeMem0Client()
        client.search_response = {
            "results": [
                {
                    "id": "m1",
                    "memory": "User asked about intro scene",
                    "score": 0.92,
                    "metadata": {"session_id": "session-3", "media_id": "media-3"},
                },
                {
                    "id": "m2",
                    "memory": "Different media entry",
                    "score": 0.75,
                    "metadata": {"session_id": "session-3", "media_id": "other-media"},
                },
            ]
        }
        service = Mem0MemoryService(enabled=True, client=client, top_k=5)

        results = await service.search_memories(
            query="intro",
            user_id="user-3",
            session_id="session-3",
            media_id="media-3",
            limit=3,
        )

        assert len(client.search_calls) == 1
        search_call = client.search_calls[0]
        assert search_call["filters"]["user_id"] == "user-3"
        assert search_call["top_k"] == 3
        assert len(results) == 1
        assert results[0]["id"] == "m1"
        assert results[0]["memory"] == "User asked about intro scene"
