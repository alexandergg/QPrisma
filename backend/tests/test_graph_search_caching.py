"""
Tests for graph query caching in QPrisma.

Covers:
1. _build_search_cache_key determinism and param sensitivity
2. hybrid_search cache hit / miss / degradation behavior
3. Route-level caching for GET /graph/stats and GET /graph/video/{id}
4. Cache invalidation on DELETE /graph/video/{id}, POST /hierarchy/process,
   POST /embeddings/generate
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from models.graph_models import GraphSearchResponse, GraphStats, NodeType

# Patch target prefix for route-level patches
_P = "api.routes.graph_routes"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _mock_media(video_id="vid-1", user_id="user_test123"):
    m = MagicMock()
    m.id = video_id
    m.user_id = user_id
    return m


def _async_graph_service():
    svc = AsyncMock()
    svc.get_stats = AsyncMock(
        return_value=GraphStats(
            total_nodes=100,
            total_relations=50,
            nodes_by_type={"Frame": 80, "Entity": 20},
            relations_by_type={"CONTAINS": 50},
            total_videos=1,
            total_frames_indexed=10,
            total_entities_extracted=5,
            avg_relations_per_node=0.5,
            max_depth=3,
        )
    )
    svc.delete_video_graph = AsyncMock(return_value=5)
    svc.sync_service = MagicMock()
    return svc


def _graph_route_service():
    svc = MagicMock()
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
    svc.bulk_generate_embeddings = AsyncMock(return_value=10)
    return svc


def _hierarchy_service():
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
    return svc


def _mock_cache():
    """Return a fully wired AsyncMock for CacheService."""
    cache = AsyncMock()
    cache.get_search_result = AsyncMock(return_value=None)
    cache.set_search_result = AsyncMock(return_value=True)
    cache.get_graph_query = AsyncMock(return_value=None)
    cache.set_graph_query = AsyncMock(return_value=True)
    cache.invalidate_video = AsyncMock(return_value=3)
    return cache


def _sample_search_response_dict():
    """A minimal GraphSearchResponse as a JSON-serialisable dict."""
    return {
        "query": "test query",
        "total_results": 1,
        "results": [
            {
                "node_id": "n-1",
                "node_type": "Frame",
                "vector_score": 0.9,
                "graph_score": 0.5,
                "combined_score": 0.8,
                "content": {"description": "A frame"},
                "related_nodes": [],
                "path_to_root": [],
                "highlights": [],
            }
        ],
        "search_time_ms": 42.0,
        "embedding_time_ms": 10.0,
        "vector_search_time_ms": 20.0,
        "fulltext_search_time_ms": 5.0,
        "graph_expansion_time_ms": 4.0,
        "temporal_scoring_time_ms": 2.0,
        "reranking_time_ms": 1.0,
        "facets": {"node_types": {"Frame": 1}},
    }


# =============================================================================
# 1. _build_search_cache_key tests
# =============================================================================


@pytest.mark.unit
class TestBuildSearchCacheKey:
    """Tests for GraphSearchService._build_search_cache_key determinism."""

    _base_params = {
        "query_text": "find the red car",
        "node_types": [NodeType.FRAME, NodeType.ENTITY],
        "video_id": "vid-1",
        "video_ids": None,
        "user_id": "user-123",
        "time_range": None,
        "limit": 20,
        "expansion_hops": 2,
        "use_reranking": True,
        "query_intent": None,
    }

    @staticmethod
    def _build(**kwargs):
        from services.graph_search_service import GraphSearchService

        return GraphSearchService._build_search_cache_key(**kwargs)

    def test_same_params_produce_same_key(self):
        key_a = self._build(**self._base_params)
        key_b = self._build(**self._base_params)
        assert key_a == key_b

    def test_different_query_text_produces_different_key(self):
        params = {**self._base_params, "query_text": "find the blue car"}
        assert self._build(**self._base_params) != self._build(**params)

    def test_different_node_types_produces_different_key(self):
        params = {**self._base_params, "node_types": [NodeType.SCENE]}
        assert self._build(**self._base_params) != self._build(**params)

    def test_different_user_id_produces_different_key(self):
        params = {**self._base_params, "user_id": "user-other"}
        assert self._build(**self._base_params) != self._build(**params)

    def test_node_type_order_does_not_matter(self):
        """node_types are sorted internally, so order shouldn't affect the key."""
        key_a = self._build(
            **{**self._base_params, "node_types": [NodeType.ENTITY, NodeType.FRAME]}
        )
        key_b = self._build(
            **{**self._base_params, "node_types": [NodeType.FRAME, NodeType.ENTITY]}
        )
        assert key_a == key_b

    def test_all_params_affect_key(self):
        """Changing each result-affecting param must change the key."""
        base_key = self._build(**self._base_params)

        mutations = {
            "video_id": "vid-other",
            "video_ids": ["vid-2", "vid-3"],
            "time_range": (10.0, 60.0),
            "limit": 50,
            "expansion_hops": 5,
            "use_reranking": False,
            "query_intent": "object",
        }
        for param, value in mutations.items():
            mutated = {**self._base_params, param: value}
            mutated_key = self._build(**mutated)
            assert (
                mutated_key != base_key
            ), f"Changing '{param}' to {value!r} did not produce a different key"

    def test_key_is_hex_string_of_expected_length(self):
        """Key should be a 32-char hex substring of a SHA256 hash."""
        key = self._build(**self._base_params)
        assert len(key) == 32
        # Should be valid hex
        int(key, 16)


# =============================================================================
# 2. hybrid_search cache behavior tests
# =============================================================================


@pytest.mark.unit
class TestHybridSearchCacheBehavior:
    """Tests for cache integration inside GraphSearchService.hybrid_search."""

    async def test_cache_hit_returns_cached_response_without_embedding(self):
        """On cache HIT, return cached GraphSearchResponse and skip embedding."""
        cached_data = _sample_search_response_dict()
        cache = _mock_cache()
        cache.get_search_result = AsyncMock(return_value=cached_data)

        mock_embedding_svc = AsyncMock()
        mock_graph_svc = MagicMock()

        with patch(
            "services.cache_service.get_cache_service",
            new_callable=AsyncMock,
            return_value=cache,
        ):
            from services.graph_search_service import GraphSearchService

            svc = GraphSearchService.__new__(GraphSearchService)
            svc.graph_service = mock_graph_svc
            svc.embedding_service = mock_embedding_svc
            svc.weights = GraphSearchService.DEFAULT_WEIGHTS

            result = await svc.hybrid_search(
                query_text="test query",
                user_id="user-123",
            )

        assert isinstance(result, GraphSearchResponse)
        assert result.total_results == 1
        assert result.query == "test query"
        # Embedding should NOT have been called
        mock_embedding_svc.generate_embedding.assert_not_called()

    async def test_cache_miss_calls_pipeline_and_stores(self):
        """On cache MISS, full pipeline runs and result is stored in cache."""
        cache = _mock_cache()
        cache.get_search_result = AsyncMock(return_value=None)

        mock_embedding_svc = AsyncMock()
        mock_embedding_svc.generate_embedding = AsyncMock(return_value=[0.1] * 3072)

        mock_graph_svc = MagicMock()
        mock_graph_svc.get_session = MagicMock()

        with (
            patch(
                "services.cache_service.get_cache_service",
                new_callable=AsyncMock,
                return_value=cache,
            ),
            patch(
                "services.graph_search_service.GraphSearchService.vector_search",
                return_value=[],
            ),
            patch(
                "services.graph_search_service.GraphSearchService._fulltext_search",
                return_value=[],
            ),
            patch(
                "services.graph_search_service.GraphSearchService._calculate_graph_scores",
            ),
            patch(
                "services.graph_search_service.GraphSearchService._calculate_temporal_scores",
            ),
        ):
            from services.graph_search_service import GraphSearchService

            svc = GraphSearchService.__new__(GraphSearchService)
            svc.graph_service = mock_graph_svc
            svc.embedding_service = mock_embedding_svc
            svc.weights = GraphSearchService.DEFAULT_WEIGHTS

            result = await svc.hybrid_search(
                query_text="find something",
                user_id="user-123",
            )

        assert isinstance(result, GraphSearchResponse)
        # Embedding was called (cache miss → full pipeline)
        mock_embedding_svc.generate_embedding.assert_called_once_with("find something")
        # Cache store was called
        cache.set_search_result.assert_called_once()

    async def test_cache_unavailable_degrades_gracefully(self):
        """When get_cache_service raises, search still works."""
        mock_embedding_svc = AsyncMock()
        mock_embedding_svc.generate_embedding = AsyncMock(return_value=[0.1] * 3072)

        mock_graph_svc = MagicMock()

        with (
            patch(
                "services.cache_service.get_cache_service",
                new_callable=AsyncMock,
                side_effect=ConnectionError("Cache unavailable"),
            ),
            patch(
                "services.graph_search_service.GraphSearchService.vector_search",
                return_value=[],
            ),
            patch(
                "services.graph_search_service.GraphSearchService._fulltext_search",
                return_value=[],
            ),
            patch(
                "services.graph_search_service.GraphSearchService._calculate_graph_scores",
            ),
            patch(
                "services.graph_search_service.GraphSearchService._calculate_temporal_scores",
            ),
        ):
            from services.graph_search_service import GraphSearchService

            svc = GraphSearchService.__new__(GraphSearchService)
            svc.graph_service = mock_graph_svc
            svc.embedding_service = mock_embedding_svc
            svc.weights = GraphSearchService.DEFAULT_WEIGHTS

            result = await svc.hybrid_search(query_text="test", user_id="u1")

        assert isinstance(result, GraphSearchResponse)
        # Pipeline completed successfully despite cache failure
        mock_embedding_svc.generate_embedding.assert_called_once()

    async def test_cache_store_failure_does_not_break_response(self):
        """set_search_result failure is swallowed; response still returned."""
        cache = _mock_cache()
        cache.get_search_result = AsyncMock(return_value=None)
        cache.set_search_result = AsyncMock(side_effect=RuntimeError("write error"))

        mock_embedding_svc = AsyncMock()
        mock_embedding_svc.generate_embedding = AsyncMock(return_value=[0.1] * 3072)

        with (
            patch(
                "services.cache_service.get_cache_service",
                new_callable=AsyncMock,
                return_value=cache,
            ),
            patch(
                "services.graph_search_service.GraphSearchService.vector_search",
                return_value=[],
            ),
            patch(
                "services.graph_search_service.GraphSearchService._fulltext_search",
                return_value=[],
            ),
            patch(
                "services.graph_search_service.GraphSearchService._calculate_graph_scores",
            ),
            patch(
                "services.graph_search_service.GraphSearchService._calculate_temporal_scores",
            ),
        ):
            from services.graph_search_service import GraphSearchService

            svc = GraphSearchService.__new__(GraphSearchService)
            svc.graph_service = MagicMock()
            svc.embedding_service = mock_embedding_svc
            svc.weights = GraphSearchService.DEFAULT_WEIGHTS

            result = await svc.hybrid_search(query_text="test", user_id="u1")

        # Response is returned despite cache store error
        assert isinstance(result, GraphSearchResponse)

    async def test_different_user_ids_get_different_cache_keys(self):
        """Tenant isolation: different user_ids produce different cache keys."""
        from services.graph_search_service import GraphSearchService

        key_a = GraphSearchService._build_search_cache_key(
            query_text="q",
            node_types=[NodeType.FRAME],
            video_id=None,
            video_ids=None,
            user_id="user-alice",
            time_range=None,
            limit=20,
            expansion_hops=2,
            use_reranking=True,
            query_intent=None,
        )
        key_b = GraphSearchService._build_search_cache_key(
            query_text="q",
            node_types=[NodeType.FRAME],
            video_id=None,
            video_ids=None,
            user_id="user-bob",
            time_range=None,
            limit=20,
            expansion_hops=2,
            use_reranking=True,
            query_intent=None,
        )
        assert key_a != key_b

    async def test_different_limit_produces_different_cache_key(self):
        """Verify limit is included in the cache key."""
        from services.graph_search_service import GraphSearchService

        key_20 = GraphSearchService._build_search_cache_key(
            query_text="q",
            node_types=[NodeType.FRAME],
            video_id=None,
            video_ids=None,
            user_id="u",
            time_range=None,
            limit=20,
            expansion_hops=2,
            use_reranking=True,
            query_intent=None,
        )
        key_50 = GraphSearchService._build_search_cache_key(
            query_text="q",
            node_types=[NodeType.FRAME],
            video_id=None,
            video_ids=None,
            user_id="u",
            time_range=None,
            limit=50,
            expansion_hops=2,
            use_reranking=True,
            query_intent=None,
        )
        assert key_20 != key_50

    async def test_cache_hit_preserves_response_structure(self):
        """Cached dict is faithfully reconstructed as GraphSearchResponse."""
        cached_data = _sample_search_response_dict()
        cache = _mock_cache()
        cache.get_search_result = AsyncMock(return_value=cached_data)

        with patch(
            "services.cache_service.get_cache_service",
            new_callable=AsyncMock,
            return_value=cache,
        ):
            from services.graph_search_service import GraphSearchService

            svc = GraphSearchService.__new__(GraphSearchService)
            svc.graph_service = MagicMock()
            svc.embedding_service = AsyncMock()
            svc.weights = GraphSearchService.DEFAULT_WEIGHTS

            result = await svc.hybrid_search(query_text="test query", user_id="u")

        assert result.results[0].node_id == "n-1"
        assert result.results[0].node_type == NodeType.FRAME
        assert result.search_time_ms == 42.0
        assert result.facets == {"node_types": {"Frame": 1}}


# =============================================================================
# 3. Route caching tests
# =============================================================================

# All route handlers use lazy `from services.cache_service import get_cache_service`
# so we must patch at the source: "services.cache_service.get_cache_service"
_CACHE_SVC = "services.cache_service.get_cache_service"


@pytest.mark.unit
class TestGraphStatsCaching:
    """Tests for GET /graph/stats cache integration."""

    def test_stats_cache_hit_returns_cached(self, authenticated_client):
        """When cache holds stats, return them without calling the graph service."""
        cached_stats = {
            "total_nodes": 200,
            "total_relations": 75,
            "nodes_by_type": {},
            "relations_by_type": {},
            "total_videos": 2,
            "total_frames_indexed": 20,
            "total_entities_extracted": 10,
            "avg_relations_per_node": 0.4,
            "max_depth": 4,
        }
        cache = _mock_cache()
        cache.get_graph_query = AsyncMock(return_value=cached_stats)

        svc = _async_graph_service()

        with (
            patch(f"{_P}.get_async_graph_service", return_value=svc),
            patch(_CACHE_SVC, new_callable=AsyncMock, return_value=cache),
        ):
            resp = authenticated_client.get("/graph/stats")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_nodes"] == 200
        # Graph service should NOT have been called (cache hit)
        svc.get_stats.assert_not_called()

    def test_stats_cache_miss_calls_service_and_stores(self, authenticated_client):
        """On cache miss, fetch stats from service and store in cache."""
        cache = _mock_cache()
        cache.get_graph_query = AsyncMock(return_value=None)

        svc = _async_graph_service()

        with (
            patch(f"{_P}.get_async_graph_service", return_value=svc),
            patch(_CACHE_SVC, new_callable=AsyncMock, return_value=cache),
        ):
            resp = authenticated_client.get("/graph/stats")

        assert resp.status_code == 200
        assert resp.json()["total_nodes"] == 100
        svc.get_stats.assert_called_once()
        # Verify cache was stored with ttl=120
        cache.set_graph_query.assert_called_once()
        call_args = cache.set_graph_query.call_args
        assert call_args.kwargs.get("ttl") == 120 or (
            len(call_args.args) >= 3 and call_args.args[2] == 120
        )

    def test_stats_cache_key_differs_for_superuser(self, app, superuser):
        """Superuser gets 'stats:global' key; regular user gets 'stats:{user_id}'."""
        from api.dependencies import get_current_user

        cache = _mock_cache()
        cache.get_graph_query = AsyncMock(return_value=None)
        svc = _async_graph_service()

        app.dependency_overrides[get_current_user] = lambda: superuser
        with (
            TestClient(app, raise_server_exceptions=False) as su_client,
            patch(f"{_P}.get_async_graph_service", return_value=svc),
            patch(_CACHE_SVC, new_callable=AsyncMock, return_value=cache),
        ):
            su_client.get("/graph/stats")

        # Superuser should use key "stats:global"
        get_call = cache.get_graph_query.call_args
        assert get_call.args[0] == "stats:global"

    def test_stats_cache_unavailable_still_works(self, authenticated_client):
        """If cache service raises, stats endpoint should still return data."""
        svc = _async_graph_service()

        with (
            patch(f"{_P}.get_async_graph_service", return_value=svc),
            patch(
                _CACHE_SVC,
                new_callable=AsyncMock,
                side_effect=ConnectionError("Cache unavailable"),
            ),
        ):
            resp = authenticated_client.get("/graph/stats")

        assert resp.status_code == 200
        assert resp.json()["total_nodes"] == 100


@pytest.mark.unit
class TestVideoGraphCaching:
    """Tests for GET /graph/video/{id} cache integration."""

    def test_video_graph_cache_hit_returns_cached(self, authenticated_client):
        """Cached video graph data is returned without calling route service."""
        cached_result = {
            "video": {"id": "vid-1"},
            "scenes": [{"id": "s1"}],
            "total_scenes": 1,
            "graph_stats": {"nodes": 42},
        }
        cache = _mock_cache()
        cache.get_graph_query = AsyncMock(return_value=cached_result)

        route_svc = _graph_route_service()

        with (
            patch(f"{_P}.get_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_graph_route_service", return_value=route_svc),
            patch(_CACHE_SVC, new_callable=AsyncMock, return_value=cache),
        ):
            resp = authenticated_client.get("/graph/video/vid-1")

        assert resp.status_code == 200
        assert resp.json()["scenes"] == [{"id": "s1"}]
        # Route service NOT called
        route_svc.get_video_graph_data.assert_not_called()

    def test_video_graph_cache_miss_stores_result(self, authenticated_client):
        """On cache miss, compute result and store in cache."""
        cache = _mock_cache()
        cache.get_graph_query = AsyncMock(return_value=None)

        with (
            patch(f"{_P}.get_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_graph_route_service", return_value=_graph_route_service()),
            patch(_CACHE_SVC, new_callable=AsyncMock, return_value=cache),
        ):
            resp = authenticated_client.get("/graph/video/vid-1")

        assert resp.status_code == 200
        cache.set_graph_query.assert_called_once()
        # Verify the key includes video_id and user_id
        stored_key = cache.set_graph_query.call_args.args[0]
        assert "vid-1" in stored_key

    def test_video_graph_cache_key_includes_user_scoping(self, authenticated_client):
        """Non-superuser key: video_graph:{video_id}:{user_id}."""
        cache = _mock_cache()
        cache.get_graph_query = AsyncMock(return_value=None)

        with (
            patch(f"{_P}.get_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_graph_route_service", return_value=_graph_route_service()),
            patch(_CACHE_SVC, new_callable=AsyncMock, return_value=cache),
        ):
            authenticated_client.get("/graph/video/vid-1")

        get_key = cache.get_graph_query.call_args.args[0]
        # test_user is NOT superuser, so user_id is included
        assert get_key == "video_graph:vid-1:user_test123"

    def test_video_graph_superuser_gets_global_key(self, app, superuser):
        """Superuser gets 'video_graph:{vid}:global' key."""
        from api.dependencies import get_current_user

        app.dependency_overrides[get_current_user] = lambda: superuser

        cache = _mock_cache()
        cache.get_graph_query = AsyncMock(return_value=None)

        with (
            TestClient(app, raise_server_exceptions=False) as su_client,
            patch(f"{_P}.get_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_graph_route_service", return_value=_graph_route_service()),
            patch(_CACHE_SVC, new_callable=AsyncMock, return_value=cache),
        ):
            su_client.get("/graph/video/vid-1")

        get_key = cache.get_graph_query.call_args.args[0]
        assert get_key == "video_graph:vid-1:global"


# =============================================================================
# 4. Invalidation tests
# =============================================================================


@pytest.mark.unit
class TestCacheInvalidation:
    """Tests for cache invalidation on mutation endpoints."""

    def test_delete_video_graph_calls_invalidate(self, authenticated_client):
        """DELETE /graph/video/{id} must call invalidate_video after deletion."""
        cache = _mock_cache()
        svc = _async_graph_service()

        with (
            patch(f"{_P}.get_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_async_graph_service", return_value=svc),
            patch(_CACHE_SVC, new_callable=AsyncMock, return_value=cache),
        ):
            resp = authenticated_client.delete("/graph/video/vid-1")

        assert resp.status_code == 200
        assert resp.json()["deleted_nodes"] == 5
        cache.invalidate_video.assert_called_once_with("vid-1")

    def test_hierarchy_process_calls_invalidate(self, authenticated_client):
        """POST /hierarchy/process must invalidate cache for the video_id."""
        cache = _mock_cache()
        payload = {
            "video_path": "/videos/test.mp4",
            "video_id": "vid-1",
            "title": "Test",
            "fps": 30.0,
            "duration": 120.0,
            "resolution": [1920, 1080],
        }

        with (
            patch(f"{_P}.get_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_hierarchical_context_service", return_value=_hierarchy_service()),
            patch(f"{_P}.get_graph_route_service", return_value=_graph_route_service()),
            patch(_CACHE_SVC, new_callable=AsyncMock, return_value=cache),
        ):
            resp = authenticated_client.post("/graph/hierarchy/process", json=payload)

        assert resp.status_code == 200
        cache.invalidate_video.assert_called_once_with("vid-1")

    def test_embeddings_generate_calls_invalidate_with_video_id(self, authenticated_client):
        """POST /embeddings/generate with video_id must invalidate cache."""
        cache = _mock_cache()

        with (
            patch(f"{_P}.get_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_graph_search_service", return_value=_graph_search_service()),
            patch(_CACHE_SVC, new_callable=AsyncMock, return_value=cache),
        ):
            resp = authenticated_client.post(
                "/graph/embeddings/generate",
                json={"node_type": "Scene", "video_id": "vid-1"},
            )

        assert resp.status_code == 200
        cache.invalidate_video.assert_called_once_with("vid-1")

    def test_embeddings_generate_skips_invalidation_without_video_id(self, app, superuser):
        """POST /embeddings/generate WITHOUT video_id must NOT call invalidate."""
        from api.dependencies import get_current_user

        app.dependency_overrides[get_current_user] = lambda: superuser

        cache = _mock_cache()

        with (
            TestClient(app, raise_server_exceptions=False) as su_client,
            patch(f"{_P}.get_graph_search_service", return_value=_graph_search_service()),
            patch(_CACHE_SVC, new_callable=AsyncMock, return_value=cache),
        ):
            resp = su_client.post(
                "/graph/embeddings/generate",
                json={"node_type": "Scene"},
            )

        assert resp.status_code == 200
        cache.invalidate_video.assert_not_called()

    def test_invalidation_failure_does_not_break_delete(self, authenticated_client):
        """If invalidate_video raises, DELETE still returns success."""
        cache = _mock_cache()
        cache.invalidate_video = AsyncMock(side_effect=RuntimeError("Cache exploded"))

        with (
            patch(f"{_P}.get_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_async_graph_service", return_value=_async_graph_service()),
            patch(_CACHE_SVC, new_callable=AsyncMock, return_value=cache),
        ):
            resp = authenticated_client.delete("/graph/video/vid-1")

        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    def test_invalidation_failure_does_not_break_hierarchy_process(self, authenticated_client):
        """If invalidate_video raises during hierarchy process, response is still OK."""
        cache = _mock_cache()
        cache.invalidate_video = AsyncMock(side_effect=RuntimeError("Cache gone"))

        payload = {
            "video_path": "/videos/test.mp4",
            "video_id": "vid-1",
            "title": "Test",
            "fps": 30.0,
            "duration": 120.0,
            "resolution": [1920, 1080],
        }

        with (
            patch(f"{_P}.get_media_or_404", return_value=_mock_media()),
            patch(f"{_P}.get_hierarchical_context_service", return_value=_hierarchy_service()),
            patch(f"{_P}.get_graph_route_service", return_value=_graph_route_service()),
            patch(_CACHE_SVC, new_callable=AsyncMock, return_value=cache),
        ):
            resp = authenticated_client.post("/graph/hierarchy/process", json=payload)

        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"
