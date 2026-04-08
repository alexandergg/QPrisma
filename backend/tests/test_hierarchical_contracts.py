"""
Contract tests for HierarchicalContextService read methods.

These tests protect Phase 7 (async prep) and Phase 8 (service split) by
establishing behavioral contracts for the public query/read methods.
"""

from unittest.mock import MagicMock, patch

import pytest

from services.hierarchical_context_service import HierarchicalContextService


@pytest.fixture
def mock_graph_service():
    """Mock KnowledgeGraphService with execute_query and get_session."""
    svc = MagicMock()
    return svc


@pytest.fixture
def service(mock_graph_service):
    """HierarchicalContextService with mocked dependencies."""
    with patch("services.hierarchical_context_service.HierarchicalSummarizer"):
        return HierarchicalContextService(
            graph_service=mock_graph_service,
            embedding_service=MagicMock(),
        )


# =============================================================================
# _determine_level
# =============================================================================


class TestDetermineLevel:
    """Contract: _determine_level maps Neo4j labels → hierarchy string."""

    def test_video_label(self, service):
        assert service._query_service._determine_level(frozenset({"Video"})) == "video"

    def test_chapter_label(self, service):
        assert service._query_service._determine_level(frozenset({"Chapter"})) == "chapter"

    def test_scene_label(self, service):
        assert service._query_service._determine_level(frozenset({"Scene"})) == "scene"

    def test_frame_label(self, service):
        assert service._query_service._determine_level(frozenset({"Frame"})) == "frame"

    def test_unknown_label(self, service):
        assert service._query_service._determine_level(frozenset({"Entity"})) == "unknown"

    def test_empty_labels(self, service):
        assert service._query_service._determine_level(frozenset()) == "unknown"

    def test_multiple_labels_video_wins(self, service):
        # In Neo4j a node can have multiple labels
        assert service._query_service._determine_level(frozenset({"BaseNode", "Video"})) == "video"


# =============================================================================
# get_hierarchy_stats
# =============================================================================


class TestGetHierarchyStats:
    """Contract: get_hierarchy_stats returns structured dict or error."""

    @pytest.mark.asyncio
    async def test_returns_stats_for_existing_video(self, service, mock_graph_service):
        mock_graph_service.execute_query.return_value = {
            "video_title": "Test Video",
            "duration": 120.5,
            "chapter_count": 3,
            "scene_count": 10,
            "frame_count": 50,
            "has_video_embedding": True,
        }

        result = await service.get_hierarchy_stats("vid-123")

        assert result["video_id"] == "vid-123"
        assert result["video_title"] == "Test Video"
        assert result["hierarchy"]["chapters"] == 3
        assert result["hierarchy"]["scenes"] == 10
        assert result["hierarchy"]["frames"] == 50
        assert result["embeddings"]["video"] is True

    @pytest.mark.asyncio
    async def test_returns_error_for_missing_video(self, service, mock_graph_service):
        mock_graph_service.execute_query.return_value = None

        result = await service.get_hierarchy_stats("nonexistent")

        assert result == {"error": "Video not found"}


# =============================================================================
# get_hierarchy_path
# =============================================================================


class TestGetHierarchyPath:
    """Contract: get_hierarchy_path returns list of HierarchyLevel from root to target."""

    @pytest.mark.asyncio
    async def test_returns_empty_for_missing_node(self, service, mock_graph_service):
        from models.graph_models import NodeType

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.run.return_value.single.return_value = None
        mock_graph_service.get_session.return_value = mock_session

        result = await service.get_hierarchy_path("missing-id", NodeType.SCENE)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_path_for_scene(self, service, mock_graph_service):
        from models.graph_models import NodeType

        # Simulate a path: Video → Chapter → Scene
        video_node = MagicMock()
        video_node.labels = frozenset({"Video"})
        video_node.__getitem__ = lambda self, key: {
            "id": "v1",
            "summary": "A video",
            "title": "Title",
            "start_time": 0,
            "end_time": 100,
        }.get(key)
        video_node.items = lambda: {
            "id": "v1",
            "summary": "A video",
            "title": "Title",
            "start_time": 0,
            "end_time": 100,
        }.items()
        video_node.keys = lambda: ["id", "summary", "title", "start_time", "end_time"]

        scene_node = MagicMock()
        scene_node.labels = frozenset({"Scene"})
        scene_node.__getitem__ = lambda self, key: {
            "id": "s1",
            "description": "A scene",
            "title": None,
            "start_time": 10,
            "end_time": 30,
        }.get(key)
        scene_node.items = lambda: {
            "id": "s1",
            "description": "A scene",
            "title": None,
            "start_time": 10,
            "end_time": 30,
        }.items()
        scene_node.keys = lambda: ["id", "description", "title", "start_time", "end_time"]

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_record = {"path_nodes": [video_node, scene_node]}
        mock_session.run.return_value.single.return_value = mock_record
        mock_graph_service.get_session.return_value = mock_session

        result = await service.get_hierarchy_path("s1", NodeType.SCENE)

        assert len(result) == 2
        assert result[0].level == "video"
        assert result[0].node_id == "v1"
        assert result[1].level == "scene"
        assert result[1].node_id == "s1"

    @pytest.mark.asyncio
    async def test_session_called_with_node_id(self, service, mock_graph_service):
        from models.graph_models import NodeType

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.run.return_value.single.return_value = None
        mock_graph_service.get_session.return_value = mock_session

        await service.get_hierarchy_path("target-123", NodeType.FRAME)

        mock_session.run.assert_called_once()
        call_kwargs = mock_session.run.call_args
        assert call_kwargs[1]["node_id"] == "target-123"
