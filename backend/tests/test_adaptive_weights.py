"""
Unit tests for adaptive weight profiles and latency instrumentation.

These tests verify that:
1. Intent-based weight selection returns correct profiles
2. Unknown/None intents fall back to defaults
3. All weight profiles sum to 1.0
4. GraphSearchResponse includes new timing fields
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.graph_models import GraphSearchResponse
from services.graph_search_service import GraphSearchService


class TestAdaptiveWeights:
    """Tests for intent-adaptive weight profiles."""

    def setup_method(self):
        """Create a service with mocked dependencies (no Neo4j needed)."""
        from unittest.mock import MagicMock

        self.mock_graph = MagicMock()
        self.mock_embedding = MagicMock()
        self.service = GraphSearchService(
            graph_service=self.mock_graph,
            embedding_service=self.mock_embedding,
        )

    def test_default_weights_sum_to_one(self):
        total = sum(GraphSearchService.DEFAULT_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9

    def test_all_intent_profiles_sum_to_one(self):
        for intent, profile in GraphSearchService.INTENT_WEIGHT_PROFILES.items():
            total = sum(profile.values())
            assert abs(total - 1.0) < 1e-9, f"Profile '{intent}' sums to {total}"

    def test_all_profiles_have_required_keys(self):
        required = {"vector", "fulltext", "graph", "temporal"}
        for intent, profile in GraphSearchService.INTENT_WEIGHT_PROFILES.items():
            assert set(profile.keys()) == required, f"Profile '{intent}' missing keys"

    def test_get_weights_for_none_returns_defaults(self):
        weights = self.service.get_weights_for_intent(None)
        assert weights == self.service.weights

    def test_get_weights_for_unknown_returns_defaults(self):
        weights = self.service.get_weights_for_intent("unknown_intent")
        assert weights == self.service.weights

    def test_get_weights_for_time_based(self):
        weights = self.service.get_weights_for_intent("time-based")
        assert weights["temporal"] > weights["vector"]
        assert weights["temporal"] == 0.40

    def test_get_weights_for_text(self):
        weights = self.service.get_weights_for_intent("text")
        assert weights["fulltext"] > weights["vector"]
        assert weights["fulltext"] == 0.40

    def test_get_weights_for_object_boosts_graph(self):
        weights = self.service.get_weights_for_intent("object")
        assert weights["graph"] > weights["vector"]
        assert weights["graph"] == 0.35

    def test_get_weights_for_person_matches_object(self):
        obj = self.service.get_weights_for_intent("object")
        person = self.service.get_weights_for_intent("person")
        assert obj == person

    def test_get_weights_for_action_boosts_vector(self):
        weights = self.service.get_weights_for_intent("action")
        assert weights["vector"] == 0.40
        assert weights["vector"] > weights["fulltext"]

    def test_get_weights_for_scene(self):
        weights = self.service.get_weights_for_intent("scene")
        assert weights["vector"] == 0.40

    def test_get_weights_for_event_boosts_temporal(self):
        weights = self.service.get_weights_for_intent("event")
        assert weights["temporal"] == 0.25
        assert weights["temporal"] > GraphSearchService.DEFAULT_WEIGHTS["temporal"]

    def test_custom_constructor_weights_used_as_fallback(self):
        custom = {"vector": 0.5, "fulltext": 0.2, "graph": 0.2, "temporal": 0.1}
        svc = GraphSearchService(
            graph_service=self.mock_graph,
            embedding_service=self.mock_embedding,
            weights=custom,
        )
        weights = svc.get_weights_for_intent(None)
        for key in custom:
            assert abs(weights[key] - custom[key]) < 1e-9

        # Known intent still returns profile, not custom
        weights = svc.get_weights_for_intent("time-based")
        assert weights["temporal"] == 0.40

    def test_intent_weights_are_copies(self):
        """Ensure returned weights are copies, not references to class dict."""
        w1 = self.service.get_weights_for_intent("time-based")
        w2 = self.service.get_weights_for_intent("time-based")
        w1["vector"] = 999
        assert w2["vector"] != 999


class TestGraphSearchResponseTimingFields:
    """Tests for new timing fields in GraphSearchResponse."""

    def test_new_timing_fields_have_defaults(self):
        resp = GraphSearchResponse(
            query="test",
            total_results=0,
            results=[],
            search_time_ms=100.0,
            vector_search_time_ms=50.0,
            graph_expansion_time_ms=30.0,
        )
        assert resp.embedding_time_ms == 0.0
        assert resp.fulltext_search_time_ms == 0.0
        assert resp.temporal_scoring_time_ms == 0.0
        assert resp.reranking_time_ms == 0.0

    def test_new_timing_fields_accept_values(self):
        resp = GraphSearchResponse(
            query="test",
            total_results=0,
            results=[],
            search_time_ms=100.0,
            embedding_time_ms=15.0,
            vector_search_time_ms=50.0,
            fulltext_search_time_ms=20.0,
            graph_expansion_time_ms=30.0,
            temporal_scoring_time_ms=5.0,
            reranking_time_ms=10.0,
        )
        assert resp.embedding_time_ms == 15.0
        assert resp.fulltext_search_time_ms == 20.0
        assert resp.temporal_scoring_time_ms == 5.0
        assert resp.reranking_time_ms == 10.0


class TestSearchSettings:
    """Tests for HNSW search configuration."""

    def test_search_settings_defaults(self):
        from core.config import SearchSettings

        cfg = SearchSettings()
        assert cfg.hnsw_m == 16
        assert cfg.hnsw_ef_construction == 256

    def test_search_settings_in_root(self):
        from core.config import Settings

        s = Settings()
        assert hasattr(s, "search")
        assert s.search.hnsw_m == 16
        assert s.search.hnsw_ef_construction == 256
