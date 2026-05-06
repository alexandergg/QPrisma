"""Knowledge Graph visualization endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import (
    get_current_user,
)
from core.exceptions import internal_error, not_found_error
from models.graph_route_schemas import (
    ExpandSubgraphRequest,
    GraphVisualizationResponse,
    NvlNode,
    NvlRelationship,
)
from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


def get_async_graph_service():
    from api.routes import graph_routes

    return graph_routes.get_async_graph_service()


def get_graph_node_media_or_404(node_id: str, current_user: User):
    from api.routes import graph_routes

    return graph_routes.get_graph_node_media_or_404(node_id, current_user)


def get_media_or_404(media_id: str, current_user: User):
    from api.routes import graph_routes

    return graph_routes.get_media_or_404(media_id, current_user)

_NODE_VISUAL_MAP: dict[str, tuple[str, int]] = {
    "Video": ("#4F46E5", 40),
    "Chapter": ("#7C3AED", 30),
    "Scene": ("#6366F1", 25),
    "Frame": ("#06B6D4", 15),
    "Entity": ("#8B5CF6", 18),
    "AudioSegment": ("#10B981", 15),
    "Topic": ("#F59E0B", 20),
}

_ENTITY_COLOR_MAP: dict[str, str] = {
    "person": "#EC4899",
    "object": "#8B5CF6",
    "location": "#14B8A6",
    "action": "#F97316",
    "concept": "#6366F1",
    "text": "#64748B",
    "brand": "#EF4444",
    "event": "#A855F7",
}


def _raw_to_nvl_node(raw: dict) -> NvlNode:
    """Convert a raw Neo4j node dict to NVL format with visual styling."""
    labels = raw.get("labels", [])
    props = raw.get("properties", {})
    node_id = raw.get("id") or props.get("id", "")

    node_type = "Entity"
    for label in labels:
        if label in _NODE_VISUAL_MAP:
            node_type = label
            break

    color, size = _NODE_VISUAL_MAP.get(node_type, ("#6366F1", 20))
    entity_type = props.get("entity_type")
    if node_type == "Entity" and entity_type:
        color = _ENTITY_COLOR_MAP.get(entity_type, color)

    caption = (
        props.get("title")
        or props.get("name")
        or props.get("normalized_name")
        or props.get("description", "")[:40]
        or f"{node_type}"
    )
    if node_type == "Frame":
        ts = props.get("timestamp")
        caption = f"{ts:.1f}s" if ts is not None else "Frame"
    elif node_type == "AudioSegment":
        start = props.get("start_time", 0)
        end = props.get("end_time", 0)
        caption = f"{start:.0f}-{end:.0f}s"

    clean_props = {k: v for k, v in props.items() if k != "embedding"}

    return NvlNode(
        id=str(node_id),
        caption=str(caption),
        color=color,
        size=size,
        node_type=node_type,
        entity_type=entity_type,
        properties=clean_props,
    )


def _raw_to_nvl_rel(raw: dict) -> NvlRelationship:
    """Convert a raw Neo4j relationship dict to NVL format."""
    rel_type = raw.get("type", "RELATES_TO")
    return NvlRelationship(
        id=str(raw.get("id", "")),
        **{"from": str(raw.get("start", ""))},
        to=str(raw.get("end", "")),
        caption=rel_type.replace("_", " ").title(),
        type=rel_type,
        properties=raw.get("properties", {}),
    )


@router.get("/video/{video_id}/visualization", response_model=GraphVisualizationResponse)
async def get_video_visualization(
    video_id: str,
    depth: int = Query(default=2, ge=1, le=4),
    include_entities: bool = Query(default=True),
    max_nodes: int = Query(default=200, ge=1, le=500),
    current_user: User = Depends(get_current_user),
):
    """Return the video graph in NVL-compatible format."""
    try:
        get_media_or_404(video_id, current_user)
        service = get_async_graph_service()
        subgraph = await service.get_video_subgraph(
            video_id=video_id,
            depth=depth,
            include_entities=include_entities,
            max_nodes=max_nodes,
        )

        raw_nodes = subgraph.get("nodes", [])
        raw_rels = subgraph.get("relationships", [])

        if not raw_nodes:
            raise not_found_error("Video", video_id)

        nvl_nodes = [_raw_to_nvl_node(n) for n in raw_nodes]
        nvl_rels = [_raw_to_nvl_rel(r) for r in raw_rels]

        return GraphVisualizationResponse(
            video_id=video_id,
            nodes=nvl_nodes,
            relationships=nvl_rels,
            total_nodes=len(nvl_nodes),
            total_relationships=len(nvl_rels),
            depth=depth,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get video visualization: %s", e, exc_info=True)
        raise internal_error() from e


@router.post("/expand-subgraph")
async def expand_subgraph(
    request: ExpandSubgraphRequest,
    current_user: User = Depends(get_current_user),
):
    """Expand a node neighborhood for progressive lazy-load in the graph viewer."""
    try:
        get_graph_node_media_or_404(request.node_id, current_user)
        service = get_async_graph_service()
        subgraph = await service.expand_node_subgraph(
            node_id=request.node_id,
            hops=request.hops,
            max_nodes=request.max_nodes,
            user_id=current_user.id,
        )

        raw_nodes = subgraph.get("nodes", [])
        raw_rels = subgraph.get("relationships", [])

        nvl_nodes = [_raw_to_nvl_node(n) for n in raw_nodes]
        nvl_rels = [_raw_to_nvl_rel(r) for r in raw_rels]

        return {
            "center_node_id": request.node_id,
            "nodes": [n.model_dump(by_alias=True) for n in nvl_nodes],
            "relationships": [r.model_dump(by_alias=True) for r in nvl_rels],
            "total_nodes": len(nvl_nodes),
            "total_relationships": len(nvl_rels),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to expand subgraph: %s", e, exc_info=True)
        raise internal_error() from e
