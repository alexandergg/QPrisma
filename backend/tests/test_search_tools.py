"""
Tests for agent/tools/search_tools.py
======================================

Tests for the 4 search tools: search_video, find_entity, get_transcript, describe_scene.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.graph_models import GraphSearchResponse, GraphSearchResult, NodeType


def _make_search_response(results=None, total=0):
    """Helper to build a GraphSearchResponse with sensible defaults."""
    return GraphSearchResponse(
        query="test",
        total_results=total or len(results or []),
        results=results or [],
        search_time_ms=5.0,
        vector_search_time_ms=3.0,
        graph_expansion_time_ms=1.0,
    )


def _make_result(node_type, content, score=0.85):
    return GraphSearchResult(
        node_id="n-1",
        node_type=node_type,
        vector_score=score,
        combined_score=score,
        content=content,
    )


# ---------------------------------------------------------------------------
# search_video
# ---------------------------------------------------------------------------


class TestSearchVideo:
    """Tests for search_video tool."""

    @pytest.mark.asyncio
    async def test_no_media_id_returns_error(self):
        from agent.tools.search_tools import search_video

        result = await search_video.ainvoke({"query": "hello", "media_id": None})
        assert result["error"]["type"] == "no_context"

    @pytest.mark.asyncio
    async def test_success_visual(self):
        from agent.tools.search_tools import search_video

        mock_service = MagicMock()
        mock_service.hybrid_search = AsyncMock(
            return_value=_make_search_response(
                results=[
                    _make_result(
                        NodeType.FRAME,
                        {"description": "A person walking", "timestamp": 15.0},
                    ),
                ],
                total=1,
            )
        )

        with patch(
            "services.graph_search_service.get_graph_search_service",
            return_value=mock_service,
        ):
            result = await search_video.ainvoke({"query": "person walking", "media_id": "vid-1"})

        assert result["query"] == "person walking"
        assert len(result["results"]) == 1
        assert result["results"][0]["type"] == "visual"
        assert result["_meta"]["result_count"] == 1

    @pytest.mark.asyncio
    async def test_time_range_filter(self):
        from agent.tools.search_tools import search_video

        mock_service = MagicMock()
        mock_service.hybrid_search = AsyncMock(
            return_value=_make_search_response(
                results=[
                    _make_result(NodeType.FRAME, {"description": "early", "timestamp": 5.0}),
                    _make_result(NodeType.FRAME, {"description": "late", "timestamp": 100.0}),
                ],
                total=2,
            )
        )

        with patch(
            "services.graph_search_service.get_graph_search_service",
            return_value=mock_service,
        ):
            result = await search_video.ainvoke(
                {
                    "query": "test",
                    "media_id": "vid-1",
                    "time_range_start": 50.0,
                    "time_range_end": 150.0,
                }
            )

        # Only the "late" result (ts=100) passes the time filter
        assert len(result["results"]) == 1
        assert result["results"][0]["content"] == "late"

    @pytest.mark.asyncio
    async def test_audio_content_type(self):
        from agent.tools.search_tools import search_video

        mock_service = MagicMock()
        mock_service.hybrid_search = AsyncMock(
            return_value=_make_search_response(
                results=[
                    _make_result(
                        NodeType.AUDIO_SEGMENT,
                        {"text": "talking about AI", "timestamp": 20.0},
                    ),
                ],
            )
        )

        with patch(
            "services.graph_search_service.get_graph_search_service",
            return_value=mock_service,
        ):
            result = await search_video.ainvoke(
                {"query": "AI", "media_id": "vid-1", "content_type": "audio"}
            )

        assert result["results"][0]["type"] == "audio"

    @pytest.mark.asyncio
    async def test_exception_returns_query_error(self):
        from agent.tools.search_tools import search_video

        with patch(
            "services.graph_search_service.get_graph_search_service",
            side_effect=RuntimeError("boom"),
        ):
            result = await search_video.ainvoke({"query": "q", "media_id": "vid-1"})

        assert result["error"]["type"] == "query_error"

    @pytest.mark.asyncio
    async def test_target_video_id_overrides(self):
        from agent.tools.search_tools import search_video

        mock_service = MagicMock()
        mock_service.hybrid_search = AsyncMock(return_value=_make_search_response())

        with patch(
            "services.graph_search_service.get_graph_search_service",
            return_value=mock_service,
        ):
            await search_video.ainvoke(
                {"query": "q", "media_id": "vid-1", "target_video_id": "vid-2"}
            )

        call_kwargs = mock_service.hybrid_search.call_args[1]
        assert call_kwargs["video_id"] == "vid-2"


# ---------------------------------------------------------------------------
# find_entity
# ---------------------------------------------------------------------------


class TestFindEntity:
    """Tests for find_entity tool."""

    @pytest.mark.asyncio
    async def test_no_media_id_returns_error(self):
        from agent.tools.search_tools import find_entity

        result = await find_entity.ainvoke({"entity_name": "John", "media_id": None})
        assert result["error"]["type"] == "no_context"

    @pytest.mark.asyncio
    async def test_success(self):
        from agent.tools.search_tools import find_entity

        mock_service = MagicMock()
        mock_service.hybrid_search = AsyncMock(
            return_value=_make_search_response(
                results=[
                    _make_result(
                        NodeType.ENTITY,
                        {"name": "John", "type": "person", "timestamp": 10.0},
                    ),
                ],
            )
        )

        with patch(
            "services.graph_search_service.get_graph_search_service",
            return_value=mock_service,
        ):
            result = await find_entity.ainvoke({"entity_name": "John", "media_id": "vid-1"})

        assert result["entity"] == "John"
        assert len(result["occurrences"]) >= 1
        assert result["_meta"]["result_count"] >= 1


# ---------------------------------------------------------------------------
# get_transcript
# ---------------------------------------------------------------------------


class TestGetTranscript:
    """Tests for get_transcript tool."""

    @pytest.mark.asyncio
    async def test_no_media_id_returns_error(self):
        from agent.tools.search_tools import get_transcript

        result = await get_transcript.ainvoke({"media_id": None})
        assert result["error"]["type"] == "no_context"

    @pytest.mark.asyncio
    async def test_no_transcript(self):
        from agent.tools.search_tools import get_transcript

        mock_kg = MagicMock()
        mock_kg.get_transcript_segments.return_value = []

        with patch(
            "services.knowledge_graph.get_knowledge_graph_service",
            return_value=mock_kg,
        ):
            result = await get_transcript.ainvoke({"media_id": "vid-1"})

        assert result["transcript"] == ""
        assert "No transcript" in result["message"]

    @pytest.mark.asyncio
    async def test_full_transcript(self):
        from agent.tools.search_tools import get_transcript

        mock_kg = MagicMock()
        mock_kg.get_transcript_segments.return_value = [
            {"timestamp": 5.0, "text": "Hello world", "speaker": "Alice"},
            {"timestamp": 10.0, "text": "How are you", "speaker": "Bob"},
        ]

        with patch(
            "services.knowledge_graph.get_knowledge_graph_service",
            return_value=mock_kg,
        ):
            result = await get_transcript.ainvoke({"media_id": "vid-1"})

        assert result["segments_count"] == 2
        assert "Alice" in result["speakers"]
        assert "Bob" in result["speakers"]
        assert result["has_speaker_ids"] is True
        assert "Hello world" in result["transcript"]

    @pytest.mark.asyncio
    async def test_time_range_transcript(self):
        from agent.tools.search_tools import get_transcript

        mock_kg = MagicMock()
        mock_kg.get_transcript_segments.return_value = [
            {"timestamp": 30.0, "text": "Specific part"},
        ]

        with patch(
            "services.knowledge_graph.get_knowledge_graph_service",
            return_value=mock_kg,
        ):
            result = await get_transcript.ainvoke(
                {"media_id": "vid-1", "start_time": 25.0, "end_time": 35.0}
            )

        assert result["start_time"] == 25.0
        assert result["end_time"] == 35.0
        assert result["segments_count"] == 1


# ---------------------------------------------------------------------------
# describe_scene
# ---------------------------------------------------------------------------


class TestDescribeScene:
    """Tests for describe_scene tool."""

    @pytest.mark.asyncio
    async def test_no_media_id_returns_error(self):
        from agent.tools.search_tools import describe_scene

        result = await describe_scene.ainvoke({"timestamp": 10.0, "media_id": None})
        assert result["error"]["type"] == "no_context"

    @pytest.mark.asyncio
    async def test_no_frame_found(self):
        from agent.tools.search_tools import describe_scene

        mock_kg = MagicMock()
        mock_kg.get_nearest_frame.return_value = None

        with patch(
            "services.knowledge_graph.get_knowledge_graph_service",
            return_value=mock_kg,
        ):
            result = await describe_scene.ainvoke({"timestamp": 50.0, "media_id": "vid-1"})

        assert "No frame data" in result["description"]
        assert result["_meta"]["is_complete"] is False

    @pytest.mark.asyncio
    async def test_success_exact_timestamp(self):
        from agent.tools.search_tools import describe_scene

        mock_kg = MagicMock()
        mock_kg.get_nearest_frame.return_value = {
            "timestamp": 50.0,
            "description": "A dog playing in the park",
        }

        with patch(
            "services.knowledge_graph.get_knowledge_graph_service",
            return_value=mock_kg,
        ):
            result = await describe_scene.ainvoke({"timestamp": 50.0, "media_id": "vid-1"})

        assert result["description"] == "A dog playing in the park"
        assert "requested_timestamp" not in result  # no gap
        assert "_meta" in result

    @pytest.mark.asyncio
    async def test_gap_reported_when_frame_far(self):
        from agent.tools.search_tools import describe_scene

        mock_kg = MagicMock()
        mock_kg.get_nearest_frame.return_value = {
            "timestamp": 55.0,
            "description": "Nearby frame",
        }

        with patch(
            "services.knowledge_graph.get_knowledge_graph_service",
            return_value=mock_kg,
        ):
            result = await describe_scene.ainvoke({"timestamp": 50.0, "media_id": "vid-1"})

        assert result["timestamp"] == 55.0
        assert result["requested_timestamp"] == 50.0
        assert result["gap_seconds"] == 5.0
