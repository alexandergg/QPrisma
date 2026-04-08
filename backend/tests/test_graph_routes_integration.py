"""
Integration tests for all 18 Knowledge Graph API route endpoints.

Covers: auth (401/403), happy path (200), service errors (500),
and endpoint-specific edge cases for graph_routes.py.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

# Patch target prefix
_P = "api.routes.graph_routes"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _mock_media(video_id="vid-1", user_id="user_test123"):
    """Return a lightweight mock media object."""
    m = MagicMock()
    m.id = video_id
    m.user_id = user_id
    return m


def _async_graph_service():
    """Pre-wired AsyncMock that satisfies every async graph facade method."""
    svc = AsyncMock()
    svc.get_stats = AsyncMock(
        return_value=MagicMock(
            total_nodes=100,
            total_relations=50,
            nodes_by_type={},
            relations_by_type={},
            total_videos=1,
            total_frames_indexed=10,
            total_entities_extracted=5,
            avg_relations_per_node=0.5,
            max_depth=3,
        )
    )
    svc.expand_context = AsyncMock(
        return_value={
            "center_node_id": "n1",
            "hops": 2,
            "total_nodes": 3,
            "nodes_by_distance": {"1": [], "2": []},
        }
    )
    svc.get_entity_timeline = AsyncMock(return_value=[])
    svc.delete_video_graph = AsyncMock(return_value=5)
    svc.clear_all = AsyncMock()
    svc.get_video_subgraph = AsyncMock(
        return_value={
            "nodes": [{"id": "n1", "labels": ["Video"], "properties": {"title": "Test"}}],
            "relationships": [
                {"id": "r1", "start": "n1", "end": "n2", "type": "CONTAINS", "properties": {}}
            ],
        }
    )
    svc.expand_node_subgraph = AsyncMock(
        return_value={
            "nodes": [{"id": "n1", "labels": ["Scene"], "properties": {"description": "A scene"}}],
            "relationships": [],
        }
    )
    # sync_service sub-mock used by health check
    svc.sync_service = MagicMock()
    return svc


def _graph_route_service():
    """Pre-wired MagicMock for GraphRouteService."""
    svc = MagicMock()
    svc.check_graph_health.return_value = SimpleNamespace(
        status="healthy",
        connected=True,
        uri="bolt://localhost:7687",
        message="Neo4j connection is active",
    )
    svc.get_video_graph_data.return_value = SimpleNamespace(
        error=None,
        video={"id": "vid-1"},
        scenes=[],
        total_scenes=0,
        graph_stats={},
    )
    svc.build_hierarchy_metadata.return_value = {
        "media_id": "vid-1",
        "video_id": "vid-1",
        "user_id": "user_test123",
        "title": "Test",
        "fps": 30.0,
        "duration": 120,
        "resolution": [1920, 1080],
    }
    return svc


def _graph_search_service():
    """Pre-wired MagicMock whose async methods are AsyncMock."""
    svc = MagicMock()
    svc.hybrid_search = AsyncMock(
        return_value=MagicMock(
            query="test",
            total_results=0,
            results=[],
            search_time_ms=1.0,
            embedding_time_ms=0.0,
            vector_search_time_ms=0.5,
            fulltext_search_time_ms=0.0,
            graph_expansion_time_ms=0.2,
            temporal_scoring_time_ms=0.0,
            reranking_time_ms=0.0,
            facets={},
        )
    )
    svc.find_similar_across_videos = AsyncMock(return_value=[])
    svc.bulk_generate_embeddings = AsyncMock(return_value=10)
    return svc


def _hierarchy_service():
    """Pre-wired AsyncMock for HierarchicalContextService."""
    svc = AsyncMock()
    svc.process_video_hierarchy = AsyncMock(
        return_value={
            "video_id": "vid-1",
            "status": "completed",
            "levels_processed": {},
            "embeddings_generated": {},
            "nodes_created": {},
            "processing_time_seconds": 1.5,
            "errors": [],
        }
    )
    svc.drill_down_search = AsyncMock(return_value=[])
    svc.load_children = AsyncMock(return_value=[])
    svc.get_hierarchy_stats = AsyncMock(
        return_value={
            "video_id": "vid-1",
            "video_title": "Test",
            "duration_seconds": 120.0,
            "hierarchy": {},
            "embeddings": {},
        }
    )
    svc.get_hierarchy_path = AsyncMock(return_value=[])
    return svc


def _embedding_service():
    """Pre-wired MagicMock for EmbeddingService."""
    svc = MagicMock()
    svc.get_stats.return_value = {
        "total_requests": 100,
        "cache_hits": 30,
        "cache_hit_rate": 0.3,
        "tokens_used": 5000,
    }
    return svc


# ============================================================================
# 1. GET /graph/health
# ============================================================================


@pytest.mark.unit
class TestGraphHealth:
    def test_requires_auth(self, client):
        resp = client.get("/graph/health")
        assert resp.status_code in (401, 403)

    def test_happy_path(self, authenticated_client):
        with (
            patch(f"{_P}.get_async_graph_service", return_value=_async_graph_service()),
            patch(f"{_P}.get_graph_route_service", return_value=_graph_route_service()),
        ):
            resp = authenticated_client.get("/graph/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert body["connected"] is True

    def test_service_error_returns_error_status(self, authenticated_client):
        """When an exception is raised, health returns status=error (not 500)."""
        with patch(f"{_P}.get_async_graph_service", side_effect=RuntimeError("boom")):
            resp = authenticated_client.get("/graph/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"
        assert resp.json()["connected"] is False


# ============================================================================
# 2. GET /graph/stats
# ============================================================================


@pytest.mark.unit
class TestGraphStats:
    def test_requires_auth(self, client):
        resp = client.get("/graph/stats")
        assert resp.status_code in (401, 403)

    def test_happy_path(self, authenticated_client):
        with patch(f"{_P}.get_async_graph_service", return_value=_async_graph_service()):
            resp = authenticated_client.get("/graph/stats")
        assert resp.status_code == 200
        assert resp.json()["total_nodes"] == 100

    def test_service_error_returns_500(self, authenticated_client):
        svc = _async_graph_service()
        svc.get_stats = AsyncMock(side_effect=RuntimeError("neo4j down"))
        with patch(f"{_P}.get_async_graph_service", return_value=svc):
            resp = authenticated_client.get("/graph/stats")
        assert resp.status_code == 500


# ============================================================================
# 3. POST /graph/search/hybrid
# ============================================================================


@pytest.mark.unit
class TestHybridSearch:
    _payload = {"query": "test search"}

    def test_requires_auth(self, client):
        resp = client.post("/graph/search/hybrid", json=self._payload)
        assert resp.status_code in (401, 403)

    def test_happy_path(self, authenticated_client):
        with (patch(f"{_P}.get_graph_search_service", return_value=_graph_search_service()),):
            resp = authenticated_client.post("/graph/search/hybrid", json=self._payload)
        assert resp.status_code == 200
        assert resp.json()["total_results"] == 0

    def test_with_video_id_validates_ownership(self, authenticated_client):
        with (
            patch(
                f"{_P}.get_media_or_404",
                side_effect=HTTPException(status_code=404, detail="Not found"),
            ),
        ):
            resp = authenticated_client.post(
                "/graph/search/hybrid", json={"query": "q", "video_id": "bad-vid"}
            )
        assert resp.status_code == 404

    def test_service_error_returns_500(self, authenticated_client):
        svc = _graph_search_service()
        svc.hybrid_search = AsyncMock(side_effect=RuntimeError("search crash"))
        with patch(f"{_P}.get_graph_search_service", return_value=svc):
            resp = authenticated_client.post("/graph/search/hybrid", json=self._payload)
        assert resp.status_code == 500


# ============================================================================
# 4. POST /graph/search/cross-video
# ============================================================================


@pytest.mark.unit
class TestCrossVideoSearch:
    _payload = {"reference_node_id": "node-1"}

    def test_requires_auth(self, client):
        resp = client.post("/graph/search/cross-video", json=self._payload)
        assert resp.status_code in (401, 403)

    def test_happy_path(self, authenticated_client):
        with (
            patch(f"{_P}.get_graph_node_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_graph_search_service", return_value=_graph_search_service()),
        ):
            resp = authenticated_client.post("/graph/search/cross-video", json=self._payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["reference_node_id"] == "node-1"
        assert body["total_found"] == 0

    def test_node_not_found_returns_404(self, authenticated_client):
        with patch(
            f"{_P}.get_graph_node_media_or_404",
            side_effect=HTTPException(status_code=404, detail="Node not found"),
        ):
            resp = authenticated_client.post("/graph/search/cross-video", json=self._payload)
        assert resp.status_code == 404


# ============================================================================
# 5. POST /graph/embeddings/generate
# ============================================================================


@pytest.mark.unit
class TestGenerateEmbeddings:
    _payload = {"node_type": "Scene", "video_id": "vid-1"}

    def test_requires_auth(self, client):
        resp = client.post("/graph/embeddings/generate", json=self._payload)
        assert resp.status_code in (401, 403)

    def test_happy_path_with_video_id(self, authenticated_client):
        with (
            patch(f"{_P}.get_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_graph_search_service", return_value=_graph_search_service()),
        ):
            resp = authenticated_client.post("/graph/embeddings/generate", json=self._payload)
        assert resp.status_code == 200
        assert resp.json()["embeddings_generated"] == 10

    def test_no_video_id_non_superuser_returns_403(self, authenticated_client):
        """Non-superuser must supply a video_id."""
        resp = authenticated_client.post("/graph/embeddings/generate", json={"node_type": "Scene"})
        assert resp.status_code == 403

    def test_no_video_id_superuser_allowed(self, app, superuser):
        from api.dependencies import get_current_user

        app.dependency_overrides[get_current_user] = lambda: superuser
        with (
            TestClient(app, raise_server_exceptions=False) as su_client,
            patch(f"{_P}.get_graph_search_service", return_value=_graph_search_service()),
        ):
            resp = su_client.post("/graph/embeddings/generate", json={"node_type": "Scene"})
        assert resp.status_code == 200

    def test_service_error_returns_500(self, authenticated_client):
        svc = _graph_search_service()
        svc.bulk_generate_embeddings = AsyncMock(side_effect=RuntimeError("oops"))
        with (
            patch(f"{_P}.get_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_graph_search_service", return_value=svc),
        ):
            resp = authenticated_client.post("/graph/embeddings/generate", json=self._payload)
        assert resp.status_code == 500


# ============================================================================
# 6. GET /graph/embeddings/stats
# ============================================================================


@pytest.mark.unit
class TestEmbeddingStats:
    def test_requires_auth(self, client):
        resp = client.get("/graph/embeddings/stats")
        assert resp.status_code in (401, 403)

    def test_happy_path(self, authenticated_client):
        with patch(f"{_P}.get_embedding_service", return_value=_embedding_service()):
            resp = authenticated_client.get("/graph/embeddings/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_requests"] == 100
        assert body["cache_hits"] == 30

    def test_service_error_returns_500(self, authenticated_client):
        svc = MagicMock()
        svc.get_stats.side_effect = RuntimeError("redis gone")
        with patch(f"{_P}.get_embedding_service", return_value=svc):
            resp = authenticated_client.get("/graph/embeddings/stats")
        assert resp.status_code == 500


# ============================================================================
# 7. POST /graph/expand
# ============================================================================


@pytest.mark.unit
class TestExpandContext:
    _payload = {"node_id": "n1"}

    def test_requires_auth(self, client):
        resp = client.post("/graph/expand", json=self._payload)
        assert resp.status_code in (401, 403)

    def test_happy_path(self, authenticated_client):
        with (
            patch(f"{_P}.get_graph_node_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_async_graph_service", return_value=_async_graph_service()),
        ):
            resp = authenticated_client.post("/graph/expand", json=self._payload)
        assert resp.status_code == 200
        assert resp.json()["center_node_id"] == "n1"

    def test_service_error_returns_500(self, authenticated_client):
        svc = _async_graph_service()
        svc.expand_context = AsyncMock(side_effect=RuntimeError("expand fail"))
        with (
            patch(f"{_P}.get_graph_node_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_async_graph_service", return_value=svc),
        ):
            resp = authenticated_client.post("/graph/expand", json=self._payload)
        assert resp.status_code == 500


# ============================================================================
# 8. POST /graph/timeline
# ============================================================================


@pytest.mark.unit
class TestEntityTimeline:
    _payload = {"entity_name": "laptop", "video_id": "vid-1"}

    def test_requires_auth(self, client):
        resp = client.post("/graph/timeline", json=self._payload)
        assert resp.status_code in (401, 403)

    def test_happy_path(self, authenticated_client):
        with (
            patch(f"{_P}.get_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_async_graph_service", return_value=_async_graph_service()),
        ):
            resp = authenticated_client.post("/graph/timeline", json=self._payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["entity_name"] == "laptop"
        assert body["total_occurrences"] == 0

    def test_video_not_found_returns_404(self, authenticated_client):
        with patch(
            f"{_P}.get_media_or_404",
            side_effect=HTTPException(status_code=404, detail="Not found"),
        ):
            resp = authenticated_client.post("/graph/timeline", json=self._payload)
        assert resp.status_code == 404


# ============================================================================
# 9. GET /graph/video/{video_id}
# ============================================================================


@pytest.mark.unit
class TestGetVideoGraph:
    def test_requires_auth(self, client):
        resp = client.get("/graph/video/vid-1")
        assert resp.status_code in (401, 403)

    def test_happy_path(self, authenticated_client):
        with (
            patch(f"{_P}.get_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_graph_route_service", return_value=_graph_route_service()),
        ):
            resp = authenticated_client.get("/graph/video/vid-1")
        assert resp.status_code == 200
        assert resp.json()["video"]["id"] == "vid-1"

    def test_graph_data_error_returns_404(self, authenticated_client):
        """When get_video_graph_data returns data.error, endpoint should 404."""
        svc = _graph_route_service()
        svc.get_video_graph_data.return_value = SimpleNamespace(
            error="Video not found in graph",
            video=None,
            scenes=[],
            total_scenes=0,
            graph_stats={},
        )
        with (
            patch(f"{_P}.get_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_graph_route_service", return_value=svc),
        ):
            resp = authenticated_client.get("/graph/video/vid-1")
        assert resp.status_code == 404

    def test_service_error_returns_500(self, authenticated_client):
        svc = _graph_route_service()
        svc.get_video_graph_data.side_effect = RuntimeError("kaboom")
        with (
            patch(f"{_P}.get_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_graph_route_service", return_value=svc),
        ):
            resp = authenticated_client.get("/graph/video/vid-1")
        assert resp.status_code == 500


# ============================================================================
# 10. DELETE /graph/video/{video_id}
# ============================================================================


@pytest.mark.unit
class TestDeleteVideoGraph:
    def test_requires_auth(self, client):
        resp = client.delete("/graph/video/vid-1")
        assert resp.status_code in (401, 403)

    def test_happy_path(self, authenticated_client):
        with (
            patch(f"{_P}.get_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_async_graph_service", return_value=_async_graph_service()),
        ):
            resp = authenticated_client.delete("/graph/video/vid-1")
        assert resp.status_code == 200
        assert resp.json()["deleted_nodes"] == 5

    def test_service_error_returns_500(self, authenticated_client):
        svc = _async_graph_service()
        svc.delete_video_graph = AsyncMock(side_effect=RuntimeError("delete fail"))
        with (
            patch(f"{_P}.get_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_async_graph_service", return_value=svc),
        ):
            resp = authenticated_client.delete("/graph/video/vid-1")
        assert resp.status_code == 500


# ============================================================================
# 11. POST /graph/hierarchy/process
# ============================================================================


@pytest.mark.unit
class TestProcessHierarchy:
    _payload = {
        "video_path": "/videos/test.mp4",
        "video_id": "vid-1",
        "title": "Test Video",
        "fps": 30.0,
        "duration": 120.0,
        "resolution": [1920, 1080],
    }

    def test_requires_auth(self, client):
        resp = client.post("/graph/hierarchy/process", json=self._payload)
        assert resp.status_code in (401, 403)

    def test_happy_path(self, authenticated_client):
        with (
            patch(f"{_P}.get_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_hierarchical_context_service", return_value=_hierarchy_service()),
            patch(f"{_P}.get_graph_route_service", return_value=_graph_route_service()),
        ):
            resp = authenticated_client.post("/graph/hierarchy/process", json=self._payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["video_id"] == "vid-1"
        assert body["status"] == "completed"

    def test_service_error_returns_500(self, authenticated_client):
        hsvc = _hierarchy_service()
        hsvc.process_video_hierarchy = AsyncMock(side_effect=RuntimeError("fail"))
        with (
            patch(f"{_P}.get_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_hierarchical_context_service", return_value=hsvc),
            patch(f"{_P}.get_graph_route_service", return_value=_graph_route_service()),
        ):
            resp = authenticated_client.post("/graph/hierarchy/process", json=self._payload)
        assert resp.status_code == 500


# ============================================================================
# 12. POST /graph/hierarchy/search/drill-down
# ============================================================================


@pytest.mark.unit
class TestDrillDownSearch:
    _payload = {"query": "product demo"}

    def test_requires_auth(self, client):
        resp = client.post("/graph/hierarchy/search/drill-down", json=self._payload)
        assert resp.status_code in (401, 403)

    def test_happy_path_without_video_id(self, authenticated_client):
        mock_formatted = MagicMock(results=[], total_results=0, levels_traversed=[])
        with (
            patch(f"{_P}.get_hierarchical_context_service", return_value=_hierarchy_service()),
            patch(f"{_P}.GraphRouteService.format_drill_down_results", return_value=mock_formatted),
        ):
            resp = authenticated_client.post(
                "/graph/hierarchy/search/drill-down", json=self._payload
            )
        assert resp.status_code == 200
        assert resp.json()["query"] == "product demo"

    def test_with_video_id_validates_ownership(self, authenticated_client):
        with patch(
            f"{_P}.get_media_or_404",
            side_effect=HTTPException(status_code=404, detail="Not found"),
        ):
            resp = authenticated_client.post(
                "/graph/hierarchy/search/drill-down",
                json={"query": "q", "video_id": "bad-vid"},
            )
        assert resp.status_code == 404

    def test_service_error_returns_500(self, authenticated_client):
        hsvc = _hierarchy_service()
        hsvc.drill_down_search = AsyncMock(side_effect=RuntimeError("drill fail"))
        with patch(f"{_P}.get_hierarchical_context_service", return_value=hsvc):
            resp = authenticated_client.post(
                "/graph/hierarchy/search/drill-down", json=self._payload
            )
        assert resp.status_code == 500


# ============================================================================
# 13. POST /graph/hierarchy/children
# ============================================================================


@pytest.mark.unit
class TestLoadChildren:
    _payload = {"node_id": "n1", "node_type": "Scene"}

    def test_requires_auth(self, client):
        resp = client.post("/graph/hierarchy/children", json=self._payload)
        assert resp.status_code in (401, 403)

    def test_happy_path(self, authenticated_client):
        mock_paginated = MagicMock(children=[], has_more=False, total_children=0)
        with (
            patch(f"{_P}.get_graph_node_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_hierarchical_context_service", return_value=_hierarchy_service()),
            patch(f"{_P}.GraphRouteService.paginate_children", return_value=mock_paginated),
        ):
            resp = authenticated_client.post("/graph/hierarchy/children", json=self._payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["parent_node_id"] == "n1"
        assert body["has_more"] is False

    def test_node_not_found_returns_404(self, authenticated_client):
        with patch(
            f"{_P}.get_graph_node_media_or_404",
            side_effect=HTTPException(status_code=404, detail="Not found"),
        ):
            resp = authenticated_client.post("/graph/hierarchy/children", json=self._payload)
        assert resp.status_code == 404


# ============================================================================
# 14. GET /graph/hierarchy/stats/{video_id}
# ============================================================================


@pytest.mark.unit
class TestHierarchyStats:
    def test_requires_auth(self, client):
        resp = client.get("/graph/hierarchy/stats/vid-1")
        assert resp.status_code in (401, 403)

    def test_happy_path(self, authenticated_client):
        with (
            patch(f"{_P}.get_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_hierarchical_context_service", return_value=_hierarchy_service()),
        ):
            resp = authenticated_client.get("/graph/hierarchy/stats/vid-1")
        assert resp.status_code == 200
        assert resp.json()["video_id"] == "vid-1"

    def test_hierarchy_not_found_returns_404(self, authenticated_client):
        hsvc = _hierarchy_service()
        hsvc.get_hierarchy_stats = AsyncMock(return_value={"error": "not found"})
        with (
            patch(f"{_P}.get_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_hierarchical_context_service", return_value=hsvc),
        ):
            resp = authenticated_client.get("/graph/hierarchy/stats/vid-1")
        assert resp.status_code == 404

    def test_service_error_returns_500(self, authenticated_client):
        hsvc = _hierarchy_service()
        hsvc.get_hierarchy_stats = AsyncMock(side_effect=RuntimeError("db down"))
        with (
            patch(f"{_P}.get_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_hierarchical_context_service", return_value=hsvc),
        ):
            resp = authenticated_client.get("/graph/hierarchy/stats/vid-1")
        assert resp.status_code == 500


# ============================================================================
# 15. GET /graph/hierarchy/path/{node_id}
# ============================================================================


@pytest.mark.unit
class TestHierarchyPath:
    def test_requires_auth(self, client):
        resp = client.get("/graph/hierarchy/path/n1")
        assert resp.status_code in (401, 403)

    def test_happy_path(self, authenticated_client):
        with (
            patch(f"{_P}.get_graph_node_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_hierarchical_context_service", return_value=_hierarchy_service()),
        ):
            resp = authenticated_client.get("/graph/hierarchy/path/n1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["node_id"] == "n1"
        assert body["depth"] == 0
        assert body["path"] == []

    def test_service_error_returns_500(self, authenticated_client):
        hsvc = _hierarchy_service()
        hsvc.get_hierarchy_path = AsyncMock(side_effect=RuntimeError("path err"))
        with (
            patch(f"{_P}.get_graph_node_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_hierarchical_context_service", return_value=hsvc),
        ):
            resp = authenticated_client.get("/graph/hierarchy/path/n1")
        assert resp.status_code == 500


# ============================================================================
# 16. DELETE /graph/clear?confirm=true  (admin)
# ============================================================================


@pytest.mark.unit
class TestClearAllGraphData:
    def test_requires_auth(self, client):
        resp = client.delete("/graph/clear?confirm=true")
        assert resp.status_code in (401, 403)

    def test_requires_superuser(self, authenticated_client):
        """Regular user gets 403."""
        resp = authenticated_client.delete("/graph/clear?confirm=true")
        assert resp.status_code == 403

    def test_requires_confirm_param(self, app, superuser):
        from api.dependencies import get_current_user

        app.dependency_overrides[get_current_user] = lambda: superuser
        with TestClient(app, raise_server_exceptions=False) as su_client:
            resp = su_client.delete("/graph/clear")
        assert resp.status_code == 400

    def test_happy_path_superuser(self, app, superuser):
        from api.dependencies import get_current_user

        app.dependency_overrides[get_current_user] = lambda: superuser
        with (
            TestClient(app, raise_server_exceptions=False) as su_client,
            patch(f"{_P}.get_async_graph_service", return_value=_async_graph_service()),
        ):
            resp = su_client.delete("/graph/clear?confirm=true")
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    def test_service_error_returns_500(self, app, superuser):
        from api.dependencies import get_current_user

        app.dependency_overrides[get_current_user] = lambda: superuser
        svc = _async_graph_service()
        svc.clear_all = AsyncMock(side_effect=RuntimeError("wipe fail"))
        with (
            TestClient(app, raise_server_exceptions=False) as su_client,
            patch(f"{_P}.get_async_graph_service", return_value=svc),
        ):
            resp = su_client.delete("/graph/clear?confirm=true")
        assert resp.status_code == 500


# ============================================================================
# 17. GET /graph/video/{video_id}/visualization
# ============================================================================


@pytest.mark.unit
class TestVideoVisualization:
    def test_requires_auth(self, client):
        resp = client.get("/graph/video/vid-1/visualization")
        assert resp.status_code in (401, 403)

    def test_happy_path(self, authenticated_client):
        with (
            patch(f"{_P}.get_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_async_graph_service", return_value=_async_graph_service()),
        ):
            resp = authenticated_client.get("/graph/video/vid-1/visualization")
        assert resp.status_code == 200
        body = resp.json()
        assert body["video_id"] == "vid-1"
        assert body["total_nodes"] == 1
        assert body["total_relationships"] == 1

    def test_empty_nodes_returns_404(self, authenticated_client):
        """When get_video_subgraph returns no nodes, should 404."""
        svc = _async_graph_service()
        svc.get_video_subgraph = AsyncMock(return_value={"nodes": [], "relationships": []})
        with (
            patch(f"{_P}.get_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_async_graph_service", return_value=svc),
        ):
            resp = authenticated_client.get("/graph/video/vid-1/visualization")
        assert resp.status_code == 404

    def test_service_error_returns_500(self, authenticated_client):
        svc = _async_graph_service()
        svc.get_video_subgraph = AsyncMock(side_effect=RuntimeError("viz fail"))
        with (
            patch(f"{_P}.get_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_async_graph_service", return_value=svc),
        ):
            resp = authenticated_client.get("/graph/video/vid-1/visualization")
        assert resp.status_code == 500


# ============================================================================
# 18. POST /graph/expand-subgraph
# ============================================================================


@pytest.mark.unit
class TestExpandSubgraph:
    _payload = {"node_id": "n1"}

    def test_requires_auth(self, client):
        resp = client.post("/graph/expand-subgraph", json=self._payload)
        assert resp.status_code in (401, 403)

    def test_happy_path(self, authenticated_client):
        with (
            patch(f"{_P}.get_graph_node_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_async_graph_service", return_value=_async_graph_service()),
        ):
            resp = authenticated_client.post("/graph/expand-subgraph", json=self._payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["center_node_id"] == "n1"
        assert body["total_nodes"] == 1

    def test_node_not_found_returns_404(self, authenticated_client):
        with patch(
            f"{_P}.get_graph_node_media_or_404",
            side_effect=HTTPException(status_code=404, detail="Not found"),
        ):
            resp = authenticated_client.post("/graph/expand-subgraph", json=self._payload)
        assert resp.status_code == 404

    def test_service_error_returns_500(self, authenticated_client):
        svc = _async_graph_service()
        svc.expand_node_subgraph = AsyncMock(side_effect=RuntimeError("expand fail"))
        with (
            patch(f"{_P}.get_graph_node_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_async_graph_service", return_value=svc),
        ):
            resp = authenticated_client.post("/graph/expand-subgraph", json=self._payload)
        assert resp.status_code == 500
