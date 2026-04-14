"""
Focused unit tests for tenant-scoped Neo4j query paths.
"""

import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure backend is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from models.graph_models import NodeType
from services.graph_expander import GraphExpander
from services.graph_search_service import GraphSearchService
from services.knowledge_graph import KnowledgeGraphService


def _iterable_result(rows):
    result = MagicMock()
    result.__iter__ = MagicMock(return_value=iter(rows))
    result.single.return_value = rows[0] if rows else None
    return result


def _session_context(session: MagicMock):
    @contextmanager
    def ctx():
        yield session

    return ctx


@pytest.mark.unit
def test_vector_query_adds_user_filter():
    session = MagicMock()
    session.run.return_value = _iterable_result([])

    svc = GraphSearchService.__new__(GraphSearchService)
    svc.graph_service = MagicMock()
    svc.graph_service.get_session = _session_context(session)

    svc._run_vector_query("entity_embedding", [0.1] * 4, 5, NodeType.ENTITY, user_id="user-1")

    query = session.run.call_args.args[0]
    params = session.run.call_args.kwargs
    assert "node.user_id = $user_id" in query
    assert params["user_id"] == "user-1"


@pytest.mark.unit
def test_fulltext_search_adds_user_filter():
    session = MagicMock()
    session.run.return_value = _iterable_result([])

    svc = GraphSearchService.__new__(GraphSearchService)
    svc.graph_service = MagicMock()
    svc.graph_service.get_session = _session_context(session)

    svc._fulltext_search("alice", NodeType.ENTITY, limit=5, video_id=None, user_id="user-1")

    query = session.run.call_args.args[0]
    params = session.run.call_args.kwargs
    assert "node.user_id = $user_id" in query
    assert params["user_id"] == "user-1"


@pytest.mark.asyncio
async def test_hybrid_search_passes_user_id_through_query_layers():
    svc = GraphSearchService.__new__(GraphSearchService)
    svc.graph_service = MagicMock()
    svc.embedding_service = MagicMock()
    svc.embedding_service.generate_embedding = AsyncMock(return_value=[0.1] * 4)
    svc.vector_search = MagicMock(return_value=[])
    svc._fulltext_search = MagicMock(return_value=[])
    svc._calculate_graph_scores = MagicMock()
    svc.weights = {"vector": 0.5, "fulltext": 0.3, "graph": 0.2}

    await svc.hybrid_search(
        query_text="alice",
        node_types=[NodeType.ENTITY],
        user_id="user-1",
        use_reranking=False,
    )

    assert svc.vector_search.call_args.kwargs["user_id"] == "user-1"
    assert svc._fulltext_search.call_args.kwargs["user_id"] == "user-1"
    svc._calculate_graph_scores.assert_called_once()
    assert svc._calculate_graph_scores.call_args.kwargs["user_id"] == "user-1"


@pytest.mark.unit
def test_merge_fulltext_scores_uses_batch_node_fetch():
    svc = GraphSearchService.__new__(GraphSearchService)
    svc._get_nodes_by_ids = MagicMock(
        return_value={
            "n1": {"id": "n1", "video_id": "vid-1", "timestamp": 5.0},
            "n2": {"id": "n2", "video_id": "vid-1", "start_time": 10.0},
        }
    )
    svc._get_node_by_id = MagicMock(side_effect=AssertionError("should not be used"))

    candidates: list = []
    svc._merge_fulltext_scores(
        candidates,
        [("n1", 0.9), ("n2", 0.8)],
        NodeType.ENTITY,
        video_id="vid-1",
        user_id="user-1",
    )

    svc._get_nodes_by_ids.assert_called_once_with(
        ["n1", "n2"],
        node_type=NodeType.ENTITY,
        video_id="vid-1",
        video_ids=None,
        user_id="user-1",
        timeout_s=None,
    )
    assert [candidate.node_id for candidate in candidates] == ["n1", "n2"]
    assert candidates[0].fulltext_score == 1.0


@pytest.mark.unit
def test_get_nodes_by_ids_uses_unwind_and_user_filter():
    session = MagicMock()
    session.run.return_value = _iterable_result(
        [{"n": {"id": "n1", "video_id": "vid-1", "user_id": "user-1"}}]
    )

    svc = GraphSearchService.__new__(GraphSearchService)
    svc.graph_service = MagicMock()
    svc.graph_service.get_session = _session_context(session)

    nodes = svc._get_nodes_by_ids(
        ["n1"],
        NodeType.ENTITY,
        video_id="vid-1",
        user_id="user-1",
    )

    query = session.run.call_args.args[0]
    params = session.run.call_args.kwargs
    assert "UNWIND $node_ids AS node_id" in query
    assert "n.user_id = $user_id" in query
    assert params["user_id"] == "user-1"
    assert nodes["n1"]["id"] == "n1"


@pytest.mark.unit
def test_calculate_graph_scores_batches_expansion_and_paths():
    expansion_rows = _iterable_result(
        [
            {
                "node_id": "n1",
                "expansions": [
                    {"node": {"id": "e1"}, "distance": 1},
                    {"node": {"id": "e2"}, "distance": 1},
                    {"node": {"id": "e3"}, "distance": 1},
                    {"node": {"id": "e4"}, "distance": 1},
                    {"node": {"id": "e5"}, "distance": 1},
                    {"node": {"id": "e6"}, "distance": 1},
                    {"node": {"id": "e7"}, "distance": 2},
                ],
                "total_related": 7,
            },
            {
                "node_id": "n2",
                "expansions": [{"node": {"id": "x1"}, "distance": 2}],
                "total_related": 1,
            },
        ]
    )
    path_rows = _iterable_result(
        [
            {"node_id": "n1", "path": ["n1", "scene-1", "video-1"]},
            {"node_id": "n2", "path": ["n2", "video-2"]},
        ]
    )

    session = MagicMock()
    session.run.side_effect = [expansion_rows, path_rows]

    svc = GraphSearchService.__new__(GraphSearchService)
    svc.graph_service = MagicMock()
    svc.graph_service.get_session = _session_context(session)

    candidates = [
        type(
            "Candidate",
            (),
            {
                "node_id": "n1",
                "node_type": NodeType.ENTITY,
                "content": {"id": "n1"},
                "vector_score": 0.8,
                "related_nodes": [],
                "path_to_video": [],
                "graph_score": 0.0,
            },
        )(),
        type(
            "Candidate",
            (),
            {
                "node_id": "n2",
                "node_type": NodeType.ENTITY,
                "content": {"id": "n2"},
                "vector_score": 0.7,
                "related_nodes": [],
                "path_to_video": [],
                "graph_score": 0.0,
            },
        )(),
    ]

    svc._calculate_graph_scores(candidates, expansion_hops=2, user_id="user-1")

    assert session.run.call_count == 2
    first_query = session.run.call_args_list[0].args[0]
    second_query = session.run.call_args_list[1].args[0]
    assert "UNWIND $node_ids AS node_id" in first_query
    assert "UNWIND $node_ids AS node_id" in second_query
    assert "all(path_node IN nodes(path) WHERE path_node.user_id = $user_id)" in first_query
    assert "all(path_node IN nodes(path) WHERE path_node.user_id = $user_id)" in second_query

    assert candidates[0].graph_score == pytest.approx((1 + 7) / 50)
    assert len(candidates[0].related_nodes) == 6
    assert candidates[0].path_to_video == ["n1", "scene-1", "video-1"]
    assert candidates[1].path_to_video == ["n2", "video-2"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_find_similar_across_videos_adds_user_filter_without_video_id_list():
    session = MagicMock()
    session.run.side_effect = [
        _iterable_result(
            [{"embedding": [0.1] * 4, "video_id": "vid-1", "label": NodeType.ENTITY.value}]
        ),
        _iterable_result([]),
    ]

    svc = GraphSearchService.__new__(GraphSearchService)
    svc.graph_service = MagicMock()
    svc.graph_service.get_session = _session_context(session)

    results = await svc.find_similar_across_videos("node-1", user_id="user-1")

    assert results == []
    search_query = session.run.call_args_list[1].args[0]
    search_params = session.run.call_args_list[1].kwargs
    assert "node.user_id = $user_id" in search_query
    assert "allowed_video_ids" not in search_params
    assert search_params["user_id"] == "user-1"


@pytest.mark.unit
def test_knowledge_graph_search_entities_adds_user_filter():
    session = MagicMock()
    session.run.return_value = _iterable_result([])

    kg = KnowledgeGraphService.__new__(KnowledgeGraphService)
    kg.get_session = _session_context(session)

    kg.search_entities("alice", video_id="vid-1", user_id="user-1")

    query = session.run.call_args.args[0]
    params = session.run.call_args.kwargs["parameters"]
    assert "node.user_id = $user_id" in query
    assert params["user_id"] == "user-1"
    assert params["video_id"] == "vid-1"


@pytest.mark.unit
def test_knowledge_graph_search_frames_adds_user_filter():
    session = MagicMock()
    session.run.return_value = _iterable_result([])

    kg = KnowledgeGraphService.__new__(KnowledgeGraphService)
    kg.get_session = _session_context(session)

    kg.search_frames_by_description("sunset", user_id="user-1")

    query = session.run.call_args.args[0]
    params = session.run.call_args.kwargs["parameters"]
    assert "node.user_id = $user_id" in query
    assert params["user_id"] == "user-1"


@pytest.mark.unit
def test_expand_context_adds_user_filter_to_start_and_neighbors():
    session = MagicMock()
    session.run.side_effect = [
        _iterable_result([]),
        _iterable_result([{"n": {"id": "node-1"}}]),
    ]

    expander = GraphExpander(lambda *_args, **_kwargs: [], _session_context(session))

    expander.expand_context("node-1", user_id="user-1")

    first_query = session.run.call_args_list[0].args[0]
    first_params = session.run.call_args_list[0].kwargs
    second_query = session.run.call_args_list[1].args[0]
    assert "start.user_id = $user_id" in first_query
    assert "node.user_id = $user_id" in first_query
    assert "all(path_node IN nodes(path) WHERE path_node.user_id = $user_id)" in first_query
    assert first_params["user_id"] == "user-1"
    assert "WHERE n.user_id = $user_id" in second_query


@pytest.mark.unit
def test_related_entities_adds_user_filter():
    queries = []

    def execute_query(cypher, params):
        queries.append((cypher, params))
        return []

    expander = GraphExpander(execute_query, lambda: None)

    expander.get_related_entities("entity-1", user_id="user-1")

    query, params = queries[0]
    assert "user_id: $user_id" in query
    assert "related.user_id = $user_id" in query
    assert params["user_id"] == "user-1"


@pytest.mark.unit
def test_common_entities_and_topics_add_user_filter():
    session = MagicMock()
    session.run.return_value = _iterable_result([])
    expander = GraphExpander(lambda *_args, **_kwargs: [], _session_context(session))

    expander.find_common_entities(["vid-1", "vid-2"], user_id="user-1")
    common_query = session.run.call_args.args[0]
    common_params = session.run.call_args.kwargs
    assert "e.user_id = $user_id" in common_query
    assert common_params["user_id"] == "user-1"

    session.run.reset_mock()
    session.run.return_value = _iterable_result([])

    expander.get_video_topics(["vid-1", "vid-2"], user_id="user-1")
    topics_query = session.run.call_args.args[0]
    topics_params = session.run.call_args.kwargs
    assert "v.user_id = $user_id" in topics_query
    assert topics_params["user_id"] == "user-1"
