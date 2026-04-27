"""
Tests for multi-video tool error handling.

Validates that enriched error responses include fallback_suggestion and
diagnostic fields so the agent can recover gracefully.
"""

from dataclasses import asdict
from unittest.mock import patch

import pytest
from agent.tools.multi_video_tools import (
    compare_videos,
    find_common_entities,
    get_library_overview,
    search_across_videos,
)

from services.cross_video_search_service import CompareVideosResult, CrossVideoSearchResult

# ── search_across_videos ────────────────────────────────────────────────


class TestSearchAcrossVideosErrors:
    @pytest.mark.asyncio
    async def test_passes_user_id_to_service(self):
        with patch(
            "services.cross_video_search_service.get_cross_video_search_service"
        ) as mock_factory:
            mock_factory.return_value.search_across_videos.return_value = CrossVideoSearchResult(
                query="test",
                videos_searched=1,
                scoped_to_selection=False,
                results_by_video=[{"video_id": "v1", "video_title": "Video 1", "matches": []}],
                total_matches=0,
            )

            result = await search_across_videos.ainvoke(
                {
                    "query": "test",
                    "limit_per_video": 3,
                    "max_videos": 5,
                    "user_id": "u1",
                    "media_ids": None,
                }
            )

        mock_factory.return_value.search_across_videos.assert_called_once_with(
            "test",
            limit_per_video=3,
            max_videos=5,
            media_ids=None,
            user_id="u1",
        )
        base_expected = asdict(mock_factory.return_value.search_across_videos.return_value)
        for key in base_expected:
            assert result[key] == base_expected[key]
        assert "_meta" in result

    @pytest.mark.asyncio
    async def test_error_includes_fallback_suggestion(self):
        with patch(
            "services.cross_video_search_service.get_cross_video_search_service",
            side_effect=RuntimeError("neo4j down"),
        ):
            result = await search_across_videos.ainvoke(
                {
                    "query": "test",
                    "limit_per_video": 3,
                    "max_videos": 5,
                    "user_id": "u1",
                    "media_ids": ["v1"],
                }
            )

        assert "error" in result
        assert "Cross-video search failed" in result["error"]["message"]
        assert "search_video" in result["error"]["recovery"]


# ── compare_videos ──────────────────────────────────────────────────────


class TestCompareVideosErrors:
    @pytest.mark.asyncio
    async def test_passes_user_id_to_service(self):
        with patch(
            "services.cross_video_search_service.get_cross_video_search_service"
        ) as mock_factory:
            mock_factory.return_value.compare_videos.return_value = CompareVideosResult(
                query="topics",
                videos_compared=2,
                comparison=[],
                error=None,
            )

            result = await compare_videos.ainvoke(
                {
                    "query": "topics",
                    "user_id": "u1",
                    "media_ids": ["v1", "v2"],
                    "media_id": None,
                }
            )

        mock_factory.return_value.compare_videos.assert_called_once_with(
            "topics",
            ["v1", "v2"],
            user_id="u1",
        )
        assert result["videos_compared"] == 2

    @pytest.mark.asyncio
    async def test_not_enough_videos_includes_fallback(self):
        result = await compare_videos.ainvoke(
            {
                "query": "topics",
                "user_id": "u1",
                "media_ids": None,
                "media_id": "only-one",
            }
        )

        assert "error" in result
        assert "at least 2 videos" in result["error"]["message"]
        assert "1 video(s)" in result["error"]["message"]
        assert "library mode" in result["error"]["recovery"]

    @pytest.mark.asyncio
    async def test_no_videos_includes_fallback(self):
        result = await compare_videos.ainvoke(
            {
                "query": "topics",
                "user_id": "u1",
                "media_ids": None,
                "media_id": None,
            }
        )

        assert "0 video(s)" in result["error"]["message"]
        assert "recovery" in result["error"]

    @pytest.mark.asyncio
    async def test_service_exception_includes_fallback_and_count(self):
        with patch(
            "services.cross_video_search_service.get_cross_video_search_service",
            side_effect=RuntimeError("comparison engine failed"),
        ):
            result = await compare_videos.ainvoke(
                {
                    "query": "revenue",
                    "user_id": "u1",
                    "media_ids": ["v1", "v2", "v3"],
                    "media_id": None,
                }
            )

        assert "Video comparison failed" in result["error"]["message"]
        assert "get_summary" in result["error"]["recovery"]


# ── find_common_entities ────────────────────────────────────────────────


class TestFindCommonEntitiesErrors:
    @pytest.mark.asyncio
    async def test_passes_user_id_to_knowledge_graph(self):
        with patch("services.knowledge_graph.get_knowledge_graph_service") as mock_factory:
            mock_factory.return_value.find_common_entities.return_value = [
                {
                    "name": "Alice",
                    "evidence": [
                        {
                            "video_id": "v1",
                            "video_title": "Video 1",
                            "timestamp": 12.0,
                            "timestamp_formatted": "0:12",
                            "description": "Alice is visible.",
                        }
                    ],
                }
            ]

            result = await find_common_entities.ainvoke(
                {
                    "entity_type": "person",
                    "limit": 10,
                    "user_id": "u1",
                    "media_ids": ["v1", "v2"],
                    "media_id": None,
                }
            )

        mock_factory.return_value.find_common_entities.assert_called_once_with(
            video_ids=["v1", "v2"],
            entity_type="person",
            limit=10,
            user_id="u1",
        )
        assert result["total_found"] == 1
        assert result["entities"][0]["evidence"][0]["video_title"] == "Video 1"
        assert "evidence timestamps" in result["_meta"]["detail_hint"]

    @pytest.mark.asyncio
    async def test_empty_result_has_no_hallucination_guidance(self):
        with patch("services.knowledge_graph.get_knowledge_graph_service") as mock_factory:
            mock_factory.return_value.find_common_entities.return_value = []

            result = await find_common_entities.ainvoke(
                {
                    "entity_type": "person",
                    "limit": 10,
                    "user_id": "u1",
                    "media_ids": ["v1", "v2"],
                    "media_id": None,
                }
            )

        assert result["total_found"] == 0
        assert "No common entities found" in result["message"]
        assert "do not infer common people" in result["_meta"]["detail_hint"]

    @pytest.mark.asyncio
    async def test_service_exception_includes_fallback_and_count(self):
        with patch(
            "services.knowledge_graph.get_knowledge_graph_service",
            side_effect=RuntimeError("kg unavailable"),
        ):
            result = await find_common_entities.ainvoke(
                {
                    "entity_type": "person",
                    "limit": 10,
                    "user_id": "u1",
                    "media_ids": ["v1", "v2"],
                    "media_id": None,
                }
            )

        assert "Finding common entities failed" in result["error"]["message"]
        assert "search_across_videos" in result["error"]["recovery"]


class TestGetLibraryOverview:
    @pytest.mark.asyncio
    async def test_passes_user_id_to_knowledge_graph(self):
        with patch("services.knowledge_graph.get_knowledge_graph_service") as mock_factory:
            mock_factory.return_value.get_video_topics.return_value = [
                {
                    "video_id": "v1",
                    "title": "Video 1",
                    "summary": "Summary",
                    "topics": ["topic"],
                    "duration": 60,
                }
            ]

            result = await get_library_overview.ainvoke(
                {
                    "user_id": "u1",
                    "media_ids": ["v1"],
                    "media_id": None,
                }
            )

        mock_factory.return_value.get_video_topics.assert_called_once_with(
            video_ids=["v1"],
            user_id="u1",
        )
        assert result["total_videos"] == 1
