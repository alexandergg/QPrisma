"""Knowledge Graph and graph-adjacent dependency providers."""

from collections.abc import Callable
from typing import Any

_knowledge_graph_service = None
_graph_route_service = None
_hierarchical_context_service = None
_community_detection_service = None
_hierarchical_query_service = None


def get_knowledge_graph_service():
    """Get or create Knowledge Graph Service, ensuring it is connected."""
    global _knowledge_graph_service

    if _knowledge_graph_service is None:
        from services.knowledge_graph import (
            get_knowledge_graph_service as _get_kg_service,
        )

        _knowledge_graph_service = _get_kg_service()
        if not _knowledge_graph_service.is_connected:
            _knowledge_graph_service.connect()
    return _knowledge_graph_service


def get_async_graph_service():
    """Return the non-blocking AsyncKnowledgeGraphFacade singleton."""
    from services.async_graph_facade import get_async_knowledge_graph_facade

    return get_async_knowledge_graph_facade()


def get_graph_search_service():
    """Get or create Graph Search Service (VideoRAG-style hybrid search)."""
    from services.graph_search_service import (
        get_graph_search_service as _canonical_getter,
    )

    return _canonical_getter()


def get_chat_service(
    *,
    openai_client: Any | None = None,
    graph_search_service: Any | None = None,
    service_cls: type | None = None,
    openai_client_factory: Callable[[], Any] | None = None,
    graph_search_service_factory: Callable[[], Any] | None = None,
):
    """Build the classic chat compatibility service from API dependencies."""
    from services.chat_service import ChatService

    if openai_client is None:
        if openai_client_factory is None:
            from api.dependencies import get_async_openai_client as openai_client_factory

        openai_client = openai_client_factory()
    if graph_search_service is None:
        graph_search_service_factory = graph_search_service_factory or get_graph_search_service
        graph_search_service = graph_search_service_factory()

    resolved_service_cls = service_cls or ChatService
    return resolved_service_cls(
        openai_client=openai_client,
        graph_search_service=graph_search_service,
    )


def get_structure_service(
    *,
    graph_service: Any | None = None,
    service_cls: type | None = None,
    graph_service_factory: Callable[[], Any] | None = None,
):
    """Build the video structure service from API dependencies."""
    from services.structure_service import StructureService

    if graph_service is None:
        graph_service_factory = graph_service_factory or get_knowledge_graph_service
        graph_service = graph_service_factory()

    resolved_service_cls = service_cls or StructureService
    return resolved_service_cls(graph_service=graph_service)


def get_graph_route_service(
    *,
    knowledge_graph_service_factory: Callable[[], Any] | None = None,
    graph_search_service_factory: Callable[[], Any] | None = None,
):
    """Get or create Graph Route Service (business logic for graph routes)."""
    global _graph_route_service

    if _graph_route_service is None:
        from services.graph_route_service import GraphRouteService

        knowledge_graph_service_factory = (
            knowledge_graph_service_factory or get_knowledge_graph_service
        )
        graph_search_service_factory = graph_search_service_factory or get_graph_search_service
        _graph_route_service = GraphRouteService(
            knowledge_graph_service=knowledge_graph_service_factory(),
            graph_search_service=graph_search_service_factory(),
        )
    return _graph_route_service


def get_hierarchical_context_service(
    *,
    graph_service_factory: Callable[[], Any] | None = None,
    embedding_service_factory: Callable[[], Any] | None = None,
):
    """Get or create Hierarchical Context Service."""
    global _hierarchical_context_service

    if _hierarchical_context_service is None:
        from services.embedding_service import get_embedding_service
        from services.hierarchical_context_service import (
            get_hierarchical_context_service as _get_hcs,
        )

        graph_service_factory = graph_service_factory or get_knowledge_graph_service
        embedding_service_factory = embedding_service_factory or get_embedding_service
        graph_svc = graph_service_factory()
        embedding_svc = embedding_service_factory()
        _hierarchical_context_service = _get_hcs(
            graph_service=graph_svc, embedding_service=embedding_svc
        )
    return _hierarchical_context_service


def get_hierarchical_query_service():
    """Get or create Hierarchical Query Service."""
    global _hierarchical_query_service

    if _hierarchical_query_service is None:
        from services.hierarchical_query_service import (
            get_hierarchical_query_service as _get_hqs,
        )

        _hierarchical_query_service = _get_hqs()
    return _hierarchical_query_service


async def get_tool_artifact_service():
    """Get ToolArtifactService singleton."""
    from services.tool_artifact_service import (
        get_tool_artifact_service as _get_tool_artifact_service,
    )

    return await _get_tool_artifact_service()


def get_community_detection_service():
    """Get or create Community Detection Service."""
    global _community_detection_service

    if _community_detection_service is None:
        from services.community_detection_service import (
            get_community_detection_service as _get_cds,
        )

        _community_detection_service = _get_cds()
    return _community_detection_service
