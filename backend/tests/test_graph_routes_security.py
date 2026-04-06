"""
Focused security tests for graph route authorization.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from api.routes.graph_routes import (
    clear_all_graph_data,
    cross_video_search,
    expand_context,
    generate_embeddings,
    get_related_entities,
    get_video_graph,
)
from models.graph_models import NodeType
from models.graph_route_schemas import (
    ContextExpansionRequest,
    CrossVideoSearchRequest,
    GenerateEmbeddingsRequest,
    RelatedEntitiesRequest,
)


@pytest.mark.unit
class TestGraphRouteSecurity:
    @pytest.mark.asyncio
    async def test_clear_all_graph_data_requires_superuser(self, test_user):
        with (
            patch("api.routes.graph_routes.get_knowledge_graph_service") as mock_service,
            pytest.raises(HTTPException) as exc_info,
        ):
            await clear_all_graph_data(confirm=True, current_user=test_user)

        assert exc_info.value.status_code == 403
        mock_service.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_video_graph_checks_media_ownership(self, test_user):
        mock_route_service = MagicMock()
        mock_route_service.get_video_graph_data.return_value = SimpleNamespace(
            error=None,
            video={"id": "vid-1"},
            scenes=[],
            total_scenes=0,
            graph_stats={},
        )

        with (
            patch("api.routes.graph_routes.get_media_or_404") as mock_auth,
            patch(
                "api.routes.graph_routes.get_graph_route_service",
                return_value=mock_route_service,
            ),
        ):
            response = await get_video_graph("vid-1", current_user=test_user)

        mock_auth.assert_called_once_with("vid-1", test_user)
        assert response["video"]["id"] == "vid-1"

    @pytest.mark.asyncio
    async def test_generate_embeddings_requires_video_scope_for_regular_user(self, test_user):
        request = GenerateEmbeddingsRequest(
            node_type=NodeType.FRAME,
            video_id=None,
            batch_size=10,
        )

        with (
            patch("api.routes.graph_routes.get_graph_search_service") as mock_service,
            pytest.raises(HTTPException) as exc_info,
        ):
            await generate_embeddings(
                request=request,
                current_user=test_user,
            )

        assert exc_info.value.status_code == 403
        mock_service.assert_not_called()

    @pytest.mark.asyncio
    async def test_cross_video_search_scopes_results_to_current_user(self, test_user):
        request = CrossVideoSearchRequest(
            reference_node_id="node-1",
            limit=5,
            min_similarity=0.8,
        )
        mock_search_service = MagicMock()
        mock_search_service.find_similar_across_videos.return_value = [
            SimpleNamespace(
                node_id="node-2",
                node_type=NodeType.FRAME,
                video_id="vid-2",
                vector_score=0.91,
                content={"id": "node-2"},
            )
        ]

        with (
            patch("api.routes.graph_routes.get_graph_node_media_or_404") as mock_node_auth,
            patch(
                "api.routes.graph_routes.get_graph_search_service",
                return_value=mock_search_service,
            ),
        ):
            response = await cross_video_search(request, current_user=test_user)

        mock_node_auth.assert_called_once_with("node-1", test_user)
        mock_search_service.find_similar_across_videos.assert_called_once_with(
            reference_node_id="node-1",
            limit=5,
            min_similarity=0.8,
            user_id=test_user.id,
        )
        assert response.total_found == 1

    @pytest.mark.asyncio
    async def test_expand_context_checks_node_ownership(self, test_user):
        request = ContextExpansionRequest(node_id="node-1", hops=2, max_nodes=10)
        mock_service = MagicMock()
        mock_service.expand_context.return_value = {
            "center_node_id": "node-1",
            "hops": 2,
            "total_nodes": 1,
            "nodes_by_distance": {0: [{"id": "node-1"}]},
        }

        with (
            patch("api.routes.graph_routes.get_graph_node_media_or_404") as mock_node_auth,
            patch(
                "api.routes.graph_routes.get_knowledge_graph_service",
                return_value=mock_service,
            ),
        ):
            response = await expand_context(request, current_user=test_user)

        mock_node_auth.assert_called_once_with("node-1", test_user)
        mock_service.expand_context.assert_called_once_with(
            node_id="node-1",
            hops=2,
            relation_types=None,
            max_nodes=10,
            user_id=test_user.id,
        )
        assert response.center_node_id == "node-1"

    @pytest.mark.asyncio
    async def test_related_entities_checks_node_ownership_and_user_scope(self, test_user):
        request = RelatedEntitiesRequest(entity_id="entity-1", limit=10)
        mock_service = MagicMock()
        mock_service.get_related_entities.return_value = [
            {"entity": {"id": "entity-2"}, "relation": "RELATED_TO", "direction": "outgoing"}
        ]

        with (
            patch("api.routes.graph_routes.get_graph_node_media_or_404") as mock_node_auth,
            patch(
                "api.routes.graph_routes.get_knowledge_graph_service",
                return_value=mock_service,
            ),
        ):
            response = await get_related_entities(request, current_user=test_user)

        mock_node_auth.assert_called_once_with("entity-1", test_user)
        mock_service.get_related_entities.assert_called_once_with(
            entity_id="entity-1",
            relation_types=None,
            limit=10,
            user_id=test_user.id,
        )
        assert response["total_related"] == 1
