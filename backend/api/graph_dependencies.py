"""Knowledge Graph and graph-adjacent dependency providers."""


def get_knowledge_graph_service():
    """Get or create Knowledge Graph Service, ensuring it is connected."""
    import api.dependencies as deps

    if deps._knowledge_graph_service is None:
        from services.knowledge_graph import (
            get_knowledge_graph_service as _get_kg_service,
        )

        deps._knowledge_graph_service = _get_kg_service()
        if not deps._knowledge_graph_service.is_connected:
            deps._knowledge_graph_service.connect()
    return deps._knowledge_graph_service


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


def get_graph_route_service():
    """Get or create Graph Route Service (business logic for graph routes)."""
    import api.dependencies as deps

    if deps._graph_route_service is None:
        from services.graph_route_service import GraphRouteService

        deps._graph_route_service = GraphRouteService(
            knowledge_graph_service=deps.get_knowledge_graph_service(),
            graph_search_service=deps.get_graph_search_service(),
        )
    return deps._graph_route_service


def get_hierarchical_context_service():
    """Get or create Hierarchical Context Service."""
    import api.dependencies as deps

    if deps._hierarchical_context_service is None:
        from services.embedding_service import get_embedding_service
        from services.hierarchical_context_service import (
            get_hierarchical_context_service as _get_hcs,
        )

        graph_svc = deps.get_knowledge_graph_service()
        embedding_svc = get_embedding_service()
        deps._hierarchical_context_service = _get_hcs(
            graph_service=graph_svc, embedding_service=embedding_svc
        )
    return deps._hierarchical_context_service


def get_hierarchical_query_service():
    """Get or create Hierarchical Query Service."""
    import api.dependencies as deps

    if deps._hierarchical_query_service is None:
        from services.hierarchical_query_service import (
            get_hierarchical_query_service as _get_hqs,
        )

        deps._hierarchical_query_service = _get_hqs()
    return deps._hierarchical_query_service


async def get_tool_artifact_service():
    """Get ToolArtifactService singleton."""
    from services.tool_artifact_service import (
        get_tool_artifact_service as _get_tool_artifact_service,
    )

    return await _get_tool_artifact_service()


def get_community_detection_service():
    """Get or create Community Detection Service."""
    import api.dependencies as deps

    if deps._community_detection_service is None:
        from services.community_detection_service import (
            get_community_detection_service as _get_cds,
        )

        deps._community_detection_service = _get_cds()
    return deps._community_detection_service
