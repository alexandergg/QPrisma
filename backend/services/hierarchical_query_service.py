"""
Hierarchical Query Service for QPrisma
=======================================

Extracts all Neo4j read/query methods from HierarchicalContextService.
Provides drill-down search, hierarchy traversal, lazy loading, and statistics
for hierarchical video representations stored in the knowledge graph.

This service is read-only — it never writes to Neo4j.
"""

import asyncio
import logging
from dataclasses import dataclass

from models.graph_models import NodeType
from services.embedding_service import EmbeddingService
from services.knowledge_graph import KnowledgeGraphService

logger = logging.getLogger(__name__)


@dataclass
class HierarchyLevel:
    """Represents a level in the hierarchy with its data."""

    level: str  # video, chapter, scene, frame
    node_id: str
    node_type: NodeType
    embedding: list[float] | None = None
    summary: str | None = None
    title: str | None = None
    start_time: float = 0.0
    end_time: float = 0.0
    children_count: int = 0
    children_loaded: bool = False
    metadata: dict = None


@dataclass
class DrillDownResult:
    """Result of a drill-down search."""

    current_level: HierarchyLevel
    children: list[HierarchyLevel]
    path_from_root: list[HierarchyLevel]
    total_children: int
    has_more_levels: bool


class HierarchicalQueryService:
    """
    Read-only query service for hierarchical video context in Neo4j.

    Provides:
    - Drill-down search (video → chapter → scene) via vector similarity
    - Lazy loading of child nodes at any level
    - Hierarchy path traversal (root to target node)
    - Statistics for a video's hierarchical structure
    """

    def __init__(
        self,
        graph_service: KnowledgeGraphService,
        embedding_service: EmbeddingService,
    ):
        self.graph_service = graph_service
        self.embedding_service = embedding_service

    # =========================================================================
    # Drill-Down Search
    # =========================================================================

    async def drill_down_search(
        self,
        query_text: str,
        video_id: str | None = None,
        start_level: str = "video",
        target_level: str = "scene",
        top_k: int = 5,
        include_context: bool = True,
    ) -> list[DrillDownResult]:
        """
        Perform hierarchical drill-down search.

        Starts at a high level (video/chapter) and drills down to target level
        based on semantic relevance.

        Args:
            query_text: Search query
            video_id: Optional video ID to restrict search
            start_level: Level to start search (video, chapter, scene)
            target_level: Level to drill down to
            top_k: Number of results per level
            include_context: Whether to include surrounding context

        Returns:
            List of DrillDownResult with hierarchy path
        """
        query_embedding = await self.embedding_service.generate_embedding(query_text)

        results = []

        if start_level == "video":
            videos = await self._search_level(
                query_embedding=query_embedding,
                node_type=NodeType.VIDEO,
                video_id=video_id,
                top_k=top_k,
            )

            for video in videos:
                video_level = HierarchyLevel(
                    level="video",
                    node_id=video["id"],
                    node_type=NodeType.VIDEO,
                    summary=video.get("summary"),
                    title=video.get("title"),
                    start_time=0,
                    end_time=video.get("duration_seconds", 0),
                )

                if target_level == "video":
                    results.append(
                        DrillDownResult(
                            current_level=video_level,
                            children=[],
                            path_from_root=[video_level],
                            total_children=0,
                            has_more_levels=True,
                        )
                    )
                else:
                    chapters = await self._search_children(
                        parent_id=video["id"],
                        parent_type=NodeType.VIDEO,
                        child_type=NodeType.CHAPTER,
                        query_embedding=query_embedding,
                        top_k=top_k,
                    )

                    for chapter in chapters:
                        chapter_level = HierarchyLevel(
                            level="chapter",
                            node_id=chapter["id"],
                            node_type=NodeType.CHAPTER,
                            summary=chapter.get("summary"),
                            title=chapter.get("title"),
                            start_time=chapter.get("start_time", 0),
                            end_time=chapter.get("end_time", 0),
                        )

                        if target_level == "chapter":
                            results.append(
                                DrillDownResult(
                                    current_level=chapter_level,
                                    children=[],
                                    path_from_root=[video_level, chapter_level],
                                    total_children=0,
                                    has_more_levels=True,
                                )
                            )
                        else:
                            scenes = await self._search_children(
                                parent_id=chapter["id"],
                                parent_type=NodeType.CHAPTER,
                                child_type=NodeType.SCENE,
                                query_embedding=query_embedding,
                                top_k=top_k,
                            )

                            for scene in scenes:
                                scene_level = HierarchyLevel(
                                    level="scene",
                                    node_id=scene["id"],
                                    node_type=NodeType.SCENE,
                                    summary=scene.get("description"),
                                    start_time=scene.get("start_time", 0),
                                    end_time=scene.get("end_time", 0),
                                )

                                results.append(
                                    DrillDownResult(
                                        current_level=scene_level,
                                        children=[],
                                        path_from_root=[
                                            video_level,
                                            chapter_level,
                                            scene_level,
                                        ],
                                        total_children=0,
                                        has_more_levels=target_level == "frame",
                                    )
                                )

        return results

    async def _search_level(
        self,
        query_embedding: list[float],
        node_type: NodeType,
        video_id: str | None = None,
        top_k: int = 5,
    ) -> list[dict]:
        """Search for nodes at a specific level using vector similarity."""
        video_filter = "AND n.video_id = $video_id" if video_id else ""

        query = f"""
        MATCH (n:{node_type.value})
        WHERE n.embedding IS NOT NULL {video_filter}
        WITH n, gds.similarity.cosine(n.embedding, $query_embedding) AS score
        ORDER BY score DESC
        LIMIT $top_k
        RETURN n {{.*, score: score}}
        """

        try:
            params = {"query_embedding": query_embedding, "top_k": top_k}
            if video_id:
                params["video_id"] = video_id
            return await asyncio.to_thread(
                self.graph_service.execute_query, query, params, unpack_key="n"
            )
        except Exception as e:
            logger.warning(f"Vector search failed, using fallback: {e}")
            return await self._fallback_search(node_type, video_id, top_k)

    async def _search_children(
        self,
        parent_id: str,
        parent_type: NodeType,
        child_type: NodeType,
        query_embedding: list[float],
        top_k: int = 5,
    ) -> list[dict]:
        """Search for child nodes of a parent using vector similarity."""
        query = f"""
        MATCH (p:{parent_type.value})-[:CONTAINS]->(c:{child_type.value})
        WHERE p.id = $parent_id AND c.embedding IS NOT NULL
        WITH c, gds.similarity.cosine(c.embedding, $query_embedding) AS score
        ORDER BY score DESC
        LIMIT $top_k
        RETURN c {{.*, score: score}}
        """

        try:
            return await asyncio.to_thread(
                self.graph_service.execute_query,
                query,
                {"parent_id": parent_id, "query_embedding": query_embedding, "top_k": top_k},
                unpack_key="c",
            )
        except Exception as e:
            logger.warning(f"Child search failed: {e}")
            return []

    async def _fallback_search(
        self, node_type: NodeType, video_id: str | None, top_k: int
    ) -> list[dict]:
        """Fallback search when vector search is not available."""
        video_filter = "WHERE n.video_id = $video_id" if video_id else ""

        query = f"""
        MATCH (n:{node_type.value})
        {video_filter}
        RETURN n
        LIMIT $top_k
        """

        params = {"top_k": top_k}
        if video_id:
            params["video_id"] = video_id
        return await asyncio.to_thread(
            self.graph_service.execute_query, query, params, unpack_key="n"
        )

    # =========================================================================
    # Lazy Loading
    # =========================================================================

    async def load_children(
        self,
        node_id: str,
        node_type: NodeType,
        child_type: NodeType,
        offset: int = 0,
        limit: int = 10,
    ) -> list[HierarchyLevel]:
        """
        Lazy-load children of a node at the next level.

        Args:
            node_id: Parent node ID
            node_type: Type of the parent node
            child_type: Type of children to load
            offset: Pagination offset
            limit: Number of children to load

        Returns:
            List of HierarchyLevel for loaded children
        """
        query = f"""
        MATCH (p:{node_type.value})-[:CONTAINS]->(c:{child_type.value})
        WHERE p.id = $node_id
        ORDER BY c.start_time
        SKIP $offset
        LIMIT $limit
        """

        records = await asyncio.to_thread(
            self.graph_service.execute_query,
            query,
            {"node_id": node_id, "offset": offset, "limit": limit},
            unpack_key="c",
        )

        children = []
        for node in records:
            children.append(
                HierarchyLevel(
                    level=child_type.value.lower(),
                    node_id=node["id"],
                    node_type=child_type,
                    summary=node.get("summary") or node.get("description"),
                    title=node.get("title"),
                    start_time=node.get("start_time", 0),
                    end_time=node.get("end_time", 0),
                )
            )

        return children

    # =========================================================================
    # Hierarchy Traversal & Stats
    # =========================================================================

    async def get_hierarchy_path(self, node_id: str, node_type: NodeType) -> list[HierarchyLevel]:
        """
        Get the full path from root (video) to a specific node.

        Args:
            node_id: Target node ID
            node_type: Type of the target node

        Returns:
            List of HierarchyLevel from root to target
        """
        query = """
        MATCH path = (v:Video)-[:CONTAINS*0..3]->(n)
        WHERE n.id = $node_id
        RETURN nodes(path) as path_nodes
        """

        # Runs in a worker thread because it needs Neo4j Node objects with
        # .labels (frozenset) for _determine_level().
        def _run_path_query() -> list[HierarchyLevel]:
            with self.graph_service.get_session() as session:
                result = session.run(query, node_id=node_id)
                record = result.single()

                if not record:
                    return []

                path = []
                for node in record["path_nodes"]:
                    node_dict = dict(node)
                    level = self._determine_level(node.labels)
                    path.append(
                        HierarchyLevel(
                            level=level,
                            node_id=node_dict["id"],
                            node_type=NodeType(level.capitalize()),
                            summary=node_dict.get("summary") or node_dict.get("description"),
                            title=node_dict.get("title"),
                            start_time=node_dict.get("start_time", 0),
                            end_time=node_dict.get("end_time", 0),
                        )
                    )

                return path

        return await asyncio.to_thread(_run_path_query)

    def _determine_level(self, labels: frozenset) -> str:
        """Determine hierarchy level from Neo4j labels."""
        if "Video" in labels:
            return "video"
        elif "Chapter" in labels:
            return "chapter"
        elif "Scene" in labels:
            return "scene"
        elif "Frame" in labels:
            return "frame"
        return "unknown"

    async def get_hierarchy_stats(self, video_id: str) -> dict:
        """Get statistics about a video's hierarchy."""
        query = """
        MATCH (v:Video {video_id: $video_id})
        OPTIONAL MATCH (v)-[:CONTAINS]->(c:Chapter)
        OPTIONAL MATCH (c)-[:CONTAINS]->(s:Scene)
        OPTIONAL MATCH (s)-[:CONTAINS]->(f:Frame)
        RETURN
            v.title as video_title,
            v.duration_seconds as duration,
            count(DISTINCT c) as chapter_count,
            count(DISTINCT s) as scene_count,
            count(DISTINCT f) as frame_count,
            v.embedding IS NOT NULL as has_video_embedding
        """

        record = await asyncio.to_thread(
            self.graph_service.execute_query, query, {"video_id": video_id}, single=True
        )

        if not record:
            return {"error": "Video not found"}

        return {
            "video_id": video_id,
            "video_title": record["video_title"],
            "duration_seconds": record["duration"],
            "hierarchy": {
                "chapters": record["chapter_count"],
                "scenes": record["scene_count"],
                "frames": record["frame_count"],
            },
            "embeddings": {"video": record["has_video_embedding"]},
        }


# =============================================================================
# Singleton
# =============================================================================

_query_service: HierarchicalQueryService | None = None


def get_hierarchical_query_service() -> HierarchicalQueryService:
    """Get or create the singleton HierarchicalQueryService."""
    global _query_service
    if _query_service is None:
        from services.knowledge_graph import get_knowledge_graph_service

        _query_service = HierarchicalQueryService(
            graph_service=get_knowledge_graph_service(),
            embedding_service=EmbeddingService(),
        )
    return _query_service
