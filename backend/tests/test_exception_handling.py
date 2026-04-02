"""
Tests for exception handling audit fixes.

Validates that:
1. Graph/DB operations log at warning level (not debug)
2. Silent exception swallowing now includes debug logging
3. Re-raised exceptions use ``raise ... from e`` (PEP 3134 / B904)
"""

import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure backend is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from models.graph_models import NodeType
from services.graph_search_queries import ScoredNode

# =============================================================================
# Graph Search Queries – logging level
# =============================================================================


def _make_search_service():
    """Create a GraphSearchService with mocked dependencies for mixin tests."""
    from services.graph_search_service import GraphSearchService

    svc = GraphSearchService.__new__(GraphSearchService)
    svc.graph_service = MagicMock()
    svc.embedding_service = MagicMock()
    return svc


@pytest.mark.unit
class TestGraphSearchQueriesLogging:
    """Verify graph_search_queries logs at WARNING for graph operations."""

    def test_vector_query_failure_logs_warning(self, caplog):
        svc = _make_search_service()
        svc.graph_service.get_session.side_effect = RuntimeError("connection lost")

        with caplog.at_level(logging.DEBUG, logger="services.graph_search_queries"):
            results = svc._run_vector_query("test_index", [0.1] * 10, 20, NodeType.ENTITY)

        warning_msgs = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            "Vector query" in m.message for m in warning_msgs
        ), "Expected a WARNING log for vector query failure"
        assert results == []

    def test_fulltext_search_failure_logs_warning(self, caplog):
        svc = _make_search_service()
        svc.graph_service.get_session.side_effect = RuntimeError("connection lost")

        with caplog.at_level(logging.DEBUG, logger="services.graph_search_queries"):
            results = svc._fulltext_search("test query", NodeType.ENTITY, limit=10, video_id=None)

        warning_msgs = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            "Full-text search failed" in m.message for m in warning_msgs
        ), "Expected a WARNING log for fulltext search failure"
        assert results == []

    def test_get_node_by_id_failure_logs_warning(self, caplog):
        svc = _make_search_service()
        svc.graph_service.get_session.side_effect = RuntimeError("timeout")

        with caplog.at_level(logging.DEBUG, logger="services.graph_search_queries"):
            result = svc._get_node_by_id("node-123", NodeType.ENTITY)

        warning_msgs = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            "Failed to get node" in m.message for m in warning_msgs
        ), "Expected a WARNING log for node fetch failure"
        assert result is None


# =============================================================================
# Graph Search Scoring – logging level
# =============================================================================


@pytest.mark.unit
class TestGraphSearchScoringLogging:
    """Verify graph_search_scoring logs at WARNING for graph expansion failures."""

    def test_graph_expansion_failure_logs_warning(self, caplog):
        svc = _make_search_service()

        candidate = ScoredNode(
            node_id="n1",
            node_type=NodeType.ENTITY,
            content={"id": "n1", "name": "Test"},
            vector_score=0.8,
        )

        # Make expand_context raise to trigger the graph expansion except block
        svc.graph_service.expand_context.side_effect = RuntimeError("boom")

        with caplog.at_level(logging.DEBUG, logger="services.graph_search_scoring"):
            svc._calculate_graph_scores([candidate], expansion_hops=1)

        warning_msgs = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            "Graph expansion failed" in m.message for m in warning_msgs
        ), "Expected a WARNING log for graph expansion failure"
        assert candidate.graph_score == 0.0


# =============================================================================
# FFmpeg Processor – raise from & debug logging
# =============================================================================


@pytest.mark.unit
class TestFFmpegProcessorExceptionChain:
    """Verify ffmpeg_processor uses raise-from for proper exception chaining."""

    def test_get_video_info_preserves_exception_chain(self):
        from services.ffmpeg_processor import FFmpegVideoProcessor

        processor = FFmpegVideoProcessor()

        with pytest.raises(RuntimeError) as exc_info:
            processor.get_video_info("/nonexistent/path.mp4")

        # PEP 3134: __cause__ should be set via `raise ... from e`
        assert (
            exc_info.value.__cause__ is not None
        ), "RuntimeError should chain original exception via 'from e'"

    def test_optimal_workers_returns_valid_count(self):
        from services.ffmpeg_processor import _get_optimal_workers

        result = _get_optimal_workers()
        assert isinstance(result, int)
        assert result >= 2


# =============================================================================
# Graph Route Service – exception logging
# =============================================================================


@pytest.mark.unit
class TestGraphRouteServiceExpansionLogging:
    """Verify graph_route_service logs at WARNING for graph expansion failures."""

    def test_expansion_failure_logs_warning(self, caplog):
        from models.graph_models import GraphSearchQuery
        from services.graph_route_service import GraphRouteService

        mock_kg = MagicMock()
        mock_kg.is_connected = True
        svc = GraphRouteService(knowledge_graph_service=mock_kg)

        # Search returns a result that triggers expansion
        mock_kg.search_entities.return_value = [
            {"entity": {"id": "e1", "name": "Test"}, "score": 0.9}
        ]
        # Expansion fails
        mock_kg.expand_context.side_effect = RuntimeError("graph unavailable")

        query = GraphSearchQuery(
            query="Test",
            node_types=[NodeType.ENTITY],
            use_graph_expansion=True,
            expansion_hops=1,
        )

        with caplog.at_level(logging.DEBUG, logger="services.graph_route_service"):
            svc.advanced_search(query)

        warning_msgs = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            "Graph expansion failed" in m.message for m in warning_msgs
        ), "Expected a WARNING log for graph expansion failure in route service"
