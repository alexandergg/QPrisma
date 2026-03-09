"""Tests for compact memory and artifact references in agent context updates."""

from unittest.mock import AsyncMock, patch

import pytest
from agent.nodes.base import (
    _rehydrate_artifact_context,
    _retrieve_external_memories,
    _retrieve_hybrid_memory_context,
    update_context_node,
)
from agent.utils.observability import Metrics
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig


@pytest.mark.unit
class TestAgentMemoryContext:
    @pytest.mark.asyncio
    async def test_update_context_adds_memory_without_artifact_storage(self):
        state = {
            "messages": [
                HumanMessage(content="Find key moments"),
                ToolMessage(
                    content='{"count": 2, "results": [{"timestamp": 12.5}, {"timestamp": 48.0}]}',
                    tool_call_id="tc-1",
                    name="search_video",
                ),
            ],
            "conversation_context": [],
            "partial_results": [],
            "memory_context": [],
            "artifact_refs": [],
            "session_id": "session-1",
            "user_id": "user-1",
            "media_id": "media-1",
            "project_id": None,
            "project_context": None,
        }
        config = RunnableConfig(configurable={"thread_id": "session-1"})

        with patch("core.config.settings.azure.storage_connection_string", None):
            updated = await update_context_node(state, config)

        assert len(updated["memory_context"]) == 1
        assert "search_video" in updated["memory_context"][0]
        assert updated["artifact_refs"] == []
        assert len(updated["partial_results"]) == 1
        assert updated["partial_results"][0]["artifact_id"] is None

    @pytest.mark.asyncio
    async def test_update_context_adds_artifact_reference_when_enabled(self):
        mock_artifact_service = AsyncMock()
        mock_artifact_service.save_artifact = AsyncMock(return_value={"id": "artifact-123"})

        state = {
            "messages": [
                HumanMessage(content="Find key moments"),
                ToolMessage(
                    content='{"count": 1, "results": [{"timestamp": 90.0}]}',
                    tool_call_id="tc-2",
                    name="search_video",
                ),
            ],
            "conversation_context": [],
            "partial_results": [],
            "memory_context": [],
            "artifact_refs": [],
            "session_id": "session-2",
            "user_id": "user-2",
            "media_id": "media-2",
            "project_id": None,
            "project_context": None,
        }
        config = RunnableConfig(configurable={"thread_id": "session-2"})

        with (
            patch(
                "core.config.settings.azure.storage_connection_string", "UseDevelopmentStorage=true"
            ),
            patch(
                "services.tool_artifact_service.get_tool_artifact_service",
                AsyncMock(return_value=mock_artifact_service),
            ),
        ):
            updated = await update_context_node(state, config)

        assert len(updated["artifact_refs"]) == 1
        assert updated["artifact_refs"][0]["artifact_id"] == "artifact-123"
        assert "[artifact:artifact-123]" in updated["memory_context"][0]
        assert updated["partial_results"][0]["artifact_id"] == "artifact-123"
        mock_artifact_service.save_artifact.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_context_persists_summary_to_external_memory(self):
        mock_mem0_service = AsyncMock()
        mock_mem0_service.add_memory = AsyncMock(return_value={"id": "mem-1"})

        state = {
            "messages": [
                HumanMessage(content="Find key moments"),
                ToolMessage(
                    content='{"count": 1, "results": [{"timestamp": 90.0}]}',
                    tool_call_id="tc-3",
                    name="search_video",
                ),
            ],
            "conversation_context": [],
            "partial_results": [],
            "memory_context": [],
            "artifact_refs": [],
            "session_id": "session-3",
            "user_id": "user-3",
            "media_id": "media-3",
            "project_id": None,
            "project_context": None,
        }
        config = RunnableConfig(configurable={"thread_id": "session-3"})

        with (
            patch("core.config.settings.azure.storage_connection_string", None),
            patch("core.config.settings.mem0.enabled", True),
            patch(
                "services.mem0_memory_service.get_mem0_memory_service",
                AsyncMock(return_value=mock_mem0_service),
            ),
        ):
            await update_context_node(state, config)

        mock_mem0_service.add_memory.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_retrieve_external_memories_formats_artifact_refs(self):
        mock_mem0_service = AsyncMock()
        mock_mem0_service.search_memories = AsyncMock(
            return_value=[
                {
                    "memory": "Important summary from previous turn",
                    "metadata": {"artifact_id": "artifact-456"},
                }
            ]
        )

        state = {
            "messages": [HumanMessage(content="What happened at the start?")],
            "session_id": "session-4",
            "user_id": "user-4",
            "media_id": "media-4",
            "project_id": None,
            "project_context": None,
        }
        config = RunnableConfig(configurable={"thread_id": "session-4"})

        with (
            patch("core.config.settings.mem0.enabled", True),
            patch(
                "services.mem0_memory_service.get_mem0_memory_service",
                AsyncMock(return_value=mock_mem0_service),
            ),
        ):
            memories = await _retrieve_external_memories(state, config)

        assert len(memories) == 1
        assert "[artifact:artifact-456]" in memories[0]

    @pytest.mark.asyncio
    async def test_rehydrate_artifact_context_for_detail_query(self):
        mock_artifact_service = AsyncMock()
        mock_artifact_service.get_artifact = AsyncMock(
            return_value={
                "id": "artifact-789",
                "tool_name": "search_video",
                "payload": {
                    "results": [{"timestamp": 5.2, "content": "Opening with city panorama"}]
                },
            }
        )

        state = {
            "messages": [
                HumanMessage(content="Give exact details with timestamp for the opening scene")
            ],
            "artifact_refs": [
                {
                    "artifact_id": "artifact-789",
                    "tool_call_id": "tc-7",
                    "tool_name": "search_video",
                    "summary": "search_video: returned 1 results",
                }
            ],
        }
        config = RunnableConfig(configurable={"thread_id": "session-7"})

        with patch(
            "services.tool_artifact_service.get_tool_artifact_service",
            AsyncMock(return_value=mock_artifact_service),
        ):
            snippets = await _rehydrate_artifact_context(state, config)

        assert len(snippets) == 1
        assert "artifact-789" in snippets[0]
        assert "Opening with city panorama" in snippets[0]
        mock_artifact_service.get_artifact.assert_awaited_once_with("artifact-789")

    @pytest.mark.asyncio
    async def test_rehydrate_artifact_context_skips_non_detail_query(self):
        mock_artifact_service = AsyncMock()
        mock_artifact_service.get_artifact = AsyncMock(return_value=None)

        state = {
            "messages": [HumanMessage(content="Thanks, continue")],
            "artifact_refs": [
                {
                    "artifact_id": "artifact-999",
                    "tool_call_id": "tc-9",
                    "tool_name": "search_video",
                    "summary": "search_video: returned 1 results",
                }
            ],
        }
        config = RunnableConfig(configurable={"thread_id": "session-9"})

        with patch(
            "services.tool_artifact_service.get_tool_artifact_service",
            AsyncMock(return_value=mock_artifact_service),
        ):
            snippets = await _rehydrate_artifact_context(state, config)

        assert snippets == []
        mock_artifact_service.get_artifact.assert_not_called()

    @pytest.mark.asyncio
    async def test_retrieve_hybrid_memory_context_reranks_and_prioritizes_artifacts(self):
        Metrics.reset()
        mock_mem0_service = AsyncMock()
        mock_mem0_service.search_memories = AsyncMock(
            return_value=[
                {
                    "memory": "Opening city panorama appears around 00:05",
                    "score": 0.91,
                    "metadata": {"artifact_id": "artifact-ext"},
                },
                {
                    "memory": "Unrelated note about credits",
                    "score": 0.95,
                    "metadata": {"artifact_id": "artifact-noise"},
                },
            ]
        )

        state = {
            "messages": [
                HumanMessage(content="Give exact timestamp and evidence for opening panorama")
            ],
            "memory_context": [
                "search_video: returned 2 results [artifact:artifact-local]",
                "summarize_video: broad overview",
            ],
            "artifact_refs": [
                {
                    "artifact_id": "artifact-local",
                    "tool_call_id": "tc-local",
                    "tool_name": "search_video",
                    "summary": "opening city panorama appears at timestamp 00:05",
                },
                {
                    "artifact_id": "artifact-other",
                    "tool_call_id": "tc-other",
                    "tool_name": "search_video",
                    "summary": "closing credits at end",
                },
            ],
            "session_id": "session-h1",
            "user_id": "user-h1",
            "media_id": "media-h1",
            "project_id": None,
            "project_context": None,
        }
        config = RunnableConfig(configurable={"thread_id": "session-h1"})

        with (
            patch("core.config.settings.mem0.enabled", True),
            patch(
                "services.mem0_memory_service.get_mem0_memory_service",
                AsyncMock(return_value=mock_mem0_service),
            ),
        ):
            snippets, artifact_ids = await _retrieve_hybrid_memory_context(state, config)

        assert snippets
        assert any("opening city panorama" in snippet.lower() for snippet in snippets)
        assert artifact_ids
        assert "artifact-local" in artifact_ids or "artifact-ext" in artifact_ids

        all_metrics = Metrics.get_all()
        duration_keys = [
            key
            for key in all_metrics["histograms"]
            if key.startswith(Metrics.MEMORY_RETRIEVAL_DURATION) and "source=hybrid" in key
        ]
        snippet_keys = [
            key
            for key in all_metrics["histograms"]
            if key.startswith(Metrics.MEMORY_SNIPPETS_INJECTED) and "source=hybrid" in key
        ]
        assert duration_keys
        assert snippet_keys

    @pytest.mark.asyncio
    async def test_rehydrate_artifact_context_uses_prioritized_ids(self):
        Metrics.reset()
        mock_artifact_service = AsyncMock()
        mock_artifact_service.get_artifact = AsyncMock(
            return_value={
                "id": "artifact-b",
                "tool_name": "search_video",
                "payload": {"results": [{"timestamp": 9.0, "content": "prioritized evidence"}]},
            }
        )

        state = {
            "messages": [HumanMessage(content="Need exact evidence now")],
            "artifact_refs": [
                {
                    "artifact_id": "artifact-a",
                    "tool_call_id": "tc-a",
                    "tool_name": "search_video",
                    "summary": "first summary",
                },
                {
                    "artifact_id": "artifact-b",
                    "tool_call_id": "tc-b",
                    "tool_name": "search_video",
                    "summary": "second summary",
                },
            ],
        }
        config = RunnableConfig(configurable={"thread_id": "session-prio"})

        with patch(
            "services.tool_artifact_service.get_tool_artifact_service",
            AsyncMock(return_value=mock_artifact_service),
        ):
            snippets = await _rehydrate_artifact_context(
                state,
                config,
                prioritized_artifact_ids=["artifact-b"],
            )

        assert len(snippets) == 1
        assert "artifact-b" in snippets[0]
        mock_artifact_service.get_artifact.assert_awaited_once_with("artifact-b")

        all_metrics = Metrics.get_all()
        attempt_keys = [
            key
            for key in all_metrics["counters"]
            if key.startswith(Metrics.ARTIFACT_REHYDRATION_ATTEMPTS) and "source=artifact" in key
        ]
        success_keys = [
            key
            for key in all_metrics["counters"]
            if key.startswith(Metrics.ARTIFACT_REHYDRATION_SUCCESSES) and "source=artifact" in key
        ]
        assert attempt_keys
        assert success_keys
