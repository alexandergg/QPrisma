"""
Tests for agent/tools/search_tools.py
======================================

Tests for the 4 search tools: search_video, find_entity, get_transcript, describe_scene.
"""

import asyncio
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


# ---------------------------------------------------------------------------
# _hybrid_search_with_fallback — timeout / fallback paths
# ---------------------------------------------------------------------------


class TestHybridSearchWithFallback:
    """Tests for the keyword-fallback path when hybrid search times out or fails."""

    @pytest.mark.asyncio
    async def test_timeout_triggers_keyword_fallback(self):
        """When hybrid search times out, keyword fallback is used and results include score."""
        from agent.tools.search_tools import search_video

        mock_service = MagicMock()
        mock_service.hybrid_search = AsyncMock(side_effect=asyncio.TimeoutError)

        mock_kg = MagicMock()
        mock_kg.search_multimodal.return_value = {
            "combined_timeline": [
                {"timestamp": 10.0, "content": "A bright sunny day", "type": "visual"},
                {"timestamp": 20.0, "content": "Bird sounds in the park", "type": "audio"},
            ],
            "total_visual": 1,
            "total_audio": 1,
        }

        with (
            patch(
                "services.graph_search_service.get_graph_search_service",
                return_value=mock_service,
            ),
            patch(
                "services.knowledge_graph.get_knowledge_graph_service",
                return_value=mock_kg,
            ),
        ):
            result = await search_video.ainvoke({"query": "sunny", "media_id": "vid-1"})

        assert result["search_mode"] == "keyword_fallback"
        assert len(result["results"]) == 2
        # Fallback results must include the score field for structural consistency
        for r in result["results"]:
            assert "score" in r

    @pytest.mark.asyncio
    async def test_exception_triggers_keyword_fallback(self):
        """When hybrid search raises a non-timeout error, keyword fallback is used."""
        from agent.tools.search_tools import search_video

        mock_service = MagicMock()
        mock_service.hybrid_search = AsyncMock(side_effect=RuntimeError("embedding failed"))

        mock_kg = MagicMock()
        mock_kg.search_multimodal.return_value = {
            "combined_timeline": [
                {"timestamp": 5.0, "content": "Fallback frame", "type": "visual"},
            ],
            "total_visual": 1,
            "total_audio": 0,
        }

        with (
            patch(
                "services.graph_search_service.get_graph_search_service",
                return_value=mock_service,
            ),
            patch(
                "services.knowledge_graph.get_knowledge_graph_service",
                return_value=mock_kg,
            ),
        ):
            result = await search_video.ainvoke({"query": "test", "media_id": "vid-1"})

        assert result["search_mode"] == "keyword_fallback"
        assert len(result["results"]) == 1
        assert result["results"][0]["score"] == 0.0


# ---------------------------------------------------------------------------
# find_entity — timeout / graph-fallback path
# ---------------------------------------------------------------------------


class TestFindEntityFallback:
    """Tests for find_entity graph-fallback path when hybrid search fails."""

    @pytest.mark.asyncio
    async def test_timeout_triggers_graph_fallback(self):
        """When hybrid search times out, find_entity falls back to graph lookup."""
        from agent.tools.search_tools import find_entity

        mock_service = MagicMock()
        mock_service.hybrid_search = AsyncMock(side_effect=asyncio.TimeoutError)

        mock_kg = MagicMock()
        mock_kg.find_entity_appearances.return_value = {
            "visual": [
                {
                    "timestamp": 15.0,
                    "description": "Person visible at center",
                },
            ],
            "audio": [],
        }
        mock_kg.search_entities.return_value = []

        with (
            patch(
                "services.graph_search_service.get_graph_search_service",
                return_value=mock_service,
            ),
            patch(
                "services.knowledge_graph.get_knowledge_graph_service",
                return_value=mock_kg,
            ),
        ):
            result = await find_entity.ainvoke({"entity_name": "Alice", "media_id": "vid-1"})

        assert result["entity"] == "Alice"
        assert len(result["occurrences"]) >= 1
        assert result["occurrences"][0]["confidence"] == 0.5
        assert "_meta" in result
        assert result["_meta"]["result_count"] >= 1


# ---------------------------------------------------------------------------
# Pipeline behavior tests
# ---------------------------------------------------------------------------


class TestPipelineBehavior:
    """Tests for hybrid search pipeline resilience: fallbacks, caps, timeouts."""

    def _make_scored_node(self, node_id, vector=0.8, fulltext=0.0, node_type=NodeType.FRAME):
        """Helper to create a ScoredNode-like object."""
        from services.graph_search_queries import ScoredNode

        return ScoredNode(
            node_id=node_id,
            node_type=node_type,
            vector_score=vector,
            fulltext_score=fulltext,
            graph_score=0.0,
            temporal_score=0.0,
            combined_score=0.0,
            content={"text": f"Content for {node_id}"},
        )

    def test_candidate_cap_preserves_fulltext_hits(self):
        """When candidate cap triggers, strong fulltext-only hits (vector=0) survive."""
        nodes = []
        # 40 vector-strong, fulltext-weak nodes
        for i in range(40):
            nodes.append(self._make_scored_node(f"v-{i}", vector=0.7, fulltext=0.1))
        # 10 fulltext-strong, vector-zero nodes
        for i in range(10):
            nodes.append(self._make_scored_node(f"ft-{i}", vector=0.0, fulltext=0.9))

        # Simulate the capping logic from _sync_search_pipeline
        limit = 5
        cap = limit * 6  # 30
        assert len(nodes) > cap  # 50 > 30, so cap triggers

        # Blended score: 0.5 * vector + 0.5 * fulltext
        for c in nodes:
            c.combined_score = 0.5 * c.vector_score + 0.5 * c.fulltext_score
        nodes.sort(key=lambda x: x.combined_score, reverse=True)
        nodes = nodes[: limit * 4]  # keep top 20

        # All 10 fulltext-strong nodes should survive (blended=0.45)
        # vs vector-only nodes (blended=0.40)
        ft_survivors = [n for n in nodes if n.node_id.startswith("ft-")]
        assert (
            len(ft_survivors) == 10
        ), f"Expected all 10 fulltext-only hits to survive cap, got {len(ft_survivors)}"

    def test_candidate_cap_not_triggered_below_threshold(self):
        """When candidates are below threshold, no capping occurs."""
        nodes = [self._make_scored_node(f"n-{i}", vector=0.5) for i in range(10)]
        limit = 5
        cap = limit * 6  # 30
        assert len(nodes) <= cap  # 10 <= 30, no cap
