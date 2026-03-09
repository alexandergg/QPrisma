"""
Graph Route Service for QPrisma

Encapsulates business logic extracted from graph route handlers.
Provides advanced search orchestration, hierarchy processing,
and data transformation for the Knowledge Graph API.

Route handlers call into this service for anything beyond a trivial
single-method delegation. Pure formatting helpers are static so they
can be tested without wiring up live services.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from models.graph_models import (
    GraphSearchQuery,
    GraphSearchResponse,
    GraphSearchResult,
    NodeType,
)

if TYPE_CHECKING:
    from services.graph_search_service import GraphSearchService
    from services.knowledge_graph import KnowledgeGraphService

logger = logging.getLogger(__name__)


# =============================================================================
# Result Data-Classes (returned to route handlers instead of raising)
# =============================================================================


@dataclass
class AdvancedSearchResult:
    """Result of an advanced search operation."""

    response: GraphSearchResponse | None = None
    error: str | None = None


@dataclass
class DrillDownFormatResult:
    """Formatted drill-down search results."""

    results: list[dict] = field(default_factory=list)
    levels_traversed: list[str] = field(default_factory=list)
    total_results: int = 0


@dataclass
class LoadChildrenResult:
    """Result of paginated children loading."""

    children: list[Any] = field(default_factory=list)
    has_more: bool = False
    total_children: int = 0


@dataclass
class VideoGraphData:
    """Assembled video graph data."""

    video: dict | None = None
    scenes: list[Any] = field(default_factory=list)
    total_scenes: int = 0
    graph_stats: dict = field(default_factory=dict)
    error: str | None = None


@dataclass
class HealthCheckResult:
    """Result of a graph health check."""

    status: str
    connected: bool
    uri: str
    message: str


# =============================================================================
# Service
# =============================================================================


class GraphRouteService:
    """
    Service encapsulating business logic for Knowledge Graph route handlers.

    All dependencies are injected via the constructor so the class is easily
    testable. Methods never raise HTTP-specific exceptions — they return
    result data-classes; the route handler maps errors to ``HTTPException``.
    """

    def __init__(
        self,
        knowledge_graph_service: KnowledgeGraphService | None = None,
        graph_search_service: GraphSearchService | None = None,
    ) -> None:
        self._kg = knowledge_graph_service
        self._search = graph_search_service

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    @staticmethod
    def check_graph_health(service: KnowledgeGraphService) -> HealthCheckResult:
        """Check Neo4j connectivity and return a structured result."""
        connected = service.is_connected
        if not connected:
            connected = service.connect()

        return HealthCheckResult(
            status="healthy" if connected else "unhealthy",
            connected=connected,
            uri=service.uri,
            message=("Neo4j connection is active" if connected else "Failed to connect to Neo4j"),
        )

    # ------------------------------------------------------------------
    # Advanced Search Orchestration
    # ------------------------------------------------------------------

    def advanced_search(
        self,
        query: GraphSearchQuery,
        knowledge_graph_service: KnowledgeGraphService | None = None,
    ) -> AdvancedSearchResult:
        """Execute advanced multi-signal search with optional graph expansion.

        Pipeline
        --------
        1. Full-text search across entities and frames
        2. Optional graph expansion on top-10 results
        3. Score aggregation and result construction
        """
        service = knowledge_graph_service or self._kg
        if service is None:
            return AdvancedSearchResult(error="Knowledge graph service not available")

        start_time = time.time()

        # 1. Base search (full-text) -------------------------------------------
        base_results: list[dict] = []

        if not query.node_types or NodeType.ENTITY in query.node_types:
            entity_results = service.search_entities(
                query_text=query.query,
                entity_types=query.entity_types,
                video_id=query.video_ids[0] if query.video_ids else None,
                limit=query.limit,
            )
            for r in entity_results:
                base_results.append(
                    {
                        "node_id": r["entity"].get("id"),
                        "node_type": NodeType.ENTITY,
                        "content": r["entity"],
                        "vector_score": r["score"],
                    }
                )

        if not query.node_types or NodeType.FRAME in query.node_types:
            frame_results = service.search_frames_by_description(
                query_text=query.query,
                video_id=query.video_ids[0] if query.video_ids else None,
                time_range=query.time_range,
                limit=query.limit,
            )
            for r in frame_results:
                base_results.append(
                    {
                        "node_id": r["frame"].get("id"),
                        "node_type": NodeType.FRAME,
                        "content": r["frame"],
                        "vector_score": r["score"],
                    }
                )

        vector_search_time = (time.time() - start_time) * 1000

        # 2. Graph expansion ---------------------------------------------------
        graph_expansion_time = 0.0
        if query.use_graph_expansion and base_results:
            expansion_start = time.time()
            for result in base_results[:10]:
                try:
                    expansion = service.expand_context(
                        node_id=result["node_id"],
                        hops=query.expansion_hops,
                        max_nodes=20,
                    )
                    nodes_by_distance = expansion.get("nodes_by_distance", {})
                    result["related_nodes"] = [
                        node for nodes in nodes_by_distance.values() for node in nodes
                    ]
                except Exception:
                    result["related_nodes"] = []
            graph_expansion_time = (time.time() - expansion_start) * 1000

        # 3. Build response ----------------------------------------------------
        search_results = [
            GraphSearchResult(
                node_id=r["node_id"],
                node_type=r["node_type"],
                vector_score=r.get("vector_score", 0),
                graph_score=0,
                combined_score=r.get("vector_score", 0),
                content=r["content"],
                related_nodes=r.get("related_nodes", []),
            )
            for r in base_results[: query.limit]
        ]

        total_time = (time.time() - start_time) * 1000

        return AdvancedSearchResult(
            response=GraphSearchResponse(
                query=query.query,
                total_results=len(search_results),
                results=search_results,
                search_time_ms=total_time,
                vector_search_time_ms=vector_search_time,
                graph_expansion_time_ms=graph_expansion_time,
            )
        )

    # ------------------------------------------------------------------
    # Video Graph Assembly
    # ------------------------------------------------------------------

    def get_video_graph_data(
        self,
        video_id: str,
        knowledge_graph_service: KnowledgeGraphService | None = None,
    ) -> VideoGraphData:
        """Assemble video node, scenes, and global stats.

        Returns ``VideoGraphData`` with ``error`` set when the video is
        not found or the service is unavailable.
        """
        service = knowledge_graph_service or self._kg
        if service is None:
            return VideoGraphData(error="Knowledge graph service not available")

        video = service.get_video_node(video_id)
        if not video:
            return VideoGraphData(error=f"Video '{video_id}' not found")

        scenes = service.get_video_scenes(video_id)
        stats = service.get_stats()

        return VideoGraphData(
            video=video,
            scenes=scenes,
            total_scenes=len(scenes),
            graph_stats=stats.model_dump(),
        )

    # ------------------------------------------------------------------
    # Cross-Video Search
    # ------------------------------------------------------------------

    @staticmethod
    def build_cross_video_results(similar_nodes: list[Any]) -> list[dict]:
        """Transform cross-video search result nodes for the API response."""
        return [
            {
                "node_id": n.node_id,
                "node_type": n.node_type.value,
                "video_id": n.video_id,
                "similarity": n.vector_score,
                "content": n.content,
            }
            for n in similar_nodes
        ]

    # ------------------------------------------------------------------
    # Embedding Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def determine_text_field(node_type: NodeType) -> str:
        """Return the text property name used for embedding generation."""
        if node_type == NodeType.ENTITY:
            return "name"
        if node_type == NodeType.AUDIO_SEGMENT:
            return "text"
        return "description"

    # ------------------------------------------------------------------
    # Hierarchy Processing
    # ------------------------------------------------------------------

    @staticmethod
    def build_hierarchy_metadata(
        video_id: str,
        title: str | None,
        fps: float,
        duration: float | None,
        resolution: tuple[int, int],
    ) -> dict:
        """Build the ``video_metadata`` dict expected by the hierarchy service."""
        return {
            "media_id": video_id,
            "video_id": video_id,
            "title": title or f"Video {video_id}",
            "fps": fps,
            "duration": duration or 0,
            "resolution": resolution,
            "file_size_bytes": 0,
            "format": "mp4",
        }

    # ------------------------------------------------------------------
    # Drill-Down Search Formatting
    # ------------------------------------------------------------------

    @staticmethod
    def format_drill_down_results(results: list[Any]) -> DrillDownFormatResult:
        """Format raw ``DrillDownResult`` objects into a response-ready shape."""
        formatted: list[dict] = []
        levels_traversed: set[str] = set()

        for result in results:
            levels_traversed.update(level.level for level in result.path_from_root)
            formatted.append(
                {
                    "current_level": {
                        "level": result.current_level.level,
                        "node_id": result.current_level.node_id,
                        "node_type": result.current_level.node_type.value,
                        "summary": result.current_level.summary,
                        "title": result.current_level.title,
                        "start_time": result.current_level.start_time,
                        "end_time": result.current_level.end_time,
                    },
                    "path": [
                        {
                            "level": level.level,
                            "node_id": level.node_id,
                            "title": level.title,
                        }
                        for level in result.path_from_root
                    ],
                    "has_more_levels": result.has_more_levels,
                }
            )

        return DrillDownFormatResult(
            results=formatted,
            levels_traversed=list(levels_traversed),
            total_results=len(formatted),
        )

    # ------------------------------------------------------------------
    # Load Children Pagination
    # ------------------------------------------------------------------

    @staticmethod
    def paginate_children(
        children: list[Any],
        requested_limit: int,
    ) -> LoadChildrenResult:
        """Apply *limit+1* pagination: detect ``has_more`` and trim."""
        has_more = len(children) > requested_limit
        if has_more:
            children = children[:requested_limit]

        return LoadChildrenResult(
            children=children,
            has_more=has_more,
            total_children=len(children),
        )

    # ------------------------------------------------------------------
    # Entity Extraction Formatting
    # ------------------------------------------------------------------

    @staticmethod
    def format_frame_extraction_result(result: Any) -> dict:
        """Format an ``ExtractionResult`` from image extraction."""
        return {
            "frame_id": result.frame_id,
            "timestamp": result.timestamp,
            "description": result.description,
            "entities": [e.model_dump() for e in result.entities],
            "relations": result.relations,
            "topics": result.topics,
            "actions": result.actions,
            "analysis_time_ms": result.analysis_time_ms,
        }

    @staticmethod
    def format_description_extraction_result(result: Any) -> dict:
        """Format an ``ExtractionResult`` from text description extraction."""
        return {
            "frame_id": result.frame_id,
            "timestamp": result.timestamp,
            "entities": [e.model_dump() for e in result.entities],
            "relations": result.relations,
            "topics": result.topics,
            "actions": result.actions,
            "analysis_time_ms": result.analysis_time_ms,
        }

    # ------------------------------------------------------------------
    # Shared Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def build_time_range(
        time_start: float | None,
        time_end: float | None,
    ) -> tuple[float, float] | None:
        """Build a ``(start, end)`` tuple when both bounds are provided."""
        if time_start is not None and time_end is not None:
            return (time_start, time_end)
        return None
