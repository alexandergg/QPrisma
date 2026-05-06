"""
Focused security tests for graph route authorization.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from api.routes.graph_routes import (
    cross_video_search,
    expand_context,
    generate_embeddings,
    get_video_graph,
)
from models.graph_models import NodeType
from models.graph_route_schemas import (
    ContextExpansionRequest,
    CrossVideoSearchRequest,
    GenerateEmbeddingsRequest,
)


@pytest.mark.unit
class TestGraphRouteSecurity:
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
        mock_search_service.find_similar_across_videos = AsyncMock(
            return_value=[
                SimpleNamespace(
                    node_id="node-2",
                    node_type=NodeType.FRAME,
                    video_id="vid-2",
                    vector_score=0.91,
                    content={"id": "node-2"},
                )
            ]
        )

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
        mock_service = AsyncMock()
        mock_service.expand_context.return_value = {
            "center_node_id": "node-1",
            "hops": 2,
            "total_nodes": 1,
            "nodes_by_distance": {0: [{"id": "node-1"}]},
        }

        with (
            patch("api.routes.graph_routes.get_graph_node_media_or_404") as mock_node_auth,
            patch(
                "api.routes.graph_routes.get_async_graph_service",
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
