"""Security-focused tests for hierarchical query scoping."""

from unittest.mock import AsyncMock

import pytest

from models.graph_models import NodeType
from services.hierarchical_query_service import HierarchicalQueryService


class _FakeGraphService:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def execute_query(self, query, params, **_kwargs):
        self.calls.append((query, params))
        return []


@pytest.mark.unit
async def test_search_level_filters_to_allowed_video_ids():
    graph = _FakeGraphService()
    service = HierarchicalQueryService(
        graph_service=graph,
        embedding_service=AsyncMock(),
    )

    await service._search_level(
        query_embedding=[0.1, 0.2],
        node_type=NodeType.VIDEO,
        allowed_video_ids=["vid-1", "vid-2"],
        top_k=5,
    )

    query, params = graph.calls[0]
    assert "n.video_id IN $allowed_video_ids" in query
    assert params["allowed_video_ids"] == ["vid-1", "vid-2"]


@pytest.mark.unit
async def test_drill_down_search_short_circuits_empty_allowed_video_ids():
    graph = _FakeGraphService()
    embedding_service = AsyncMock()
    service = HierarchicalQueryService(
        graph_service=graph,
        embedding_service=embedding_service,
    )

    results = await service.drill_down_search(
        query_text="demo",
        allowed_video_ids=[],
    )

    assert results == []
    embedding_service.generate_embedding.assert_not_awaited()
    assert graph.calls == []
