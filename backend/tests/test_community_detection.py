"""
Tests for the CommunityDetectionService.

Validates:
- Entity co-occurrence graph construction from mock Neo4j data
- Community detection via Louvain algorithm
- Summary generation with mocked LLM
- Full pipeline orchestration
- Edge cases (empty graphs, single entities, disconnected components)

These are pure unit tests — no Neo4j or Azure OpenAI connection required.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mock_settings():
    """Return a mock settings object with community + azure sections."""
    s = MagicMock()
    s.community.algorithm = "louvain"
    s.community.resolution = 1.0
    s.community.min_community_size = 2
    s.community.min_entity_occurrences = 2
    s.community.max_communities_per_video = 20
    s.community.summary_max_tokens = 300
    s.community.enabled = True
    s.azure.openai_endpoint = "https://test.openai.azure.com/"
    s.azure.openai_api_key = "test-key"
    s.azure.openai_api_version = "2024-02-15-preview"
    s.azure.openai_deployment = "gpt-4o"
    s.azure.openai_deployment_gpt = "gpt-4o"
    return s


def _make_service():
    """Create a CommunityDetectionService with mocked dependencies."""
    with patch("services.community_detection_service.settings", _mock_settings()):
        from services.community_detection_service import CommunityDetectionService

        svc = CommunityDetectionService()
    return svc


def _mock_neo4j_session(entity_rows, cooccurrence_rows):
    """Build a mock session context manager that returns given rows."""
    mock_session = MagicMock()

    def _make_record(row):
        rec = MagicMock()
        rec.__getitem__ = lambda self, key, r=row: r[key]
        rec.get = lambda key, default=None, r=row: r.get(key, default)
        return rec

    entity_records = [_make_record(r) for r in entity_rows]
    cooccurrence_records = [_make_record(r) for r in cooccurrence_rows]
    mock_session.run.side_effect = [entity_records, cooccurrence_records]

    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_session)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


# ===========================================================================
# Graph construction
# ===========================================================================


@pytest.mark.unit
class TestBuildEntityGraph:
    """Test entity co-occurrence graph construction."""

    def test_builds_graph_from_cooccurrences(self):
        svc = _make_service()

        entities = [
            {
                "id": "e1",
                "name": "Alice",
                "normalized_name": "alice",
                "entity_type": "PERSON",
                "description": "Person",
                "occurrence_count": 3,
                "first_seen_time": 0.0,
                "last_seen_time": 10.0,
            },
            {
                "id": "e2",
                "name": "Bob",
                "normalized_name": "bob",
                "entity_type": "PERSON",
                "description": "Person",
                "occurrence_count": 2,
                "first_seen_time": 1.0,
                "last_seen_time": 8.0,
            },
            {
                "id": "e3",
                "name": "Car",
                "normalized_name": "car",
                "entity_type": "OBJECT",
                "description": "Object",
                "occurrence_count": 4,
                "first_seen_time": 2.0,
                "last_seen_time": 12.0,
            },
        ]
        cooccurrences = [
            {"source": "e1", "target": "e2", "weight": 5},
            {"source": "e2", "target": "e3", "weight": 3},
        ]

        ctx = _mock_neo4j_session(entities, cooccurrences)

        mock_kg = MagicMock()
        mock_kg.get_session.return_value = ctx
        svc._graph_service = mock_kg

        with patch("services.community_detection_service.settings", _mock_settings()):
            G = svc.build_entity_graph("vid-1")

        assert len(G.nodes) == 3
        assert len(G.edges) == 2
        assert G["e1"]["e2"]["weight"] == 5

    def test_empty_video_returns_empty_graph(self):
        svc = _make_service()

        ctx = _mock_neo4j_session([], [])

        mock_kg = MagicMock()
        mock_kg.get_session.return_value = ctx
        svc._graph_service = mock_kg

        with patch("services.community_detection_service.settings", _mock_settings()):
            G = svc.build_entity_graph("vid-empty")

        assert len(G.nodes) == 0
        assert len(G.edges) == 0


# ===========================================================================
# Community detection
# ===========================================================================


@pytest.mark.unit
class TestDetectCommunities:
    """Test Louvain community detection."""

    def test_detects_two_communities(self):
        import networkx as nx

        svc = _make_service()

        # Two dense groups with weak inter-connection
        G = nx.Graph()
        G.add_edge("A", "B", weight=10)
        G.add_edge("A", "C", weight=10)
        G.add_edge("B", "C", weight=10)
        G.add_edge("D", "E", weight=10)
        G.add_edge("D", "F", weight=10)
        G.add_edge("E", "F", weight=10)
        G.add_edge("C", "D", weight=1)  # Weak bridge

        with patch("services.community_detection_service.settings", _mock_settings()):
            communities = svc.detect_communities(G)

        # Returns list[set[str]] — should detect at least 2
        assert len(communities) >= 2
        all_members = set()
        for members in communities:
            all_members.update(members)
        assert all_members == {"A", "B", "C", "D", "E", "F"}

    def test_single_clique_returns_one_community(self):
        import networkx as nx

        svc = _make_service()

        G = nx.Graph()
        G.add_edge("X", "Y", weight=5)
        G.add_edge("Y", "Z", weight=5)
        G.add_edge("X", "Z", weight=5)

        with patch("services.community_detection_service.settings", _mock_settings()):
            communities = svc.detect_communities(G)

        assert len(communities) == 1
        assert set(communities[0]) == {"X", "Y", "Z"}

    def test_empty_graph_returns_no_communities(self):
        import networkx as nx

        svc = _make_service()
        G = nx.Graph()

        with patch("services.community_detection_service.settings", _mock_settings()):
            communities = svc.detect_communities(G)

        assert len(communities) == 0

    def test_filters_small_communities(self):
        import networkx as nx

        svc = _make_service()

        G = nx.Graph()
        G.add_edge("A", "B", weight=10)
        G.add_edge("A", "C", weight=10)
        G.add_edge("B", "C", weight=10)
        G.add_node("Loner")

        with patch("services.community_detection_service.settings", _mock_settings()):
            communities = svc.detect_communities(G)

        for members in communities:
            assert len(members) >= 2


# ===========================================================================
# Summary generation
# ===========================================================================


@pytest.mark.unit
class TestGenerateSummaries:
    """Test LLM summary generation for communities."""

    def test_generates_summary_for_community(self):
        import networkx as nx

        svc = _make_service()

        G = nx.Graph()
        G.add_node(
            "e1",
            name="Alice",
            entity_type="PERSON",
            description="Main character",
            first_seen_time=0.0,
            last_seen_time=10.0,
        )
        G.add_node(
            "e2",
            name="Bob",
            entity_type="PERSON",
            description="Supporting character",
            first_seen_time=1.0,
            last_seen_time=8.0,
        )
        G.add_edge("e1", "e2", weight=5)

        communities = [{"e1", "e2"}]

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = (
            '{"title": "Main Characters",'
            ' "summary": "A group about main characters.",'
            ' "themes": ["characters"]}'
        )

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        svc._openai_client = mock_client

        mock_kg = MagicMock()
        frame_session = MagicMock()
        frame_session.run.return_value = []
        frame_ctx = MagicMock()
        frame_ctx.__enter__ = MagicMock(return_value=frame_session)
        frame_ctx.__exit__ = MagicMock(return_value=False)
        mock_kg.get_session.return_value = frame_ctx
        svc._graph_service = mock_kg

        with patch("services.community_detection_service.settings", _mock_settings()):
            result = svc.generate_community_summaries(G, communities, "vid-1")

        assert len(result) == 1
        assert result[0].title == "Main Characters"
        assert "characters" in result[0].themes


# ===========================================================================
# Pipeline orchestration
# ===========================================================================


@pytest.mark.unit
class TestRunPipeline:
    """Test full pipeline orchestration."""

    def test_pipeline_skips_when_no_entities(self):
        svc = _make_service()

        ctx = _mock_neo4j_session([], [])

        mock_kg = MagicMock()
        mock_kg.get_session.return_value = ctx
        mock_kg.is_connected = True
        svc._graph_service = mock_kg

        with patch("services.community_detection_service.settings", _mock_settings()):
            result = svc.run_pipeline("vid-empty")

        assert result == []

    def test_pipeline_returns_community_nodes(self):
        import networkx as nx

        svc = _make_service()

        G = nx.Graph()
        G.add_node(
            "ea",
            name="A",
            entity_type="THING",
            description="Entity A",
            normalized_name="a",
            occurrence_count=3,
            first_seen_time=0.0,
            last_seen_time=10.0,
        )
        G.add_node(
            "eb",
            name="B",
            entity_type="THING",
            description="Entity B",
            normalized_name="b",
            occurrence_count=3,
            first_seen_time=1.0,
            last_seen_time=8.0,
        )
        G.add_node(
            "ec",
            name="C",
            entity_type="THING",
            description="Entity C",
            normalized_name="c",
            occurrence_count=3,
            first_seen_time=2.0,
            last_seen_time=12.0,
        )
        G.add_edge("ea", "eb", weight=5)
        G.add_edge("eb", "ec", weight=5)
        G.add_edge("ea", "ec", weight=5)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = (
            '{"title": "Test Community",' ' "summary": "A test community.",' ' "themes": ["test"]}'
        )

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        mock_kg = MagicMock()
        mock_kg.is_connected = True
        mock_kg.delete_video_communities.return_value = 0
        mock_kg.create_communities_batch.return_value = 1
        mock_kg.link_entities_to_community.return_value = None
        frame_session = MagicMock()
        frame_session.run.return_value = []
        frame_ctx = MagicMock()
        frame_ctx.__enter__ = MagicMock(return_value=frame_session)
        frame_ctx.__exit__ = MagicMock(return_value=False)
        mock_kg.get_session.return_value = frame_ctx

        svc._graph_service = mock_kg
        svc._openai_client = mock_client
        svc._embedding_service = MagicMock()
        svc._embedding_service.generate_embedding.return_value = [0.1] * 3072

        with (
            patch.object(svc, "build_entity_graph", return_value=G),
            patch("services.community_detection_service.settings", _mock_settings()),
        ):
            result = svc.run_pipeline("vid-1")

        assert len(result) == 1
        assert result[0].title == "Test Community"


# ===========================================================================
# Singleton accessor
# ===========================================================================


@pytest.mark.unit
class TestSingleton:
    """Test get_community_detection_service returns singleton."""

    def test_returns_service_instance(self):
        with patch("services.community_detection_service.settings", _mock_settings()):
            import services.community_detection_service as mod
            from services.community_detection_service import (
                CommunityDetectionService,
                get_community_detection_service,
            )

            mod._community_detection_service = None

            svc = get_community_detection_service()
            assert isinstance(svc, CommunityDetectionService)

            svc2 = get_community_detection_service()
            assert svc is svc2

            mod._community_detection_service = None
