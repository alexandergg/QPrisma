"""
Tests for agent/tools/analysis_tools.py
========================================

Tests for the 3 analysis tools: get_related_content, get_entity_timeline, compare_moments.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.graph_models import GraphSearchResponse, GraphSearchResult, NodeType


def _make_search_response(results=None, total=0):
    """Helper to build a GraphSearchResponse."""
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
# get_related_content
# ---------------------------------------------------------------------------


class TestGetRelatedContent:
    """Tests for get_related_content tool."""

    @pytest.mark.asyncio
    async def test_no_media_id_returns_error(self):
        from agent.tools.analysis_tools import get_related_content

        result = await get_related_content.ainvoke({"topic": "AI", "media_id": None})
        assert result["error"]["type"] == "no_context"

    @pytest.mark.asyncio
    async def test_success_entities_and_topics(self):
        from agent.tools.analysis_tools import get_related_content

        mock_service = MagicMock()
        mock_service.hybrid_search = AsyncMock(
            return_value=_make_search_response(
                results=[
                    _make_result(
                        NodeType.ENTITY,
                        {"name": "GPT-4", "type": "model", "description": "LLM"},
                    ),
                    _make_result(
                        NodeType.TOPIC,
                        {"name": "Deep Learning", "description": "Neural nets"},
                    ),
                    _make_result(
                        NodeType.FRAME,
                        {"description": "Slide about AI", "timestamp": 30.0},
                    ),
                ],
            )
        )

        with patch(
            "services.graph_search_service.get_graph_search_service",
            return_value=mock_service,
        ):
            result = await get_related_content.ainvoke({"topic": "AI", "media_id": "vid-1"})

        assert result["topic"] == "AI"
        assert len(result["related_entities"]) >= 1
        assert len(result["related_topics"]) >= 1
        assert len(result["related_moments"]) >= 1
        assert "_meta" in result

    @pytest.mark.asyncio
    async def test_depth_clamped_to_3(self):
        from agent.tools.analysis_tools import get_related_content

        mock_service = MagicMock()
        mock_service.hybrid_search = AsyncMock(return_value=_make_search_response())

        with patch(
            "services.graph_search_service.get_graph_search_service",
            return_value=mock_service,
        ):
            await get_related_content.ainvoke({"topic": "test", "depth": 10, "media_id": "vid-1"})

        call_kwargs = mock_service.hybrid_search.call_args[1]
        assert call_kwargs["expansion_hops"] == 3

    @pytest.mark.asyncio
    async def test_target_video_id_overrides_injected_media_id(self):
        from agent.tools.analysis_tools import get_related_content

        mock_service = MagicMock()
        mock_service.hybrid_search = AsyncMock(return_value=_make_search_response())

        with patch(
            "services.graph_search_service.get_graph_search_service",
            return_value=mock_service,
        ):
            await get_related_content.ainvoke(
                {
                    "topic": "AI",
                    "target_video_id": "vid-target",
                    "media_id": "vid-default",
                }
            )

        call_kwargs = mock_service.hybrid_search.call_args[1]
        assert call_kwargs["video_id"] == "vid-target"

    @pytest.mark.asyncio
    async def test_exception_returns_query_error(self):
        from agent.tools.analysis_tools import get_related_content

        with patch(
            "services.graph_search_service.get_graph_search_service",
            side_effect=RuntimeError("boom"),
        ):
            result = await get_related_content.ainvoke({"topic": "AI", "media_id": "vid-1"})

        assert result["error"]["type"] == "query_error"


# ---------------------------------------------------------------------------
# get_entity_timeline
# ---------------------------------------------------------------------------


class TestGetEntityTimeline:
    """Tests for get_entity_timeline tool."""

    @pytest.mark.asyncio
    async def test_no_media_id_returns_error(self):
        from agent.tools.analysis_tools import get_entity_timeline

        result = await get_entity_timeline.ainvoke({"entity_name": "Alice", "media_id": None})
        assert result["error"]["type"] == "no_context"

    @pytest.mark.asyncio
    async def test_success_with_appearances(self):
        from agent.tools.analysis_tools import get_entity_timeline

        mock_kg = MagicMock()
        mock_kg.find_entity_appearances.return_value = {
            "visual": [
                {
                    "name": "Alice",
                    "entity_type": "person",
                    "timestamp": 10.0,
                    "description": "Alice walks in",
                },
                {
                    "name": "Alice",
                    "entity_type": "person",
                    "timestamp": 30.0,
                    "description": "Alice speaks",
                },
            ],
            "audio": [
                {"timestamp": 20.0, "text": "Alice mentioned by name"},
            ],
        }

        with patch(
            "services.knowledge_graph.get_knowledge_graph_service",
            return_value=mock_kg,
        ):
            result = await get_entity_timeline.ainvoke(
                {"entity_name": "Alice", "media_id": "vid-1", "user_id": "u-1"}
            )

        assert result["entity"] == "Alice"
        assert result["total_appearances"] == 3
        assert result["visual_appearances"] == 2
        assert result["spoken_mentions"] == 1
        # Sorted by timestamp
        timestamps = [t["timestamp"] for t in result["timeline"]]
        assert timestamps == sorted(timestamps)

    @pytest.mark.asyncio
    async def test_entity_type_filter(self):
        from agent.tools.analysis_tools import get_entity_timeline

        mock_kg = MagicMock()
        mock_kg.find_entity_appearances.return_value = {
            "visual": [
                {"name": "NYC", "entity_type": "location", "timestamp": 10.0, "description": "NYC"},
                {"name": "Cat", "entity_type": "object", "timestamp": 20.0, "description": "Cat"},
            ],
            "audio": [],
        }

        with patch(
            "services.knowledge_graph.get_knowledge_graph_service",
            return_value=mock_kg,
        ):
            result = await get_entity_timeline.ainvoke(
                {"entity_name": "NYC", "entity_type": "location", "media_id": "vid-1"}
            )

        # Only "location" type should pass the filter
        assert result["total_appearances"] == 1
        assert result["timeline"][0]["entity_name"] == "NYC"

    @pytest.mark.asyncio
    async def test_empty_appearances(self):
        from agent.tools.analysis_tools import get_entity_timeline

        mock_kg = MagicMock()
        mock_kg.find_entity_appearances.return_value = {"visual": [], "audio": []}

        with patch(
            "services.knowledge_graph.get_knowledge_graph_service",
            return_value=mock_kg,
        ):
            result = await get_entity_timeline.ainvoke(
                {"entity_name": "Ghost", "media_id": "vid-1"}
            )

        assert result["total_appearances"] == 0
        assert result["first_appearance"] is None
        assert result["last_appearance"] is None

    @pytest.mark.asyncio
    async def test_passes_user_id(self):
        from agent.tools.analysis_tools import get_entity_timeline

        mock_kg = MagicMock()
        mock_kg.find_entity_appearances.return_value = {"visual": [], "audio": []}

        with patch(
            "services.knowledge_graph.get_knowledge_graph_service",
            return_value=mock_kg,
        ):
            await get_entity_timeline.ainvoke(
                {"entity_name": "X", "media_id": "vid-1", "user_id": "u-99"}
            )

        call_kwargs = mock_kg.find_entity_appearances.call_args
        assert call_kwargs[1].get("user_id") == "u-99"

    @pytest.mark.asyncio
    async def test_target_video_id_overrides_media_id(self):
        from agent.tools.analysis_tools import get_entity_timeline

        mock_kg = MagicMock()
        mock_kg.find_entity_appearances.return_value = {"visual": [], "audio": []}

        with patch(
            "services.knowledge_graph.get_knowledge_graph_service",
            return_value=mock_kg,
        ):
            await get_entity_timeline.ainvoke(
                {
                    "entity_name": "X",
                    "media_id": "vid-primary",
                    "target_video_id": "vid-target",
                }
            )

        assert mock_kg.find_entity_appearances.call_args[0][0] == "vid-target"


# ---------------------------------------------------------------------------
# compare_moments
# ---------------------------------------------------------------------------


class TestCompareMoments:
    """Tests for compare_moments tool."""

    @pytest.mark.asyncio
    async def test_no_media_id_returns_error(self):
        from agent.tools.analysis_tools import compare_moments

        result = await compare_moments.ainvoke({"timestamps": [10.0, 20.0], "media_id": None})
        assert result["error"]["type"] == "no_context"

    @pytest.mark.asyncio
    async def test_too_few_timestamps(self):
        from agent.tools.analysis_tools import compare_moments

        result = await compare_moments.ainvoke({"timestamps": [10.0], "media_id": "vid-1"})
        assert result["error"]["type"] == "invalid_input"

    @pytest.mark.asyncio
    async def test_too_many_timestamps(self):
        from agent.tools.analysis_tools import compare_moments

        result = await compare_moments.ainvoke(
            {"timestamps": [1, 2, 3, 4, 5, 6], "media_id": "vid-1"}
        )
        assert result["error"]["type"] == "invalid_input"

    @pytest.mark.asyncio
    async def test_success(self):
        from agent.tools.analysis_tools import compare_moments

        mock_kg = MagicMock()
        mock_kg.get_moments_context.return_value = [
            {
                "timestamp": 10.0,
                "visual": {"timestamp": 10.0, "description": "Opening"},
                "audio": [{"text": "Welcome", "speaker": "Host"}],
            },
            {
                "timestamp": 60.0,
                "visual": {"timestamp": 60.0, "description": "Closing"},
                "audio": [{"text": "Goodbye", "speaker": "Host"}],
            },
        ]

        with patch(
            "services.knowledge_graph.get_knowledge_graph_service",
            return_value=mock_kg,
        ):
            result = await compare_moments.ainvoke(
                {"timestamps": [10.0, 60.0], "media_id": "vid-1"}
            )

        assert result["timestamps_compared"] == 2
        assert len(result["moments"]) == 2
        assert result["moments"][0]["visual"]["description"] == "Opening"
        assert result["_meta"]["result_count"] == 2

    @pytest.mark.asyncio
    async def test_visual_only_aspect(self):
        from agent.tools.analysis_tools import compare_moments

        mock_kg = MagicMock()
        mock_kg.get_moments_context.return_value = [
            {
                "timestamp": 10.0,
                "visual": {"timestamp": 10.0, "description": "Frame A"},
                "audio": [{"text": "Speech", "speaker": "X"}],
            },
            {
                "timestamp": 20.0,
                "visual": {"timestamp": 20.0, "description": "Frame B"},
                "audio": [{"text": "More speech", "speaker": "Y"}],
            },
        ]

        with patch(
            "services.knowledge_graph.get_knowledge_graph_service",
            return_value=mock_kg,
        ):
            result = await compare_moments.ainvoke(
                {
                    "timestamps": [10.0, 20.0],
                    "media_id": "vid-1",
                    "comparison_aspect": "visual",
                }
            )

        assert result["comparison_aspect"] == "visual"
        # Only visual data should be included
        for m in result["moments"]:
            assert "visual" in m
            assert "audio" not in m

    @pytest.mark.asyncio
    async def test_target_video_id_overrides_media_id(self):
        from agent.tools.analysis_tools import compare_moments

        mock_kg = MagicMock()
        mock_kg.get_moments_context.return_value = []

        with patch(
            "services.knowledge_graph.get_knowledge_graph_service",
            return_value=mock_kg,
        ):
            await compare_moments.ainvoke(
                {
                    "timestamps": [10.0, 20.0],
                    "media_id": "vid-primary",
                    "target_video_id": "vid-target",
                }
            )

        assert mock_kg.get_moments_context.call_args[0][0] == "vid-target"
