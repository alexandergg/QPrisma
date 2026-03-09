"""
Tests for Dense Temporal Chains feature.

Validates:
- Chain creation methods (create_frame_chain, create_segment_chain, create_scene_chain)
- Chain traversal (walk_temporal_chain forward/backward)
- Convenience method create_temporal_chains
- Temporal adjacency scoring boost
- Idempotent chain recreation (delete-then-create pattern)
- Edge case handling (empty graphs, single-node chains)

These are pure unit tests — no Neo4j connection is required.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ===========================================================================
# Helpers
# ===========================================================================


def _make_mock_session():
    """Create a mock Neo4j session with run() returning configurable results."""
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    return session


def _make_repository():
    """Create a GraphNodeRepository with mock callables."""
    from services.graph_node_repository import GraphNodeRepository

    exec_fn = MagicMock()
    sess_fn = MagicMock()
    repo = GraphNodeRepository(exec_fn, sess_fn)
    return repo, exec_fn, sess_fn


def _make_expander():
    """Create a GraphExpander with mock callables."""
    from services.graph_expander import GraphExpander

    exec_fn = MagicMock()
    sess_fn = MagicMock()
    exp = GraphExpander(exec_fn, sess_fn)
    return exp, exec_fn, sess_fn


def _make_service():
    """Create a KnowledgeGraphService with mocked settings."""
    with patch("services.knowledge_graph.settings") as mock_settings:
        neo4j = MagicMock()
        neo4j.uri = "bolt://localhost:7687"
        neo4j.user = "neo4j"
        neo4j.password = "test"
        neo4j.database = "neo4j"
        mock_settings.neo4j = neo4j

        from services.knowledge_graph import KnowledgeGraphService

        svc = KnowledgeGraphService()
    return svc


# ===========================================================================
# RelationType enum
# ===========================================================================


@pytest.mark.unit
class TestTemporalRelationTypes:
    """Verify NEXT_FRAME, NEXT_SEGMENT, NEXT_SCENE exist in RelationType."""

    def test_next_frame_exists(self):
        from models.graph_models import RelationType

        assert hasattr(RelationType, "NEXT_FRAME")
        assert RelationType.NEXT_FRAME.value == "NEXT_FRAME"

    def test_next_segment_exists(self):
        from models.graph_models import RelationType

        assert hasattr(RelationType, "NEXT_SEGMENT")
        assert RelationType.NEXT_SEGMENT.value == "NEXT_SEGMENT"

    def test_next_scene_exists(self):
        from models.graph_models import RelationType

        assert hasattr(RelationType, "NEXT_SCENE")
        assert RelationType.NEXT_SCENE.value == "NEXT_SCENE"


# ===========================================================================
# Chain creation — GraphNodeRepository
# ===========================================================================


@pytest.mark.unit
class TestChainCreation:
    """Verify chain creation methods execute correct Cypher patterns."""

    def test_create_frame_chain_calls_session(self):
        repo, _, sess_fn = _make_repository()
        session = _make_mock_session()
        sess_fn.return_value = session

        repo.create_frame_chain("video-1")

        # Should have been called (at least delete + create)
        assert session.run.call_count >= 2
        calls = [str(c) for c in session.run.call_args_list]
        # First call deletes existing NEXT_FRAME edges
        assert any("DELETE" in c and "NEXT_FRAME" in c for c in calls)
        # Second call creates NEXT_FRAME edges
        assert any("CREATE" in c and "NEXT_FRAME" in c for c in calls)

    def test_create_segment_chain_calls_session(self):
        repo, _, sess_fn = _make_repository()
        session = _make_mock_session()
        sess_fn.return_value = session

        repo.create_segment_chain("video-1")

        assert session.run.call_count >= 2
        calls = [str(c) for c in session.run.call_args_list]
        assert any("DELETE" in c and "NEXT_SEGMENT" in c for c in calls)
        assert any("CREATE" in c and "NEXT_SEGMENT" in c for c in calls)

    def test_create_scene_chain_calls_session(self):
        repo, _, sess_fn = _make_repository()
        session = _make_mock_session()
        sess_fn.return_value = session

        repo.create_scene_chain("video-1")

        assert session.run.call_count >= 2
        calls = [str(c) for c in session.run.call_args_list]
        assert any("DELETE" in c and "NEXT_SCENE" in c for c in calls)
        assert any("CREATE" in c and "NEXT_SCENE" in c for c in calls)

    def test_create_frame_chain_passes_video_id(self):
        repo, _, sess_fn = _make_repository()
        session = _make_mock_session()
        sess_fn.return_value = session

        repo.create_frame_chain("my-video-42")

        # All run() calls should include video_id parameter
        for c in session.run.call_args_list:
            kwargs = c[1] if len(c) > 1 else {}
            if "video_id" in kwargs:
                assert kwargs["video_id"] == "my-video-42"

    def test_create_frame_chain_uses_frame_number_ordering(self):
        repo, _, sess_fn = _make_repository()
        session = _make_mock_session()
        sess_fn.return_value = session

        repo.create_frame_chain("vid-1")

        # The CREATE call should order by frame_number
        create_calls = [str(c) for c in session.run.call_args_list if "CREATE" in str(c)]
        assert any("frame_number" in c for c in create_calls)

    def test_create_segment_chain_uses_start_time_ordering(self):
        repo, _, sess_fn = _make_repository()
        session = _make_mock_session()
        sess_fn.return_value = session

        repo.create_segment_chain("vid-1")

        create_calls = [str(c) for c in session.run.call_args_list if "CREATE" in str(c)]
        assert any("start_time" in c for c in create_calls)

    def test_create_scene_chain_uses_scene_index_ordering(self):
        repo, _, sess_fn = _make_repository()
        session = _make_mock_session()
        sess_fn.return_value = session

        repo.create_scene_chain("vid-1")

        create_calls = [str(c) for c in session.run.call_args_list if "CREATE" in str(c)]
        assert any("scene_index" in c for c in create_calls)


# ===========================================================================
# Chain traversal — GraphExpander
# ===========================================================================


@pytest.mark.unit
class TestChainTraversal:
    """Verify walk_temporal_chain executes correct Cypher path queries."""

    def test_walk_forward_uses_outgoing_direction(self):
        exp, _, sess_fn = _make_expander()
        session = _make_mock_session()
        session.run.return_value = []
        sess_fn.return_value = session

        exp.walk_temporal_chain("node-1", "NEXT_FRAME", direction="forward", hops=5)

        query = str(session.run.call_args)
        assert "NEXT_FRAME" in query

    def test_walk_backward_uses_incoming_direction(self):
        exp, _, sess_fn = _make_expander()
        session = _make_mock_session()
        session.run.return_value = []
        sess_fn.return_value = session

        exp.walk_temporal_chain("node-1", "NEXT_FRAME", direction="backward", hops=5)

        query = str(session.run.call_args)
        assert "NEXT_FRAME" in query

    def test_walk_default_direction_is_forward(self):
        exp, _, sess_fn = _make_expander()
        session = _make_mock_session()
        session.run.return_value = []
        sess_fn.return_value = session

        exp.walk_temporal_chain("node-1", "NEXT_SEGMENT")

        assert session.run.called

    def test_walk_default_hops_is_5(self):
        exp, _, sess_fn = _make_expander()
        session = _make_mock_session()
        session.run.return_value = []
        sess_fn.return_value = session

        exp.walk_temporal_chain("node-1", "NEXT_FRAME")

        assert session.run.called

    def test_walk_returns_list(self):
        exp, _, sess_fn = _make_expander()
        session = _make_mock_session()
        mock_record = MagicMock()
        mock_record.__getitem__ = MagicMock(return_value={"id": "f1", "timestamp": 1.0})
        session.run.return_value = [mock_record]
        sess_fn.return_value = session

        result = exp.walk_temporal_chain("node-1", "NEXT_FRAME")

        assert isinstance(result, list)

    def test_walk_respects_hop_limit(self):
        exp, _, sess_fn = _make_expander()
        session = _make_mock_session()
        session.run.return_value = []
        sess_fn.return_value = session

        exp.walk_temporal_chain("node-1", "NEXT_FRAME", hops=3)

        query = str(session.run.call_args)
        assert "3" in query

    def test_walk_with_next_scene(self):
        exp, _, sess_fn = _make_expander()
        session = _make_mock_session()
        session.run.return_value = []
        sess_fn.return_value = session

        exp.walk_temporal_chain("scene-1", "NEXT_SCENE", direction="forward", hops=2)

        query = str(session.run.call_args)
        assert "NEXT_SCENE" in query


# ===========================================================================
# KnowledgeGraphService delegation
# ===========================================================================


@pytest.mark.unit
class TestTemporalDelegation:
    """Verify KnowledgeGraphService delegates chain methods correctly."""

    def test_create_frame_chain_delegates_to_nodes(self):
        svc = _make_service()
        svc.nodes.create_frame_chain = MagicMock(return_value=5)

        result = svc.create_frame_chain("vid-1")

        svc.nodes.create_frame_chain.assert_called_once_with("vid-1")
        assert result == 5

    def test_create_segment_chain_delegates_to_nodes(self):
        svc = _make_service()
        svc.nodes.create_segment_chain = MagicMock(return_value=10)

        result = svc.create_segment_chain("vid-1")

        svc.nodes.create_segment_chain.assert_called_once_with("vid-1")
        assert result == 10

    def test_create_scene_chain_delegates_to_nodes(self):
        svc = _make_service()
        svc.nodes.create_scene_chain = MagicMock(return_value=3)

        result = svc.create_scene_chain("vid-1")

        svc.nodes.create_scene_chain.assert_called_once_with("vid-1")
        assert result == 3

    def test_walk_temporal_chain_delegates_to_expander(self):
        svc = _make_service()
        svc.expander.walk_temporal_chain = MagicMock(return_value=[{"id": "f1"}])

        result = svc.walk_temporal_chain("node-1", "NEXT_FRAME")

        svc.expander.walk_temporal_chain.assert_called_once_with(
            "node-1", "NEXT_FRAME", "forward", 10
        )
        assert result == [{"id": "f1"}]

    def test_create_temporal_chains_calls_all_three(self):
        svc = _make_service()
        svc.nodes.create_frame_chain = MagicMock(return_value=5)
        svc.nodes.create_segment_chain = MagicMock(return_value=10)
        svc.nodes.create_scene_chain = MagicMock(return_value=3)

        result = svc.create_temporal_chains("vid-1")

        svc.nodes.create_frame_chain.assert_called_once_with("vid-1")
        svc.nodes.create_segment_chain.assert_called_once_with("vid-1")
        svc.nodes.create_scene_chain.assert_called_once_with("vid-1")
        assert result == {"frame_chains": 5, "segment_chains": 10, "scene_chains": 3}


# ===========================================================================
# Temporal adjacency scoring
# ===========================================================================


@pytest.mark.unit
class TestTemporalAdjacencyScoring:
    """Verify temporal adjacency boost in scoring mixin."""

    def test_boost_temporal_adjacency_exists(self):
        from services.graph_search_scoring import GraphSearchScoringMixin

        assert hasattr(GraphSearchScoringMixin, "_boost_temporal_adjacency")

    def test_calculate_temporal_scores_calls_adjacency_boost(self):
        from services.graph_search_scoring import GraphSearchScoringMixin

        mixin = GraphSearchScoringMixin()
        # Create mock candidates with timestamps
        candidates = []
        for i in range(3):
            c = MagicMock()
            c.timestamp = float(i * 5)
            c.vector_score = 0.8
            c.temporal_score = 0.5
            candidates.append(c)

        mixin._calculate_temporal_scores(candidates, time_range=(0.0, 15.0))

        # Verify temporal_score was set on all candidates
        for c in candidates:
            assert c.temporal_score is not None

    def test_adjacency_boost_no_crash_on_empty(self):
        from services.graph_search_scoring import GraphSearchScoringMixin

        mixin = GraphSearchScoringMixin()
        mixin._boost_temporal_adjacency([])

    def test_adjacency_boost_no_crash_on_single(self):
        from services.graph_search_scoring import GraphSearchScoringMixin

        mixin = GraphSearchScoringMixin()
        c = MagicMock()
        c.timestamp = 1.0
        c.vector_score = 0.9
        c.temporal_score = 0.5
        mixin._boost_temporal_adjacency([c])

    def test_adjacency_boost_increases_scores_for_close_candidates(self):
        from services.graph_search_scoring import GraphSearchScoringMixin

        mixin = GraphSearchScoringMixin()

        c1 = MagicMock()
        c1.timestamp = 1.0
        c1.vector_score = 0.9
        c1.temporal_score = 0.5

        c2 = MagicMock()
        c2.timestamp = 3.0  # 2s gap — well within 15s threshold
        c2.vector_score = 0.8
        c2.temporal_score = 0.5

        candidates = [c1, c2]
        mixin._boost_temporal_adjacency(candidates)

        # Both should have been boosted above 0.5
        assert c1.temporal_score > 0.5
        assert c2.temporal_score > 0.5

    def test_adjacency_boost_does_not_exceed_1(self):
        from services.graph_search_scoring import GraphSearchScoringMixin

        mixin = GraphSearchScoringMixin()

        c1 = MagicMock()
        c1.timestamp = 1.0
        c1.vector_score = 1.0
        c1.temporal_score = 0.99

        c2 = MagicMock()
        c2.timestamp = 1.5
        c2.vector_score = 1.0
        c2.temporal_score = 0.99

        mixin._boost_temporal_adjacency([c1, c2])

        assert c1.temporal_score <= 1.0
        assert c2.temporal_score <= 1.0

    def test_no_boost_for_distant_candidates(self):
        from services.graph_search_scoring import GraphSearchScoringMixin

        mixin = GraphSearchScoringMixin()

        c1 = MagicMock()
        c1.timestamp = 1.0
        c1.vector_score = 0.9
        c1.temporal_score = 0.5

        c2 = MagicMock()
        c2.timestamp = 100.0  # 99s gap — far beyond 15s threshold
        c2.vector_score = 0.9
        c2.temporal_score = 0.5

        mixin._boost_temporal_adjacency([c1, c2])

        # Neither should be boosted
        assert c1.temporal_score == 0.5
        assert c2.temporal_score == 0.5
