"""
Targeted unit tests for GraphNodeRepository graph-scoping behavior.

These tests verify that Entity and Topic nodes are merged per-video and
that cross-video linking/deletion stays safely scoped by tenant/video.
"""

import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.graph_models import EntityNode, EntityType, TopicNode
from services.graph_expander import GraphExpander
from services.graph_node_repository import GraphNodeRepository


def _make_mock_session(single_result: dict | None = None) -> MagicMock:
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    result = MagicMock()
    result.single.return_value = single_result or {}
    session.run.return_value = result
    return session


def _make_repository() -> tuple[GraphNodeRepository, MagicMock]:
    exec_fn = MagicMock()
    sess_fn = MagicMock()
    repo = GraphNodeRepository(exec_fn, sess_fn)
    return repo, sess_fn


@pytest.mark.unit
class TestGraphNodeRepositoryScoping:
    def test_create_entity_node_merges_by_video_id(self):
        repo, sess_fn = _make_repository()
        session = _make_mock_session({"id": "entity-1"})
        sess_fn.return_value = session

        entity = EntityNode(
            name="Alice",
            normalized_name="alice",
            entity_type=EntityType.PERSON,
            user_id="user-1",
            description="Presenter",
            confidence=0.9,
        )
        entity.created_at = datetime.now(UTC)

        result = repo.create_entity_node(entity, "frame-1")

        query = session.run.call_args.args[0]
        assert "video_id: f.video_id" in query
        assert "entity_type: $entity_type" in query
        assert result == "entity-1"

    def test_create_entities_batch_merges_by_video_id(self):
        repo, sess_fn = _make_repository()
        session = _make_mock_session({"created": 2})
        sess_fn.return_value = session

        entities = [
            (
                EntityNode(
                    name="Alice",
                    normalized_name="alice",
                    entity_type=EntityType.PERSON,
                    user_id="user-1",
                ),
                "frame-1",
            ),
            (
                EntityNode(
                    name="Product",
                    normalized_name="product",
                    entity_type=EntityType.OBJECT,
                    user_id="user-1",
                ),
                "frame-2",
            ),
        ]

        created = repo.create_entities_batch(entities)

        query = session.run.call_args.args[0]
        assert "video_id: f.video_id" in query
        assert created == 2

    def test_create_topic_nodes_batch_merges_by_video_id(self):
        repo, sess_fn = _make_repository()
        session = _make_mock_session({"created": 1})
        sess_fn.return_value = session

        topics = [
            TopicNode(
                name="Artificial Intelligence",
                normalized_name="artificial intelligence",
                user_id="user-1",
                keywords=["ai", "ml"],
            )
        ]

        created = repo.create_topic_nodes_batch(topics, "video-1")

        query = session.run.call_args.args[0]
        assert query.index("MATCH (v:Video {video_id: $video_id})") < query.index(
            "UNWIND $topics AS topic"
        )
        assert (
            "MERGE (t:Topic {normalized_name: topic.normalized_name, video_id: $video_id})" in query
        )
        assert session.run.call_args.kwargs["video_id"] == "video-1"
        assert created == 1

    def test_resolve_cross_video_entities_scopes_to_same_user(self):
        repo, sess_fn = _make_repository()
        session = _make_mock_session({"linked": 3})
        sess_fn.return_value = session

        linked = repo.resolve_cross_video_entities("video-1")

        query = session.run.call_args.args[0]
        assert "MATCH (e1:Entity {video_id: $video_id})" in query
        assert "AND e2.user_id = e1.user_id" in query
        assert linked == 3


@pytest.mark.unit
def test_delete_video_graph_deletes_topics_by_video_id():
    exec_fn = MagicMock(side_effect=[{"deleted": 1}] * 8)
    expander = GraphExpander(exec_fn, MagicMock())

    deleted = expander.delete_video_graph("video-1")

    queries = [call.args[0] for call in exec_fn.call_args_list]
    assert any(
        "MATCH (n:Topic)" in query and "WHERE n.video_id = $video_id" in query for query in queries
    )
    assert deleted == 8
