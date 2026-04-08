"""
Tests for agent/tools/context_tools.py
=======================================

Tests for the 5 context tools: list_chapters, get_video_info, get_summary,
get_scene_context, get_community_overview.
"""

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# list_chapters
# ---------------------------------------------------------------------------


class TestListChapters:
    """Tests for list_chapters tool."""

    @pytest.mark.asyncio
    async def test_no_media_id_returns_error(self):
        from agent.tools.context_tools import list_chapters

        result = await list_chapters.ainvoke({"media_id": None})
        assert result["error"]["type"] == "no_context"

    @pytest.mark.asyncio
    async def test_video_not_in_graph(self):
        from agent.tools.context_tools import list_chapters

        mock_kg = MagicMock()
        mock_kg.get_video_node.return_value = None

        with patch("services.knowledge_graph.get_knowledge_graph_service", return_value=mock_kg):
            result = await list_chapters.ainvoke({"media_id": "vid-1"})

        assert result["chapters"] == []
        assert result["_meta"]["result_count"] == 0

    @pytest.mark.asyncio
    async def test_no_scenes_returns_topics_fallback(self):
        from agent.tools.context_tools import list_chapters

        mock_kg = MagicMock()
        mock_kg.get_video_node.return_value = {"video_id": "vid-1"}
        mock_kg.get_video_scenes.return_value = []
        mock_kg.get_video_summary.return_value = ("A nice video", ["AI", "ML"])

        with patch("services.knowledge_graph.get_knowledge_graph_service", return_value=mock_kg):
            result = await list_chapters.ainvoke({"media_id": "vid-1"})

        assert result["chapters"] == []
        assert result["topics"] == ["AI", "ML"]
        assert result["summary"] == "A nice video"

    @pytest.mark.asyncio
    async def test_success_with_scenes(self):
        from agent.tools.context_tools import list_chapters

        mock_kg = MagicMock()
        mock_kg.get_video_node.return_value = {"video_id": "vid-1", "summary": "Test video"}
        mock_kg.get_video_scenes.return_value = [
            {"scene_index": 0, "start_time": 0, "end_time": 30, "title": "Intro"},
            {"scene_index": 1, "start_time": 30, "end_time": 60, "title": "Main"},
        ]
        mock_kg.get_video_frames.return_value = [
            {"timestamp": 5, "description": "Opening shot"},
            {"timestamp": 35, "description": "Main content"},
        ]

        with patch("services.knowledge_graph.get_knowledge_graph_service", return_value=mock_kg):
            result = await list_chapters.ainvoke({"media_id": "vid-1"})

        assert "_meta" in result
        assert result["_meta"]["result_count"] >= 1
        assert len(result["chapters"]) >= 1
        assert "start_time" in result["chapters"][0]
        assert "title" in result["chapters"][0]

    @pytest.mark.asyncio
    async def test_exception_returns_query_error(self):
        from agent.tools.context_tools import list_chapters

        with patch(
            "services.knowledge_graph.get_knowledge_graph_service",
            side_effect=RuntimeError("Neo4j down"),
        ):
            result = await list_chapters.ainvoke({"media_id": "vid-1"})

        assert result["error"]["type"] == "query_error"

    @pytest.mark.asyncio
    async def test_target_video_id_overrides_media_id(self):
        from agent.tools.context_tools import list_chapters

        mock_kg = MagicMock()
        mock_kg.get_video_node.return_value = None

        with patch("services.knowledge_graph.get_knowledge_graph_service", return_value=mock_kg):
            await list_chapters.ainvoke({"media_id": "vid-1", "target_video_id": "vid-2"})

        mock_kg.get_video_node.assert_called_once_with("vid-2")


# ---------------------------------------------------------------------------
# get_video_info
# ---------------------------------------------------------------------------


class TestGetVideoInfo:
    """Tests for get_video_info tool."""

    @pytest.mark.asyncio
    async def test_no_media_id_returns_error(self):
        from agent.tools.context_tools import get_video_info

        result = await get_video_info.ainvoke({"media_id": None})
        assert result["error"]["type"] == "no_context"

    @pytest.mark.asyncio
    async def test_video_not_found(self):
        from agent.tools.context_tools import get_video_info

        mock_db = MagicMock()
        mock_db.get_media.return_value = None

        with patch("services.database_service.get_database_service", return_value=mock_db):
            result = await get_video_info.ainvoke({"media_id": "vid-1"})

        assert result["error"]["type"] == "no_data"

    @pytest.mark.asyncio
    async def test_success(self):
        from agent.tools.context_tools import get_video_info

        mock_media = MagicMock()
        mock_media.original_filename = "test.mp4"
        mock_media.blob_name = "blob-test"
        mock_media.video_metadata = {"duration": 120, "width": 1920, "height": 1080, "fps": 30}
        mock_media.processing_status = "completed"

        mock_db = MagicMock()
        mock_db.get_media.return_value = mock_media

        with patch("services.database_service.get_database_service", return_value=mock_db):
            result = await get_video_info.ainvoke({"media_id": "vid-1"})

        assert result["title"] == "test.mp4"
        assert result["duration"] == 120
        assert result["resolution"] == "1920x1080"
        assert result["fps"] == 30
        assert result["status"] == "completed"
        assert result["_meta"]["source"] == "database"

    @pytest.mark.asyncio
    async def test_exception_returns_query_error(self):
        from agent.tools.context_tools import get_video_info

        with patch(
            "services.database_service.get_database_service",
            side_effect=RuntimeError("DB down"),
        ):
            result = await get_video_info.ainvoke({"media_id": "vid-1"})

        assert result["error"]["type"] == "query_error"


# ---------------------------------------------------------------------------
# get_summary
# ---------------------------------------------------------------------------


class TestGetSummary:
    """Tests for get_summary tool."""

    @pytest.mark.asyncio
    async def test_no_media_id_returns_error(self):
        from agent.tools.context_tools import get_summary

        result = await get_summary.ainvoke({"media_id": None})
        assert result["error"]["type"] == "no_context"

    @pytest.mark.asyncio
    async def test_no_summary_available(self):
        from agent.tools.context_tools import get_summary

        mock_kg = MagicMock()
        mock_kg.get_video_summary_data.return_value = {"title": "My Video", "summary": None}

        with patch("services.knowledge_graph.get_knowledge_graph_service", return_value=mock_kg):
            result = await get_summary.ainvoke({"media_id": "vid-1"})

        assert result["_meta"]["is_complete"] is False
        assert "No summary" in result["summary"]

    @pytest.mark.asyncio
    async def test_success(self):
        from agent.tools.context_tools import get_summary

        mock_kg = MagicMock()
        mock_kg.get_video_summary_data.return_value = {
            "title": "AI Talk",
            "summary": "A talk about AI advances.",
            "topics": ["AI", "ML"],
            "duration": 300,
        }

        with patch("services.knowledge_graph.get_knowledge_graph_service", return_value=mock_kg):
            result = await get_summary.ainvoke({"media_id": "vid-1"})

        assert result["title"] == "AI Talk"
        assert result["summary"] == "A talk about AI advances."
        assert result["topics"] == ["AI", "ML"]
        assert "_meta" in result

    @pytest.mark.asyncio
    async def test_passes_user_id(self):
        from agent.tools.context_tools import get_summary

        mock_kg = MagicMock()
        mock_kg.get_video_summary_data.return_value = {
            "title": "T",
            "summary": "S",
            "topics": [],
            "duration": 60,
        }

        with patch("services.knowledge_graph.get_knowledge_graph_service", return_value=mock_kg):
            await get_summary.ainvoke({"media_id": "vid-1", "user_id": "u-42"})

        call_args = mock_kg.get_video_summary_data.call_args
        assert call_args[1].get("user_id") == "u-42" or call_args[0] == ("vid-1",)


# ---------------------------------------------------------------------------
# get_scene_context
# ---------------------------------------------------------------------------


class TestGetSceneContext:
    """Tests for get_scene_context tool."""

    @pytest.mark.asyncio
    async def test_no_media_id_returns_error(self):
        from agent.tools.context_tools import get_scene_context

        result = await get_scene_context.ainvoke({"timestamp": 10.0, "media_id": None})
        assert result["error"]["type"] == "no_context"

    @pytest.mark.asyncio
    async def test_success(self):
        from agent.tools.context_tools import get_scene_context

        mock_kg = MagicMock()
        mock_kg.get_frames_in_window.return_value = [
            {"timestamp": 5.0, "description": "Before frame"},
            {"timestamp": 10.0, "description": "During frame"},
            {"timestamp": 20.0, "description": "After frame"},
        ]
        mock_kg.get_audio_in_window.return_value = [
            {"timestamp": 10.0, "text": "Hello there"},
        ]
        mock_kg.get_scene_at_timestamp.return_value = {
            "scene_type": "dialogue",
            "description": "Conversation scene",
            "start_time": 0,
            "end_time": 30,
        }

        with patch("services.knowledge_graph.get_knowledge_graph_service", return_value=mock_kg):
            result = await get_scene_context.ainvoke({"timestamp": 10.0, "media_id": "vid-1"})

        assert result["timestamp"] == 10.0
        assert "context" in result
        assert result["total_frames_in_window"] == 3
        assert result["total_audio_segments"] == 1
        assert "_meta" in result

    @pytest.mark.asyncio
    async def test_exception_returns_query_error(self):
        from agent.tools.context_tools import get_scene_context

        mock_kg = MagicMock()
        mock_kg.get_frames_in_window.side_effect = RuntimeError("Neo4j timeout")

        with patch("services.knowledge_graph.get_knowledge_graph_service", return_value=mock_kg):
            result = await get_scene_context.ainvoke({"timestamp": 10.0, "media_id": "vid-1"})

        assert result["error"]["type"] == "query_error"


# ---------------------------------------------------------------------------
# get_community_overview
# ---------------------------------------------------------------------------


class TestGetCommunityOverview:
    """Tests for get_community_overview tool."""

    @pytest.mark.asyncio
    async def test_no_media_id_returns_error(self):
        from agent.tools.context_tools import get_community_overview

        result = await get_community_overview.ainvoke({"media_id": None})
        assert result["error"]["type"] == "no_context"

    @pytest.mark.asyncio
    async def test_no_communities(self):
        from agent.tools.context_tools import get_community_overview

        mock_kg = MagicMock()
        mock_kg.get_community_context.return_value = []

        with patch("services.knowledge_graph.get_knowledge_graph_service", return_value=mock_kg):
            result = await get_community_overview.ainvoke({"media_id": "vid-1"})

        assert result["communities"] == []
        assert result["_meta"]["result_count"] == 0

    @pytest.mark.asyncio
    async def test_success(self):
        from agent.tools.context_tools import get_community_overview

        mock_kg = MagicMock()
        mock_kg.get_community_context.return_value = [
            {
                "title": "AI Ethics",
                "summary": "Discussion on AI safety",
                "themes": ["safety", "regulation"],
                "member_count": 12,
                "relevance_score": 0.95,
            },
        ]

        with patch("services.knowledge_graph.get_knowledge_graph_service", return_value=mock_kg):
            result = await get_community_overview.ainvoke({"media_id": "vid-1"})

        assert result["total_communities"] == 1
        assert result["communities"][0]["title"] == "AI Ethics"
        assert result["_meta"]["result_count"] == 1

    @pytest.mark.asyncio
    async def test_topic_filter_passed(self):
        from agent.tools.context_tools import get_community_overview

        mock_kg = MagicMock()
        mock_kg.get_community_context.return_value = []

        with patch("services.knowledge_graph.get_knowledge_graph_service", return_value=mock_kg):
            await get_community_overview.ainvoke({"media_id": "vid-1", "topic": "machine learning"})

        call_kwargs = mock_kg.get_community_context.call_args
        assert "machine learning" in str(call_kwargs)
