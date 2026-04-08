"""
Tests for Round 4 tenant isolation hardening.

Covers:
- get_stats() user_id scoping
- get_entity_by_name() user_id filtering
- _get_node_by_id() user_id filtering
- expand_node_subgraph() user_id filtering
- Agent query methods (get_video_summary_data, get_nearest_frame, find_entity_appearances)
"""

import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.graph_models import NodeType
from services.graph.agent_queries import AgentQueryMixin
from services.graph.entity_ops import EntityOpsMixin
from services.graph_expander import GraphExpander
from services.graph_search_service import GraphSearchService


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


# -------------------------------------------------------------------
# get_stats() — Phase 1
# -------------------------------------------------------------------


@pytest.mark.unit
def test_get_stats_with_user_id_adds_user_filter():
    """get_stats(user_id=...) should emit user-scoped Cypher queries."""
    session = MagicMock()
    stats_row = {
        "total_nodes": 10,
        "total_relations": 5,
        "total_videos": 2,
        "total_frames": 6,
        "total_entities": 3,
    }
    nodes_rows = [{"label": "Video", "count": 2}, {"label": "Frame", "count": 6}]
    rels_rows = [{"type": "HAS_FRAME", "count": 5}]

    session.run.side_effect = [
        _iterable_result([stats_row]),
        _iterable_result(nodes_rows),
        _iterable_result(rels_rows),
    ]

    expander = GraphExpander(lambda *_args, **_kwargs: [], _session_context(session))
    result = expander.get_stats(user_id="user-1")

    assert result.total_nodes == 10
    assert result.total_videos == 2

    # First call (main stats) must filter by user_id
    main_query = session.run.call_args_list[0].args[0]
    main_params = session.run.call_args_list[0].kwargs
    assert "n.user_id = $user_id" in main_query
    assert main_params["user_id"] == "user-1"


@pytest.mark.unit
def test_get_stats_without_user_id_returns_global():
    """get_stats() with no user_id should NOT filter by user_id (superuser view)."""
    session = MagicMock()
    stats_row = {
        "total_nodes": 100,
        "total_relations": 50,
        "total_videos": 20,
        "total_frames": 60,
        "total_entities": 30,
    }
    session.run.side_effect = [
        _iterable_result([stats_row]),
        _iterable_result([]),
        _iterable_result([]),
    ]

    expander = GraphExpander(lambda *_args, **_kwargs: [], _session_context(session))
    result = expander.get_stats()

    assert result.total_nodes == 100
    main_query = session.run.call_args_list[0].args[0]
    assert "user_id" not in main_query


# -------------------------------------------------------------------
# get_entity_by_name() — Phase 1
# -------------------------------------------------------------------


@pytest.mark.unit
def test_get_entity_by_name_with_user_id_adds_filter():
    """get_entity_by_name(user_id=...) should add user_id WHERE clause."""
    mixin = EntityOpsMixin.__new__(EntityOpsMixin)
    entity_record = {"e": {"id": "e1", "name": "Alice", "user_id": "user-1"}}

    session = MagicMock()
    session.run.return_value = _iterable_result([entity_record])
    mixin._execute_query = MagicMock(return_value={"id": "e1", "name": "Alice"})

    # Call with user_id
    mixin.get_entity_by_name("Alice", user_id="user-1")

    call_args = mixin._execute_query.call_args
    query = call_args.args[0]
    params = call_args.args[1]
    assert "e.user_id = $user_id" in query
    assert params["user_id"] == "user-1"


@pytest.mark.unit
def test_get_entity_by_name_without_user_id_no_filter():
    """get_entity_by_name() without user_id should NOT add user_id filter."""
    mixin = EntityOpsMixin.__new__(EntityOpsMixin)
    mixin._execute_query = MagicMock(return_value=None)

    mixin.get_entity_by_name("Alice")

    query = mixin._execute_query.call_args.args[0]
    assert "user_id" not in query


# -------------------------------------------------------------------
# _get_node_by_id() — Phase 1
# -------------------------------------------------------------------


@pytest.mark.unit
def test_get_node_by_id_with_user_id_adds_filter():
    """_get_node_by_id(user_id=...) should add ownership filter."""
    session = MagicMock()
    session.run.return_value = _iterable_result(
        [{"n": {"id": "n1", "video_id": "vid-1", "user_id": "user-1"}}]
    )

    svc = GraphSearchService.__new__(GraphSearchService)
    svc.graph_service = MagicMock()
    svc.graph_service.get_session = _session_context(session)

    result = svc._get_node_by_id("n1", NodeType.ENTITY, user_id="user-1")

    query = session.run.call_args.args[0]
    params = session.run.call_args.kwargs
    assert "n.user_id = $user_id" in query
    assert params["user_id"] == "user-1"
    assert result["id"] == "n1"


@pytest.mark.unit
def test_get_node_by_id_without_user_id_no_filter():
    """_get_node_by_id() without user_id should not restrict."""
    session = MagicMock()
    session.run.return_value = _iterable_result([{"n": {"id": "n1", "video_id": "vid-1"}}])

    svc = GraphSearchService.__new__(GraphSearchService)
    svc.graph_service = MagicMock()
    svc.graph_service.get_session = _session_context(session)

    svc._get_node_by_id("n1", NodeType.ENTITY)

    query = session.run.call_args.args[0]
    assert "user_id" not in query


# -------------------------------------------------------------------
# expand_node_subgraph() — Phase 2
# -------------------------------------------------------------------


@pytest.mark.unit
def test_expand_node_subgraph_with_user_id_adds_filter():
    """expand_node_subgraph(user_id=...) should filter start node."""
    session = MagicMock()
    session.run.return_value = _iterable_result([])

    expander = GraphExpander(lambda *_args, **_kwargs: [], _session_context(session))
    expander.expand_node_subgraph("node-1", user_id="user-1")

    query = session.run.call_args.args[0]
    params = session.run.call_args.kwargs
    assert "start.user_id = $user_id" in query
    assert params["user_id"] == "user-1"


@pytest.mark.unit
def test_expand_node_subgraph_without_user_id_no_filter():
    """expand_node_subgraph() without user_id should not filter start node."""
    session = MagicMock()
    session.run.return_value = _iterable_result([])

    expander = GraphExpander(lambda *_args, **_kwargs: [], _session_context(session))
    expander.expand_node_subgraph("node-1")

    query = session.run.call_args.args[0]
    assert "user_id" not in query


# -------------------------------------------------------------------
# Agent query methods — Phase 3
# -------------------------------------------------------------------


class _FakeAgentQueryMixin(AgentQueryMixin):
    """Minimal wrapper to test AgentQueriesMixin in isolation."""

    def __init__(self, session):
        self._session = session

    def _execute_query(self, query, params, single=False):
        result = self._session.run(query, **params)
        if single:
            rec = result.single()
            return dict(rec) if rec else None
        return [dict(r) for r in result]

    def _get_session(self):
        return _session_context(self._session)()


@pytest.mark.unit
def test_agent_get_video_summary_data_with_user_id():
    """get_video_summary_data(user_id=...) should add user filter."""
    session = MagicMock()
    session.run.return_value = _iterable_result(
        [{"summary": "A video about cats", "title": "Cats", "topics": ["cats"], "duration": 120}]
    )

    mixin = _FakeAgentQueryMixin(session)
    result = mixin.get_video_summary_data("vid-1", user_id="user-1")

    query = session.run.call_args.args[0]
    params = session.run.call_args.kwargs
    assert "v.user_id = $user_id" in query
    assert params["user_id"] == "user-1"
    assert result["title"] == "Cats"


@pytest.mark.unit
def test_agent_get_video_summary_data_without_user_id():
    """get_video_summary_data() without user_id should NOT filter."""
    session = MagicMock()
    session.run.return_value = _iterable_result(
        [{"summary": "test", "title": "test", "topics": [], "duration": 60}]
    )

    mixin = _FakeAgentQueryMixin(session)
    mixin.get_video_summary_data("vid-1")

    query = session.run.call_args.args[0]
    assert "user_id" not in query


@pytest.mark.unit
def test_agent_get_nearest_frame_with_user_id():
    """get_nearest_frame(user_id=...) should add user filter."""
    session = MagicMock()
    session.run.return_value = _iterable_result(
        [{"timestamp": 10.5, "description": "A sunset scene"}]
    )

    mixin = _FakeAgentQueryMixin(session)
    result = mixin.get_nearest_frame("vid-1", 10.0, user_id="user-1")

    query = session.run.call_args.args[0]
    params = session.run.call_args.kwargs
    assert "f.user_id = $user_id" in query
    assert params["user_id"] == "user-1"
    assert result["timestamp"] == 10.5


@pytest.mark.unit
def test_agent_find_entity_appearances_with_user_id():
    """find_entity_appearances(user_id=...) should filter both visual and audio queries."""
    visual_row = {
        "name": "Alice",
        "entity_type": "person",
        "timestamp": 5.0,
        "description": "Alice appears",
    }
    audio_row = {
        "name": "Alice",
        "start_time": 10.0,
        "end_time": 15.0,
        "text": "Alice speaks",
    }

    session = MagicMock()
    session.run.side_effect = [
        _iterable_result([visual_row]),
        _iterable_result([audio_row]),
    ]

    mixin = _FakeAgentQueryMixin(session)
    result = mixin.find_entity_appearances("vid-1", "Alice", user_id="user-1")

    visual_query = session.run.call_args_list[0].args[0]
    visual_params = session.run.call_args_list[0].kwargs
    audio_query = session.run.call_args_list[1].args[0]
    audio_params = session.run.call_args_list[1].kwargs

    assert "e.user_id = $user_id" in visual_query
    assert visual_params["user_id"] == "user-1"
    assert "a.user_id = $user_id" in audio_query
    assert audio_params["user_id"] == "user-1"

    assert len(result["visual"]) == 1
    assert len(result["audio"]) == 1
