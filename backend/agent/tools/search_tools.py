"""
Search Tools
============

Tools for searching video content using hybrid search.
"""

import logging
from typing import Any

from agent.tools.base import BaseTool, ToolParameter, format_timestamp
from api.dependencies import get_graph_search_service
from models.graph_models import NodeType

logger = logging.getLogger(__name__)


class SearchVideoTool(BaseTool):
    """
    Search for specific content within a video.

    Uses hybrid search combining:
    - Vector similarity (semantic understanding)
    - Full-text search (keyword matching)
    - Graph proximity (related content)
    - Temporal relevance
    """

    name = "search_video"
    description = (
        "Search for specific moments, topics, objects, or spoken words in the video. "
        "Returns timestamped results with descriptions. "
        "Use this when the user asks about finding something specific in the video."
    )
    parameters = [
        ToolParameter(
            name="query",
            type="string",
            description="What to search for (e.g., 'when does he mention AI', 'scenes with cars', 'introduction')",
            required=True,
        ),
        ToolParameter(
            name="content_type",
            type="string",
            description="Type of content to search: 'all' for everything, 'visual' for scenes/frames, 'audio' for speech/transcript",
            required=False,
            enum=["all", "visual", "audio"],
            default="all",
        ),
        ToolParameter(
            name="time_range_start",
            type="number",
            description="Optional: Start of time range to search (in seconds)",
            required=False,
        ),
        ToolParameter(
            name="time_range_end",
            type="number",
            description="Optional: End of time range to search (in seconds)",
            required=False,
        ),
        ToolParameter(
            name="limit",
            type="integer",
            description="Maximum number of results to return (default: 5)",
            required=False,
            default=5,
        ),
    ]

    async def execute(
        self,
        media_id: str | None,
        query: str,
        content_type: str = "all",
        time_range_start: float | None = None,
        time_range_end: float | None = None,
        limit: int = 5,
        **kwargs,
    ) -> dict[str, Any]:
        """Execute video search."""
        if not media_id:
            return {
                "error": "No video context available. Please select a video first.",
                "results": [],
            }

        try:
            search_service = get_graph_search_service()

            # Ensure connection
            if not search_service.graph_service.is_connected:
                search_service.graph_service.connect()

            # Determine node types based on content_type
            if content_type == "visual":
                node_types = [NodeType.FRAME, NodeType.SCENE]
            elif content_type == "audio":
                node_types = [NodeType.AUDIO_SEGMENT]
            else:
                node_types = [NodeType.FRAME, NodeType.AUDIO_SEGMENT, NodeType.ENTITY]

            # Execute hybrid search
            search_response = search_service.hybrid_search(
                query_text=query,
                node_types=node_types,
                video_id=media_id,
                limit=limit * 2,  # Get more for filtering
                expansion_hops=1,
                use_reranking=True,
            )

            # Format results
            results = []
            for r in search_response.results:
                ts = r.content.get("timestamp", 0)

                # Filter by time range if specified
                if time_range_start is not None and ts < time_range_start:
                    continue
                if time_range_end is not None and ts > time_range_end:
                    continue

                if r.node_type == NodeType.FRAME:
                    results.append({
                        "timestamp": ts,
                        "timestamp_formatted": format_timestamp(ts),
                        "type": "visual",
                        "content": r.content.get("description", "")[:300],
                        "score": round(r.combined_score, 3),
                    })
                elif r.node_type == NodeType.AUDIO_SEGMENT:
                    results.append({
                        "timestamp": ts,
                        "timestamp_formatted": format_timestamp(ts),
                        "type": "audio",
                        "content": r.content.get("text", "")[:300],
                        "score": round(r.combined_score, 3),
                    })
                elif r.node_type == NodeType.ENTITY:
                    entity_name = r.content.get("name", "")
                    entity_type = r.content.get("type", "entity")
                    results.append({
                        "timestamp": ts or 0,
                        "timestamp_formatted": format_timestamp(ts or 0),
                        "type": "entity",
                        "content": f"{entity_type}: {entity_name}",
                        "score": round(r.combined_score, 3),
                    })

                if len(results) >= limit:
                    break

            return {
                "query": query,
                "total_found": search_response.total_results,
                "results": results,
                "search_time_ms": search_response.vector_search_time_ms,
            }

        except Exception as e:
            logger.error(f"Search error: {e}")
            return {
                "error": f"Search failed: {str(e)}",
                "results": [],
            }


class FindEntityTool(BaseTool):
    """
    Find occurrences of a specific entity (person, object, concept) in the video.
    """

    name = "find_entity"
    description = (
        "Find all occurrences of a specific person, object, or concept in the video. "
        "Returns timestamps where the entity appears or is mentioned. "
        "Use this when looking for a specific named thing."
    )
    parameters = [
        ToolParameter(
            name="entity_name",
            type="string",
            description="Name of the entity to find (e.g., 'John', 'car', 'machine learning')",
            required=True,
        ),
        ToolParameter(
            name="entity_type",
            type="string",
            description="Type of entity: 'person', 'object', 'concept', 'location', or 'any'",
            required=False,
            enum=["person", "object", "concept", "location", "any"],
            default="any",
        ),
    ]

    async def execute(
        self,
        media_id: str | None,
        entity_name: str,
        entity_type: str = "any",
        **kwargs,
    ) -> dict[str, Any]:
        """Find entity occurrences."""
        if not media_id:
            return {
                "error": "No video context available. Please select a video first.",
                "occurrences": [],
            }

        try:
            search_service = get_graph_search_service()

            if not search_service.graph_service.is_connected:
                search_service.graph_service.connect()

            # Search specifically for entities
            search_response = search_service.hybrid_search(
                query_text=entity_name,
                node_types=[NodeType.ENTITY, NodeType.FRAME, NodeType.AUDIO_SEGMENT],
                video_id=media_id,
                limit=20,
                expansion_hops=2,  # More hops to find related appearances
                use_reranking=True,
            )

            occurrences = []
            seen_timestamps = set()

            for r in search_response.results:
                ts = r.content.get("timestamp", 0)

                # Avoid duplicate timestamps
                ts_key = round(ts, 1)
                if ts_key in seen_timestamps:
                    continue
                seen_timestamps.add(ts_key)

                context = ""
                occurrence_type = "mentioned"

                if r.node_type == NodeType.ENTITY:
                    if entity_type != "any" and r.content.get("type", "").lower() != entity_type:
                        continue
                    context = f"Entity '{r.content.get('name')}' of type {r.content.get('type')}"
                    occurrence_type = "identified"
                elif r.node_type == NodeType.FRAME:
                    context = r.content.get("description", "")[:200]
                    occurrence_type = "visible"
                elif r.node_type == NodeType.AUDIO_SEGMENT:
                    context = r.content.get("text", "")[:200]
                    occurrence_type = "mentioned"

                occurrences.append({
                    "timestamp": ts,
                    "timestamp_formatted": format_timestamp(ts),
                    "occurrence_type": occurrence_type,
                    "context": context,
                    "confidence": round(r.combined_score, 3),
                })

            # Sort by timestamp
            occurrences.sort(key=lambda x: x["timestamp"])

            return {
                "entity": entity_name,
                "entity_type": entity_type,
                "total_occurrences": len(occurrences),
                "occurrences": occurrences[:10],  # Limit to top 10
            }

        except Exception as e:
            logger.error(f"Find entity error: {e}")
            return {
                "error": f"Entity search failed: {str(e)}",
                "occurrences": [],
            }


# Tool instances
search_video = SearchVideoTool()
find_entity = FindEntityTool()
