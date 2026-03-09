"""
Unit tests for GraphRouteService.

Covers the business logic extracted from graph route handlers:
- Advanced search orchestration
- Drill-down search formatting
- Children pagination
- Hierarchy metadata construction
- Text-field determination
- Cross-video result transformation
- Entity extraction result formatting
- Video graph assembly
- Health check
- Time range helper
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Ensure backend is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from models.graph_models import (
    GraphSearchQuery,
    NodeType,
)
from services.graph_route_service import (
    AdvancedSearchResult,
    DrillDownFormatResult,
    GraphRouteService,
    HealthCheckResult,
    LoadChildrenResult,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture()
def mock_kg_service():
    """Create a mocked KnowledgeGraphService."""
    svc = MagicMock()
    svc.is_connected = True
    svc.uri = "bolt://localhost:7687"
    return svc


@pytest.fixture()
def service(mock_kg_service):
    """Create a GraphRouteService with mocked dependencies."""
    return GraphRouteService(
        knowledge_graph_service=mock_kg_service,
    )


# =============================================================================
# Health Check
# =============================================================================


@pytest.mark.unit
class TestCheckGraphHealth:
    def test_healthy_when_connected(self, mock_kg_service):
        mock_kg_service.is_connected = True

        result = GraphRouteService.check_graph_health(mock_kg_service)

        assert isinstance(result, HealthCheckResult)
        assert result.status == "healthy"
        assert result.connected is True
        assert result.uri == "bolt://localhost:7687"
        assert "active" in result.message

    def test_unhealthy_when_not_connected_and_connect_fails(self, mock_kg_service):
        mock_kg_service.is_connected = False
        mock_kg_service.connect.return_value = False

        result = GraphRouteService.check_graph_health(mock_kg_service)

        assert result.status == "unhealthy"
        assert result.connected is False
        mock_kg_service.connect.assert_called_once()

    def test_reconnects_successfully(self, mock_kg_service):
        mock_kg_service.is_connected = False
        mock_kg_service.connect.return_value = True

        result = GraphRouteService.check_graph_health(mock_kg_service)

        assert result.status == "healthy"
        assert result.connected is True
        mock_kg_service.connect.assert_called_once()


# =============================================================================
# Advanced Search
# =============================================================================


@pytest.mark.unit
class TestAdvancedSearch:
    def test_returns_error_when_no_service(self):
        svc = GraphRouteService()
        query = GraphSearchQuery(query="test")

        result = svc.advanced_search(query)

        assert isinstance(result, AdvancedSearchResult)
        assert result.error is not None
        assert result.response is None

    def test_entity_only_search(self, service, mock_kg_service):
        mock_kg_service.search_entities.return_value = [
            {"entity": {"id": "e1", "name": "Alice"}, "score": 0.9},
        ]

        query = GraphSearchQuery(
            query="Alice",
            node_types=[NodeType.ENTITY],
            use_graph_expansion=False,
        )
        result = service.advanced_search(query)

        assert result.error is None
        assert result.response is not None
        assert result.response.total_results == 1
        assert result.response.results[0].node_id == "e1"
        assert result.response.results[0].node_type == NodeType.ENTITY
        mock_kg_service.search_entities.assert_called_once()
        mock_kg_service.search_frames_by_description.assert_not_called()

    def test_frame_only_search(self, service, mock_kg_service):
        mock_kg_service.search_frames_by_description.return_value = [
            {"frame": {"id": "f1", "description": "A sunset"}, "score": 0.8},
        ]

        query = GraphSearchQuery(
            query="sunset",
            node_types=[NodeType.FRAME],
            use_graph_expansion=False,
        )
        result = service.advanced_search(query)

        assert result.error is None
        assert result.response.total_results == 1
        assert result.response.results[0].node_type == NodeType.FRAME
        mock_kg_service.search_frames_by_description.assert_called_once()
        mock_kg_service.search_entities.assert_not_called()

    def test_combined_entity_and_frame_search(self, service, mock_kg_service):
        mock_kg_service.search_entities.return_value = [
            {"entity": {"id": "e1"}, "score": 0.9},
        ]
        mock_kg_service.search_frames_by_description.return_value = [
            {"frame": {"id": "f1"}, "score": 0.7},
        ]

        query = GraphSearchQuery(query="test", use_graph_expansion=False)
        result = service.advanced_search(query)

        assert result.response.total_results == 2

    def test_graph_expansion(self, service, mock_kg_service):
        mock_kg_service.search_entities.return_value = [
            {"entity": {"id": "e1"}, "score": 0.9},
        ]
        mock_kg_service.expand_context.return_value = {"nodes_by_distance": {"1": [{"id": "e2"}]}}

        query = GraphSearchQuery(
            query="test",
            node_types=[NodeType.ENTITY],
            use_graph_expansion=True,
            expansion_hops=2,
        )
        result = service.advanced_search(query)

        assert result.error is None
        mock_kg_service.expand_context.assert_called_once()
        assert result.response.graph_expansion_time_ms >= 0

    def test_graph_expansion_failure_handled(self, service, mock_kg_service):
        mock_kg_service.search_entities.return_value = [
            {"entity": {"id": "e1"}, "score": 0.9},
        ]
        mock_kg_service.expand_context.side_effect = RuntimeError("Neo4j down")

        query = GraphSearchQuery(
            query="test",
            node_types=[NodeType.ENTITY],
            use_graph_expansion=True,
        )
        result = service.advanced_search(query)

        # Should not propagate the error
        assert result.error is None
        assert result.response.total_results == 1

    def test_respects_limit(self, service, mock_kg_service):
        mock_kg_service.search_entities.return_value = [
            {"entity": {"id": f"e{i}"}, "score": 0.9 - i * 0.01} for i in range(10)
        ]

        query = GraphSearchQuery(
            query="test",
            node_types=[NodeType.ENTITY],
            use_graph_expansion=False,
            limit=3,
        )
        result = service.advanced_search(query)

        assert result.response.total_results == 3

    def test_video_id_filter_passed(self, service, mock_kg_service):
        mock_kg_service.search_entities.return_value = []

        query = GraphSearchQuery(
            query="test",
            video_ids=["vid-1"],
            node_types=[NodeType.ENTITY],
            use_graph_expansion=False,
        )
        service.advanced_search(query)

        mock_kg_service.search_entities.assert_called_once_with(
            query_text="test",
            entity_types=None,
            video_id="vid-1",
            limit=20,
        )

    def test_timing_metrics_populated(self, service, mock_kg_service):
        mock_kg_service.search_entities.return_value = []

        query = GraphSearchQuery(
            query="test",
            node_types=[NodeType.ENTITY],
            use_graph_expansion=False,
        )
        result = service.advanced_search(query)

        assert result.response.search_time_ms >= 0
        assert result.response.vector_search_time_ms >= 0


# =============================================================================
# Video Graph Data
# =============================================================================


@pytest.mark.unit
class TestGetVideoGraphData:
    def test_returns_error_when_no_service(self):
        svc = GraphRouteService()
        data = svc.get_video_graph_data("vid-1")
        assert data.error is not None

    def test_returns_error_when_video_not_found(self, service, mock_kg_service):
        mock_kg_service.get_video_node.return_value = None

        data = service.get_video_graph_data("missing-vid")

        assert data.error is not None
        assert "missing-vid" in data.error

    def test_assembles_video_graph_data(self, service, mock_kg_service):
        mock_kg_service.get_video_node.return_value = {"id": "v1", "title": "Demo"}
        mock_kg_service.get_video_scenes.return_value = [
            {"id": "s1"},
            {"id": "s2"},
        ]
        stats_mock = MagicMock()
        stats_mock.model_dump.return_value = {"total_nodes": 100}
        mock_kg_service.get_stats.return_value = stats_mock

        data = service.get_video_graph_data("v1")

        assert data.error is None
        assert data.video == {"id": "v1", "title": "Demo"}
        assert data.total_scenes == 2
        assert data.graph_stats == {"total_nodes": 100}


# =============================================================================
# Cross-Video Results
# =============================================================================


@pytest.mark.unit
class TestBuildCrossVideoResults:
    def test_transforms_nodes(self):
        nodes = [
            SimpleNamespace(
                node_id="n1",
                node_type=NodeType.ENTITY,
                video_id="v2",
                vector_score=0.95,
                content={"name": "Alice"},
            ),
            SimpleNamespace(
                node_id="n2",
                node_type=NodeType.FRAME,
                video_id="v3",
                vector_score=0.80,
                content={"description": "sunset"},
            ),
        ]

        result = GraphRouteService.build_cross_video_results(nodes)

        assert len(result) == 2
        assert result[0]["node_id"] == "n1"
        assert result[0]["node_type"] == "Entity"
        assert result[0]["similarity"] == 0.95
        assert result[1]["video_id"] == "v3"

    def test_empty_list(self):
        assert GraphRouteService.build_cross_video_results([]) == []


# =============================================================================
# Text Field Determination
# =============================================================================


@pytest.mark.unit
class TestDetermineTextField:
    def test_entity_uses_name(self):
        assert GraphRouteService.determine_text_field(NodeType.ENTITY) == "name"

    def test_audio_segment_uses_text(self):
        assert GraphRouteService.determine_text_field(NodeType.AUDIO_SEGMENT) == "text"

    def test_frame_uses_description(self):
        assert GraphRouteService.determine_text_field(NodeType.FRAME) == "description"

    def test_scene_uses_description(self):
        assert GraphRouteService.determine_text_field(NodeType.SCENE) == "description"

    def test_video_uses_description(self):
        assert GraphRouteService.determine_text_field(NodeType.VIDEO) == "description"


# =============================================================================
# Hierarchy Metadata
# =============================================================================


@pytest.mark.unit
class TestBuildHierarchyMetadata:
    def test_with_all_fields(self):
        meta = GraphRouteService.build_hierarchy_metadata(
            video_id="v1",
            title="My Video",
            fps=30.0,
            duration=120.0,
            resolution=(1920, 1080),
        )

        assert meta["video_id"] == "v1"
        assert meta["media_id"] == "v1"
        assert meta["title"] == "My Video"
        assert meta["fps"] == 30.0
        assert meta["duration"] == 120.0
        assert meta["resolution"] == (1920, 1080)
        assert meta["file_size_bytes"] == 0
        assert meta["format"] == "mp4"

    def test_defaults_title_when_none(self):
        meta = GraphRouteService.build_hierarchy_metadata(
            video_id="v1",
            title=None,
            fps=24.0,
            duration=None,
            resolution=(1280, 720),
        )

        assert meta["title"] == "Video v1"
        assert meta["duration"] == 0


# =============================================================================
# Drill-Down Results Formatting
# =============================================================================


@pytest.mark.unit
class TestFormatDrillDownResults:
    def _make_result(self, level="scene", node_id="s1", title="Scene 1"):
        """Helper to build a mock DrillDownResult."""
        current = SimpleNamespace(
            level=level,
            node_id=node_id,
            node_type=NodeType.SCENE,
            summary="Summary",
            title=title,
            start_time=0.0,
            end_time=10.0,
        )
        root_level = SimpleNamespace(
            level="video",
            node_id="v1",
            title="Root Video",
        )
        return SimpleNamespace(
            current_level=current,
            path_from_root=[root_level],
            has_more_levels=True,
        )

    def test_empty_results(self):
        formatted = GraphRouteService.format_drill_down_results([])
        assert isinstance(formatted, DrillDownFormatResult)
        assert formatted.total_results == 0
        assert formatted.results == []
        assert formatted.levels_traversed == []

    def test_single_result(self):
        results = [self._make_result()]
        formatted = GraphRouteService.format_drill_down_results(results)

        assert formatted.total_results == 1
        r = formatted.results[0]
        assert r["current_level"]["node_id"] == "s1"
        assert r["current_level"]["node_type"] == "Scene"
        assert r["has_more_levels"] is True
        assert len(r["path"]) == 1
        assert r["path"][0]["level"] == "video"

    def test_multiple_results_collect_levels(self):
        r1 = self._make_result(level="scene", node_id="s1")
        r2 = self._make_result(level="chapter", node_id="c1")
        # Add a chapter-level path entry
        r2.path_from_root = [
            SimpleNamespace(level="video", node_id="v1", title="Root"),
            SimpleNamespace(level="chapter", node_id="c1", title="Ch 1"),
        ]

        formatted = GraphRouteService.format_drill_down_results([r1, r2])

        assert formatted.total_results == 2
        assert "video" in formatted.levels_traversed
        assert "chapter" in formatted.levels_traversed


# =============================================================================
# Pagination
# =============================================================================


@pytest.mark.unit
class TestPaginateChildren:
    def test_has_more_when_exceeds_limit(self):
        children = list(range(6))  # 6 items
        result = GraphRouteService.paginate_children(children, requested_limit=5)

        assert isinstance(result, LoadChildrenResult)
        assert result.has_more is True
        assert result.total_children == 5
        assert len(result.children) == 5

    def test_no_more_when_at_limit(self):
        children = list(range(5))
        result = GraphRouteService.paginate_children(children, requested_limit=5)

        assert result.has_more is False
        assert result.total_children == 5

    def test_no_more_when_under_limit(self):
        children = list(range(3))
        result = GraphRouteService.paginate_children(children, requested_limit=5)

        assert result.has_more is False
        assert result.total_children == 3

    def test_empty_children(self):
        result = GraphRouteService.paginate_children([], requested_limit=10)
        assert result.has_more is False
        assert result.total_children == 0


# =============================================================================
# Entity Extraction Formatting
# =============================================================================


@pytest.mark.unit
class TestFormatExtractionResults:
    def _make_entity(self, name="Alice"):
        entity = MagicMock()
        entity.model_dump.return_value = {"name": name, "type": "person"}
        return entity

    def _make_extraction_result(self, *, include_description=True):
        result = SimpleNamespace(
            frame_id="f1",
            timestamp=1.5,
            entities=[self._make_entity("Alice"), self._make_entity("Bob")],
            relations=[{"type": "INTERACTS_WITH"}],
            topics=["meeting"],
            actions=["talking"],
            analysis_time_ms=150,
        )
        if include_description:
            result.description = "Two people talking"
        return result

    def test_format_frame_extraction(self):
        result = self._make_extraction_result(include_description=True)
        formatted = GraphRouteService.format_frame_extraction_result(result)

        assert formatted["frame_id"] == "f1"
        assert formatted["timestamp"] == 1.5
        assert formatted["description"] == "Two people talking"
        assert len(formatted["entities"]) == 2
        assert formatted["entities"][0] == {"name": "Alice", "type": "person"}
        assert formatted["topics"] == ["meeting"]
        assert formatted["analysis_time_ms"] == 150

    def test_format_description_extraction(self):
        result = self._make_extraction_result(include_description=False)
        formatted = GraphRouteService.format_description_extraction_result(result)

        assert formatted["frame_id"] == "f1"
        assert "description" not in formatted
        assert len(formatted["entities"]) == 2
        assert formatted["actions"] == ["talking"]


# =============================================================================
# Time Range Helper
# =============================================================================


@pytest.mark.unit
class TestBuildTimeRange:
    def test_both_provided(self):
        assert GraphRouteService.build_time_range(1.0, 5.0) == (1.0, 5.0)

    def test_start_none(self):
        assert GraphRouteService.build_time_range(None, 5.0) is None

    def test_end_none(self):
        assert GraphRouteService.build_time_range(1.0, None) is None

    def test_both_none(self):
        assert GraphRouteService.build_time_range(None, None) is None

    def test_zero_values(self):
        assert GraphRouteService.build_time_range(0.0, 0.0) == (0.0, 0.0)
