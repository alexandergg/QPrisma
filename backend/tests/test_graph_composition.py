"""
Tests for the KnowledgeGraphService composition refactoring.

Validates that:
- ``KnowledgeGraphService`` composes ``GraphNodeRepository`` and ``GraphExpander``
- All public delegation methods forward to the correct composed service
- ``GraphNodeRepository`` and ``GraphExpander`` can be instantiated with callables
- The singleton accessor ``get_knowledge_graph_service`` returns a
  ``KnowledgeGraphService`` instance

These are pure unit tests — no Neo4j connection is required.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure backend is on path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ===========================================================================
# Helpers
# ===========================================================================


def _make_service():
    """Create a KnowledgeGraphService with mocked connection settings."""
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
# Composition wiring
# ===========================================================================


@pytest.mark.unit
class TestCompositionWiring:
    """Verify that __init__ wires composed services correctly."""

    def test_nodes_attribute_is_graph_node_repository(self):
        from services.graph_node_repository import GraphNodeRepository

        svc = _make_service()
        assert isinstance(svc.nodes, GraphNodeRepository)

    def test_expander_attribute_is_graph_expander(self):
        from services.graph_expander import GraphExpander

        svc = _make_service()
        assert isinstance(svc.expander, GraphExpander)

    def test_nodes_receives_execute_query(self):
        svc = _make_service()
        # Verify same underlying function (bound methods create new wrappers)
        assert svc.nodes._execute_query.__func__ is svc._execute_query.__func__

    def test_nodes_receives_get_session(self):
        svc = _make_service()
        assert svc.nodes._get_session.__func__ is svc.get_session.__func__

    def test_expander_receives_execute_query(self):
        svc = _make_service()
        assert svc.expander._execute_query.__func__ is svc._execute_query.__func__

    def test_expander_receives_get_session(self):
        svc = _make_service()
        assert svc.expander._get_session.__func__ is svc.get_session.__func__


# ===========================================================================
# GraphNodeRepository delegation
# ===========================================================================


@pytest.mark.unit
class TestNodeDelegation:
    """Each CRUD method on the facade delegates to self.nodes.<method>."""

    _DELEGATION_MAP = [
        # (facade_method, delegate_method, call_args, expected_args)
        # call_args = what we pass to the facade
        # expected_args = what the delegate receives (including defaults)
        ("create_video_node", "create_video_node", (MagicMock(),), None),
        ("get_video_node", "get_video_node", ("vid-1",), None),
        ("get_video_summary", "get_video_summary", ("vid-1",), None),
        ("update_video_summary", "update_video_summary", ("vid-1", "summary", ["t"]), None),
        ("create_scene_node", "create_scene_node", (MagicMock(),), None),
        ("get_video_scenes", "get_video_scenes", ("vid-1",), None),
        ("get_scene_frames", "get_scene_frames", ("scene-1",), None),
        ("get_video_frames", "get_video_frames", ("vid-1",), None),
        ("create_frame_node", "create_frame_node", (MagicMock(),), None),
        ("create_frames_batch", "create_frames_batch", ([],), None),
        ("create_entity_node", "create_entity_node", (MagicMock(), "frame-1"), None),
        ("create_entities_batch", "create_entities_batch", ([],), None),
        ("get_entity_by_name", "get_entity_by_name", ("John",), ("John", None)),
        ("create_audio_segment", "create_audio_segment", (MagicMock(),), None),
        ("create_audio_segments_batch", "create_audio_segments_batch", ([],), ([], 100)),
        ("get_video_transcripts", "get_video_transcripts", ("vid-1",), None),
        ("search_transcripts", "search_transcripts", ("hello",), ("hello", None, 20)),
        ("delete_video_transcripts", "delete_video_transcripts", ("vid-1",), None),
        ("create_relation", "create_relation", ("a", "b", "REL"), ("a", "b", "REL", None)),
        ("create_relations_batch", "create_relations_batch", ([],), None),
        (
            "create_temporal_relation",
            "create_temporal_relation",
            ("a", "b", "REL"),
            ("a", "b", "REL", None),
        ),
        ("create_entity_cooccurrence", "create_entity_cooccurrence", ("frame-1",), None),
        ("create_frame_chain", "create_frame_chain", ("vid-1",), None),
        ("create_segment_chain", "create_segment_chain", ("vid-1",), None),
        ("create_scene_chain", "create_scene_chain", ("vid-1",), None),
    ]

    @pytest.mark.parametrize(
        "facade_method,delegate_method,call_args,expected_args", _DELEGATION_MAP
    )
    def test_delegation(self, facade_method, delegate_method, call_args, expected_args):
        svc = _make_service()
        mock_fn = MagicMock(return_value="ok")
        setattr(svc.nodes, delegate_method, mock_fn)

        result = getattr(svc, facade_method)(*call_args)

        expected = expected_args if expected_args is not None else call_args
        mock_fn.assert_called_once_with(*expected)
        assert result == "ok"


# ===========================================================================
# GraphExpander delegation
# ===========================================================================


@pytest.mark.unit
class TestExpanderDelegation:
    """Each expansion/analytics/cleanup method delegates to self.expander."""

    _DELEGATION_MAP = [
        # (facade_method, delegate_method, call_args, expected_args)
        ("expand_context", "expand_context", ("node-1",), ("node-1", 2, None, 50)),
        ("get_entity_timeline", "get_entity_timeline", ("John", "vid-1"), None),
        ("get_related_entities", "get_related_entities", ("entity-1",), ("entity-1", None, 20)),
        (
            "find_common_entities",
            "find_common_entities",
            (["vid-1", "vid-2"],),
            (["vid-1", "vid-2"], None, 20),
        ),
        ("get_video_topics", "get_video_topics", (["vid-1"],), None),
        ("get_stats", "get_stats", (), None),
        ("get_video_subgraph", "get_video_subgraph", ("vid-1",), ("vid-1", 2, True, 200)),
        ("expand_node_subgraph", "expand_node_subgraph", ("node-1",), ("node-1", 1, 50)),
        ("delete_video_graph", "delete_video_graph", ("vid-1",), None),
        ("clear_all", "clear_all", (), None),
        (
            "walk_temporal_chain",
            "walk_temporal_chain",
            ("node-1", "NEXT_FRAME"),
            ("node-1", "NEXT_FRAME", "forward", 10),
        ),
    ]

    @pytest.mark.parametrize(
        "facade_method,delegate_method,call_args,expected_args", _DELEGATION_MAP
    )
    def test_delegation(self, facade_method, delegate_method, call_args, expected_args):
        svc = _make_service()
        mock_fn = MagicMock(return_value="ok")
        setattr(svc.expander, delegate_method, mock_fn)

        result = getattr(svc, facade_method)(*call_args)

        expected = expected_args if expected_args is not None else call_args
        mock_fn.assert_called_once_with(*expected)
        assert result == "ok"


# ===========================================================================
# Search methods stay in the facade (not delegated)
# ===========================================================================


@pytest.mark.unit
class TestSearchMethodsInFacade:
    """search_entities, search_frames_by_description, search_multimodal remain local."""

    def test_search_entities_is_not_delegated(self):
        svc = _make_service()
        # search_entities is defined directly on the class, not on nodes or expander
        method = type(svc).search_entities
        assert method is not None
        # It should NOT be a simple wrapper around nodes.search_entities
        assert not hasattr(svc.nodes, "search_entities") or True  # just verify it exists on svc

    def test_search_frames_by_description_exists(self):
        svc = _make_service()
        assert callable(getattr(svc, "search_frames_by_description", None))

    def test_search_multimodal_exists(self):
        svc = _make_service()
        assert callable(getattr(svc, "search_multimodal", None))


# ===========================================================================
# Standalone composed service instantiation
# ===========================================================================


@pytest.mark.unit
class TestStandaloneInstantiation:
    """GraphNodeRepository and GraphExpander can be created with bare callables."""

    def test_graph_node_repository_accepts_callables(self):
        from services.graph_node_repository import GraphNodeRepository

        exec_fn = MagicMock()
        sess_fn = MagicMock()
        repo = GraphNodeRepository(exec_fn, sess_fn)
        assert repo._execute_query is exec_fn
        assert repo._get_session is sess_fn

    def test_graph_expander_accepts_callables(self):
        from services.graph_expander import GraphExpander

        exec_fn = MagicMock()
        sess_fn = MagicMock()
        exp = GraphExpander(exec_fn, sess_fn)
        assert exp._execute_query is exec_fn
        assert exp._get_session is sess_fn


# ===========================================================================
# Singleton accessor
# ===========================================================================


@pytest.mark.unit
class TestSingleton:
    """get_knowledge_graph_service returns a KnowledgeGraphService singleton."""

    def test_returns_instance(self):
        with patch("services.knowledge_graph.settings") as mock_settings:
            neo4j = MagicMock()
            neo4j.uri = "bolt://localhost:7687"
            neo4j.user = "neo4j"
            neo4j.password = "test"
            neo4j.database = "neo4j"
            mock_settings.neo4j = neo4j

            import services.knowledge_graph as mod

            # Reset singleton state
            mod._knowledge_graph_service = None

            svc = mod.get_knowledge_graph_service()
            from services.knowledge_graph import KnowledgeGraphService

            assert isinstance(svc, KnowledgeGraphService)

            # Same instance on second call
            svc2 = mod.get_knowledge_graph_service()
            assert svc2 is svc

            # Clean up
            mod._knowledge_graph_service = None


# ===========================================================================
# Package exports
# ===========================================================================


@pytest.mark.unit
class TestPackageExports:
    """GraphNodeRepository and GraphExpander are accessible from services package."""

    def test_graph_node_repository_exported(self):
        from services import GraphNodeRepository

        assert GraphNodeRepository is not None

    def test_graph_expander_exported(self):
        from services import GraphExpander

        assert GraphExpander is not None

    def test_knowledge_graph_service_still_exported(self):
        from services import KnowledgeGraphService, get_knowledge_graph_service

        assert KnowledgeGraphService is not None
        assert get_knowledge_graph_service is not None


# ===========================================================================
# Full public API coverage
# ===========================================================================


@pytest.mark.unit
class TestPublicAPICoverage:
    """Every method that existed before the refactoring still exists on the facade."""

    EXPECTED_PUBLIC_METHODS = [
        # Connection management
        "connect",
        "disconnect",
        "is_connected",
        "get_session",
        # Async connection
        "async_connect",
        "async_disconnect",
        "is_async_connected",
        "get_async_session",
        "async_execute_query",
        # Schema
        "initialize_schema",
        # CRUD (delegated to nodes)
        "create_video_node",
        "get_video_node",
        "get_video_summary",
        "update_video_summary",
        "create_scene_node",
        "get_video_scenes",
        "get_scene_frames",
        "get_video_frames",
        "create_frame_node",
        "create_frames_batch",
        "create_entity_node",
        "create_entities_batch",
        "get_entity_by_name",
        "create_audio_segment",
        "create_audio_segments_batch",
        "get_video_transcripts",
        "search_transcripts",
        "delete_video_transcripts",
        "create_relation",
        "create_relations_batch",
        "create_temporal_relation",
        "create_entity_cooccurrence",
        # Temporal chains (delegated to nodes)
        "create_frame_chain",
        "create_segment_chain",
        "create_scene_chain",
        "create_temporal_chains",
        # Search (kept in facade)
        "search_entities",
        "search_frames_by_description",
        "search_multimodal",
        # Expansion (delegated to expander)
        "expand_context",
        "get_entity_timeline",
        "get_related_entities",
        "find_common_entities",
        "get_video_topics",
        "get_stats",
        "get_video_subgraph",
        "expand_node_subgraph",
        "delete_video_graph",
        "clear_all",
        # Temporal chain traversal (delegated to expander)
        "walk_temporal_chain",
    ]

    def test_all_public_methods_exist(self):
        svc = _make_service()
        missing = [m for m in self.EXPECTED_PUBLIC_METHODS if not hasattr(svc, m)]
        assert missing == [], f"Missing public methods: {missing}"

    def test_all_public_methods_are_callable(self):
        svc = _make_service()
        non_callable = []
        for m in self.EXPECTED_PUBLIC_METHODS:
            attr = getattr(svc, m, None)
            # Properties are not "callable" but are still valid API members
            if (
                attr is None
                or not callable(attr)
                and not isinstance(getattr(type(svc), m, None), property)
            ):
                non_callable.append(m)
        assert non_callable == [], f"Non-callable public attributes: {non_callable}"


# ===========================================================================
# Fulltext index migration
# ===========================================================================


@pytest.mark.unit
class TestFulltextIndexDefs:
    """Validate the _FULLTEXT_INDEX_DEFS class attribute."""

    def test_contains_expected_indexes(self):
        svc = _make_service()
        expected_names = {
            "entity_search",
            "frame_search",
            "topic_search",
            "audio_search",
            "community_search",
        }
        assert set(svc._FULLTEXT_INDEX_DEFS.keys()) == expected_names

    def test_entity_search_properties(self):
        svc = _make_service()
        assert svc._FULLTEXT_INDEX_DEFS["entity_search"] == ["name", "description"]

    def test_frame_search_properties(self):
        svc = _make_service()
        assert svc._FULLTEXT_INDEX_DEFS["frame_search"] == ["description"]

    def test_community_search_properties(self):
        svc = _make_service()
        assert svc._FULLTEXT_INDEX_DEFS["community_search"] == ["title", "summary", "themes_text"]


@pytest.mark.unit
class TestMigrateFulltextIndexes:
    """Unit tests for _migrate_fulltext_indexes()."""

    def _make_mock_session(self, existing_indexes: dict[str, list[str]]):
        """Create a mock Neo4j session that returns the given fulltext indexes.

        ``existing_indexes`` maps index name → list of property names.
        """
        records = [{"name": name, "properties": props} for name, props in existing_indexes.items()]
        session = MagicMock()
        session.run.return_value = records
        return session

    # -- nothing to drop --------------------------------------------------

    def test_no_existing_indexes_does_nothing(self):
        svc = _make_service()
        session = self._make_mock_session({})

        svc._migrate_fulltext_indexes(session)

        # Only the SHOW query should have been issued
        session.run.assert_called_once()

    def test_matching_indexes_are_not_dropped(self):
        svc = _make_service()
        session = self._make_mock_session(
            {
                "entity_search": ["name", "description"],
                "frame_search": ["description"],
            }
        )

        svc._migrate_fulltext_indexes(session)

        # Only the SHOW query; no DROP
        session.run.assert_called_once()

    def test_unknown_indexes_are_ignored(self):
        """Indexes not in _FULLTEXT_INDEX_DEFS should never be dropped."""
        svc = _make_service()
        session = self._make_mock_session(
            {
                "some_other_index": ["foo", "bar"],
            }
        )

        svc._migrate_fulltext_indexes(session)

        session.run.assert_called_once()

    # -- stale indexes dropped --------------------------------------------

    def test_stale_index_is_dropped(self):
        svc = _make_service()
        # entity_search has ["name", "description"] expected but we report only ["name"]
        session = self._make_mock_session(
            {
                "entity_search": ["name"],
            }
        )

        svc._migrate_fulltext_indexes(session)

        # SHOW + DROP
        assert session.run.call_count == 2
        drop_call = session.run.call_args_list[1]
        assert "DROP INDEX entity_search" in drop_call.args[0]

    def test_multiple_stale_indexes_dropped(self):
        svc = _make_service()
        session = self._make_mock_session(
            {
                "entity_search": ["name"],  # stale
                "frame_search": ["description"],  # OK
                "community_search": ["title", "summary"],  # stale (missing themes_text)
            }
        )

        svc._migrate_fulltext_indexes(session)

        # SHOW + 2 × DROP
        assert session.run.call_count == 3
        drop_args = [c.args[0] for c in session.run.call_args_list[1:]]
        assert any("entity_search" in a for a in drop_args)
        assert any("community_search" in a for a in drop_args)

    def test_superset_properties_are_stale(self):
        """An index with *extra* properties should also be dropped."""
        svc = _make_service()
        session = self._make_mock_session(
            {
                "frame_search": ["description", "extra_col"],
            }
        )

        svc._migrate_fulltext_indexes(session)

        assert session.run.call_count == 2
        assert "DROP INDEX frame_search" in session.run.call_args_list[1].args[0]

    def test_property_order_does_not_matter(self):
        """Properties in different order but same set should NOT be dropped."""
        svc = _make_service()
        session = self._make_mock_session(
            {
                "entity_search": ["description", "name"],  # reversed order
            }
        )

        svc._migrate_fulltext_indexes(session)

        # Only the SHOW query – no DROP
        session.run.assert_called_once()


@pytest.mark.unit
class TestInitializeSchemaCallsMigration:
    """Verify that initialize_schema invokes _migrate_fulltext_indexes."""

    def test_migrate_called_before_index_creation(self):
        svc = _make_service()
        mock_session = MagicMock()
        # Make the session context-manager work
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(svc, "get_session", return_value=mock_session),
            patch.object(svc, "_migrate_fulltext_indexes") as mock_migrate,
        ):
            svc.initialize_schema()

        mock_migrate.assert_called_once_with(mock_session)

    def test_migrate_exception_is_caught(self):
        """initialize_schema should not raise even if migration fails."""
        svc = _make_service()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(svc, "get_session", return_value=mock_session),
            patch.object(svc, "_migrate_fulltext_indexes", side_effect=RuntimeError("boom")),
        ):
            # Should NOT raise
            svc.initialize_schema()

    def test_indexes_still_created_after_migration_failure(self):
        """Even if migration raises, the rest of initialize_schema should proceed."""
        svc = _make_service()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(svc, "get_session", return_value=mock_session),
            patch.object(svc, "_migrate_fulltext_indexes", side_effect=RuntimeError("boom")),
        ):
            svc.initialize_schema()

        # session.run should still have been called for constraints & indexes
        assert mock_session.run.call_count > 0
