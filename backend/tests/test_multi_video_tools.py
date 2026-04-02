"""
Tests for multi-video tool error handling.

Validates that enriched error responses include fallback_suggestion and
diagnostic fields so the agent can recover gracefully.
"""

from unittest.mock import patch

import pytest

from agent.tools.multi_video_tools import (
    compare_videos,
    find_common_entities,
    search_across_videos,
)

# ── search_across_videos ────────────────────────────────────────────────


class TestSearchAcrossVideosErrors:
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
        assert "Cross-video search failed" in result["error"]
        assert result["results"] == []
        assert "fallback_suggestion" in result
        assert "search_video" in result["fallback_suggestion"]


# ── compare_videos ──────────────────────────────────────────────────────


class TestCompareVideosErrors:
    @pytest.mark.asyncio
    async def test_not_enough_videos_includes_fallback(self):
        result = await compare_videos.ainvoke(
            {
                "query": "topics",
                "media_ids": None,
                "media_id": "only-one",
            }
        )

        assert "error" in result
        assert "at least 2 videos" in result["error"]
        assert "1 video(s)" in result["error"]
        assert result["comparison"] == []
        assert "fallback_suggestion" in result
        assert "library mode" in result["fallback_suggestion"]

    @pytest.mark.asyncio
    async def test_no_videos_includes_fallback(self):
        result = await compare_videos.ainvoke(
            {
                "query": "topics",
                "media_ids": None,
                "media_id": None,
            }
        )

        assert "0 video(s)" in result["error"]
        assert "fallback_suggestion" in result

    @pytest.mark.asyncio
    async def test_service_exception_includes_fallback_and_count(self):
        with patch(
            "services.cross_video_search_service.get_cross_video_search_service",
            side_effect=RuntimeError("comparison engine failed"),
        ):
            result = await compare_videos.ainvoke(
                {
                    "query": "revenue",
                    "media_ids": ["v1", "v2", "v3"],
                    "media_id": None,
                }
            )

        assert "Video comparison failed" in result["error"]
        assert result["comparison"] == []
        assert result["videos_attempted"] == 3
        assert "fallback_suggestion" in result
        assert "get_summary" in result["fallback_suggestion"]


# ── find_common_entities ────────────────────────────────────────────────


class TestFindCommonEntitiesErrors:
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
                    "media_ids": ["v1", "v2"],
                    "media_id": None,
                }
            )

        assert "Finding common entities failed" in result["error"]
        assert result["entities"] == []
        assert result["videos_attempted"] == 2
        assert "fallback_suggestion" in result
        assert "search_across_videos" in result["fallback_suggestion"]
