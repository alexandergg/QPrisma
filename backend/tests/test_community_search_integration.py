"""
Tests for Community Detection search integration.

Validates:
- COMMUNITY is included in default hybrid_search node_types
- _fulltext_search resolves the correct index name for COMMUNITY nodes
- community_search fulltext index is declared in schema initialization

Pure unit tests — no Neo4j or Azure OpenAI connection required.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.graph_models import NodeType

# ===========================================================================
# Task 1 — default node_types includes COMMUNITY
# ===========================================================================


@pytest.mark.unit
class TestDefaultNodeTypes:
    """hybrid_search must include COMMUNITY in the default node_types."""

    @pytest.mark.asyncio
    async def test_hybrid_search_defaults_include_community(self) -> None:
        """When node_types is None, COMMUNITY must be in the resolved list."""
        from services.graph_search_service import GraphSearchService

        mock_graph = MagicMock()
        mock_embed = MagicMock()
        mock_embed.generate_embedding = AsyncMock(return_value=[0.0] * 3072)

        svc = GraphSearchService(
            graph_service=mock_graph,
            embedding_service=mock_embed,
        )

        # Capture the node_types that vector_search is called with.
        captured_types: list[NodeType] = []

        def _spy_vector_search(*, node_type: NodeType, **kwargs):
            captured_types.append(node_type)
            return []

        svc.vector_search = _spy_vector_search

        # Also stub fulltext + graph expansion to avoid side-effects.
        svc._fulltext_search = MagicMock(return_value=[])
        svc._merge_fulltext_scores = MagicMock(side_effect=lambda c, *a, **kw: c)
        svc._expand_graph_context = MagicMock(side_effect=lambda c, *a, **kw: c)
        svc._compute_temporal_scores = MagicMock(side_effect=lambda c, *a, **kw: c)
        svc._rank_candidates = MagicMock(return_value=[])

        await svc.hybrid_search(query_text="test query", video_id="v1")

        assert (
            NodeType.COMMUNITY in captured_types
        ), "COMMUNITY should be in the default node_types for hybrid_search"


# ===========================================================================
# Task 2 — fulltext search resolves community_search index
# ===========================================================================


@pytest.mark.unit
class TestFulltextCommunityIndex:
    """_fulltext_search must map COMMUNITY to 'community_search' index."""

    def test_community_index_name_resolved(self) -> None:
        """Calling _fulltext_search with NodeType.COMMUNITY should use 'community_search'."""
        from services.graph_search_queries import GraphSearchQueryMixin

        # Create a minimal concrete subclass so we can instantiate the mixin.
        class _Stub(GraphSearchQueryMixin):
            def __init__(self, graph_service: MagicMock):
                self.graph_service = graph_service

        mock_session = MagicMock()
        mock_session.run.return_value = [
            {"id": "comm-1", "score": 1.5},
        ]
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_session)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        mock_graph = MagicMock()
        mock_graph.get_session.return_value = mock_ctx

        stub = _Stub(graph_service=mock_graph)

        results = stub._fulltext_search(
            query_text="test topic",
            node_type=NodeType.COMMUNITY,
            limit=5,
            video_id=None,
        )

        assert len(results) == 1
        assert results[0][0] == "comm-1"

        # Verify the Cypher received the correct index name.
        call_kwargs = mock_session.run.call_args
        passed_params = call_kwargs[1] if call_kwargs[1] else {}
        assert passed_params.get("index_name") == "community_search"

    def test_unknown_node_type_returns_empty(self) -> None:
        """An unsupported node type should return an empty list."""
        from services.graph_search_queries import GraphSearchQueryMixin

        class _Stub(GraphSearchQueryMixin):
            def __init__(self, graph_service: MagicMock):
                self.graph_service = graph_service

        stub = _Stub(graph_service=MagicMock())

        # Use a mock node type not in the if/elif chain
        mock_type = MagicMock()
        mock_type.value = "Nonexistent"
        results = stub._fulltext_search(
            query_text="anything",
            node_type=mock_type,
            limit=5,
            video_id=None,
        )
        assert results == []


# ===========================================================================
# Task 2 — schema declares community_search fulltext index
# ===========================================================================


@pytest.mark.unit
class TestSchemaDeclaration:
    """The community_search fulltext index must be declared in _ensure_schema."""

    def test_community_search_index_in_schema(self) -> None:
        """knowledge_graph._ensure_schema must include community_search with themes_text."""
        import inspect

        import services.knowledge_graph as kg_module

        source = inspect.getsource(kg_module)

        assert (
            "community_search" in source
        ), "community_search fulltext index must be declared in knowledge_graph.py"
        assert (
            "c.themes_text" in source
        ), "community_search index should include the themes_text property"
