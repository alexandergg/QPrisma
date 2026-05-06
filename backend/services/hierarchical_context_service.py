"""
Hierarchical Context Service for QPrisma
=========================================

Integrates scene analysis, summarization, embeddings, and knowledge graph
to provide hierarchical video representation optimized for RAG.

Hierarchy:
    Video (1 embedding + summary)
      └── Chapters (N embeddings + summaries)
            └── Scenes (M embeddings + summaries)
                  └── Keyframes (K embeddings + descriptions)

Key Features:
- Multi-level embedding generation with pooling strategies
- Neo4j storage of hierarchical structure
- Drill-down search from video to frame level
- Lazy loading of deeper levels
- Embedding compression at higher levels
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from models.graph_models import ChapterNode, NodeType, RelationType, SceneNode, VideoNode
from services.embedding_service import EmbeddingService
from services.hierarchical_query_service import DrillDownResult, HierarchyLevel
from services.hierarchical_summarizer import HierarchicalSummarizer, SummaryConfig
from services.knowledge_graph import KnowledgeGraphService
from services.scene_analyzer import Scene, SceneAnalyzer, VideoStructure

logger = logging.getLogger(__name__)


class EmbeddingPoolStrategy(str, Enum):
    """Strategy for pooling embeddings at higher levels."""

    MEAN = "mean"  # Simple average
    WEIGHTED_MEAN = "weighted"  # Weighted by importance/duration
    MAX_POOL = "max"  # Element-wise max
    ATTENTION = "attention"  # Attention-weighted (requires model)
    SUMMARY_ONLY = "summary"  # Only use summary embedding


@dataclass
class HierarchicalConfig:
    """Configuration for hierarchical context encoding."""

    # Scene detection
    scene_threshold: float = 0.3
    min_scene_duration: float = 2.0
    max_scene_duration: float = 60.0
    keyframes_per_scene: int = 3

    # Chapter configuration
    max_scenes_per_chapter: int = 5

    # Embedding configuration
    embedding_dimensions: int = 3072
    pool_strategy: EmbeddingPoolStrategy = EmbeddingPoolStrategy.WEIGHTED_MEAN

    # Compression at higher levels (reduce dimensionality)
    compress_chapter_embeddings: bool = False
    compress_video_embeddings: bool = False
    compressed_dimensions: int = 1024

    # Summary configuration
    scene_summary_tokens: int = 200
    chapter_summary_tokens: int = 300
    video_summary_tokens: int = 500

    # Storage
    store_frame_embeddings: bool = True
    store_scene_embeddings: bool = True
    store_chapter_embeddings: bool = True
    store_video_embeddings: bool = True


class HierarchicalContextService:
    """
    Service for building and querying hierarchical video context.

    Integrates:
    - SceneAnalyzer for scene detection
    - HierarchicalSummarizer for summaries at each level
    - EmbeddingService for vector embeddings
    - KnowledgeGraphService for Neo4j storage and queries
    """

    def __init__(
        self,
        graph_service: KnowledgeGraphService | None = None,
        embedding_service: EmbeddingService | None = None,
        config: HierarchicalConfig | None = None,
    ):
        """Initialize the hierarchical context service."""
        self.graph_service = graph_service or KnowledgeGraphService()
        self.embedding_service = embedding_service or EmbeddingService()
        self.config = config or HierarchicalConfig()

        # Initialize sub-services
        self.scene_analyzer = SceneAnalyzer(
            scene_threshold=self.config.scene_threshold,
            min_scene_duration=self.config.min_scene_duration,
            max_scene_duration=self.config.max_scene_duration,
            keyframes_per_scene=self.config.keyframes_per_scene,
        )

        self.summarizer = HierarchicalSummarizer()

        # Compose focused helpers (lazy imports avoid circular dependencies)
        from services.hierarchical_query_service import HierarchicalQueryService
        from services.hierarchy_embedding_generator import HierarchyEmbeddingGenerator
        from services.hierarchy_node_factory import HierarchyNodeFactory

        self._embedding_generator = HierarchyEmbeddingGenerator(
            embedding_service=self.embedding_service,
            config=self.config,
        )
        self._node_factory = HierarchyNodeFactory(
            knowledge_graph=self.graph_service,
        )
        self._query_service = HierarchicalQueryService(
            graph_service=self.graph_service,
            embedding_service=self.embedding_service,
        )

        # Graph connection is managed at startup via FastAPI lifespan;
        # no lazy connect needed here.

    # =========================================================================
    # Embedding Generation & Pooling (delegated to HierarchyEmbeddingGenerator)
    # =========================================================================

    def _pool_embeddings(
        self,
        embeddings: list[list[float]],
        weights: list[float] | None = None,
        strategy: EmbeddingPoolStrategy | None = None,
    ) -> list[float]:
        """Pool multiple embeddings into a single embedding."""
        return self._embedding_generator.pool_embeddings(embeddings, weights, strategy)

    def _compress_embedding(self, embedding: list[float], target_dims: int) -> list[float]:
        """Compress embedding to lower dimensionality."""
        return self._embedding_generator.compress_embedding(embedding, target_dims)

    async def generate_scene_embedding(
        self, scene: Scene, frame_embeddings: list[list[float]] | None = None
    ) -> list[float]:
        """Generate embedding for a scene."""
        return await self._embedding_generator.generate_scene_embedding(scene, frame_embeddings)

    async def generate_chapter_embedding(
        self, chapter: dict, scene_embeddings: list[list[float]], scene_durations: list[float]
    ) -> list[float]:
        """Generate embedding for a chapter."""
        return await self._embedding_generator.generate_chapter_embedding(
            chapter, scene_embeddings, scene_durations
        )

    async def generate_video_embedding(
        self,
        structure: VideoStructure,
        chapter_embeddings: list[list[float]],
        chapter_durations: list[float],
    ) -> list[float]:
        """Generate embedding for entire video."""
        return await self._embedding_generator.generate_video_embedding(
            structure, chapter_embeddings, chapter_durations
        )

    def _build_scene_text(self, scene: Scene) -> str:
        """Build text representation for scene embedding."""
        return self._embedding_generator.build_scene_text(scene)

    def _build_chapter_text(self, chapter: dict) -> str:
        """Build text representation for chapter embedding."""
        return self._embedding_generator.build_chapter_text(chapter)

    def _build_video_text(self, structure: VideoStructure) -> str:
        """Build text representation for video embedding."""
        return self._embedding_generator.build_video_text(structure)

    # =========================================================================
    # Full Pipeline Processing
    # =========================================================================

    async def process_video_hierarchy(
        self,
        video_path: str,
        video_metadata: dict,
        frame_analyses: list[dict] | None = None,
        transcript_segments: list[dict] | None = None,
        progress_callback: Callable | None = None,
    ) -> dict:
        """
        Complete pipeline for hierarchical video processing.

        Steps:
        1. Analyze video structure (scenes, chapters)
        2. Generate hierarchical summaries
        3. Generate embeddings at each level
        4. Store in Neo4j knowledge graph

        Args:
            video_path: Path to video file
            video_metadata: Video metadata dict
            frame_analyses: Pre-computed frame analyses
            transcript_segments: Audio transcript segments
            progress_callback: Optional callback for progress updates

        Returns:
            Dict with processing results and statistics
        """
        start_time = datetime.now(UTC)
        video_id = video_metadata.get("media_id", video_metadata.get("video_id", "unknown"))

        safe_video_id = str(video_id)[:100].replace("\r", "").replace("\n", "")
        logger.info("Starting hierarchical processing for video: %s", safe_video_id)

        result = {
            "video_id": video_id,
            "status": "processing",
            "levels_processed": {},
            "embeddings_generated": {},
            "nodes_created": {},
            "errors": [],
        }

        try:
            # Step 1: Analyze video structure
            if progress_callback:
                await progress_callback("analyzing_structure", 0.1)

            logger.info("Step 1: Analyzing video structure...")
            structure = await self.scene_analyzer.analyze_video_structure(
                video_path=video_path,
                video_metadata=video_metadata,
                frame_analyses=frame_analyses,
                transcript_segments=transcript_segments,
            )

            result["levels_processed"]["scenes"] = len(structure.scenes)
            result["levels_processed"]["chapters"] = len(structure.chapters)

            # Step 2: Generate hierarchical summaries
            if progress_callback:
                await progress_callback("generating_summaries", 0.3)

            logger.info("Step 2: Generating hierarchical summaries...")
            summary_config = SummaryConfig(
                scene_summary_max_tokens=self.config.scene_summary_tokens,
                chapter_summary_max_tokens=self.config.chapter_summary_tokens,
                video_summary_max_tokens=self.config.video_summary_tokens,
            )

            structure = await self.summarizer.process_video_hierarchy(
                structure=structure, config=summary_config
            )

            # Step 3: Generate embeddings at each level
            if progress_callback:
                await progress_callback("generating_embeddings", 0.5)

            logger.info("Step 3: Generating hierarchical embeddings...")

            # 3a: Scene embeddings
            scene_embeddings = []
            scene_durations = []

            for scene in structure.scenes:
                scene_emb = await self.generate_scene_embedding(scene)
                scene.embedding = scene_emb
                scene_embeddings.append(scene_emb)
                scene_durations.append(scene.duration)

            result["embeddings_generated"]["scenes"] = len(scene_embeddings)

            # 3b: Chapter embeddings
            chapter_embeddings = []
            chapter_durations = []

            for chapter in structure.chapters:
                # Get scene embeddings for this chapter
                chapter_scene_ids = set(chapter.get("scene_ids", []))
                chapter_scene_embs = [
                    scene_embeddings[i]
                    for i, s in enumerate(structure.scenes)
                    if s.scene_id in chapter_scene_ids
                ]
                chapter_scene_durs = [
                    scene_durations[i]
                    for i, s in enumerate(structure.scenes)
                    if s.scene_id in chapter_scene_ids
                ]

                chapter_emb = await self.generate_chapter_embedding(
                    chapter, chapter_scene_embs, chapter_scene_durs
                )
                chapter["embedding"] = chapter_emb
                chapter_embeddings.append(chapter_emb)
                chapter_durations.append(chapter.get("duration", 0))

            result["embeddings_generated"]["chapters"] = len(chapter_embeddings)

            # 3c: Video embedding
            video_embedding = await self.generate_video_embedding(
                structure, chapter_embeddings, chapter_durations
            )
            result["embeddings_generated"]["video"] = 1

            # Step 4: Store in Neo4j
            if progress_callback:
                await progress_callback("storing_graph", 0.7)

            logger.info("Step 4: Storing in Neo4j knowledge graph...")

            graph_result = await self._store_hierarchy_in_graph(
                structure=structure, video_metadata=video_metadata, video_embedding=video_embedding
            )

            result["nodes_created"] = graph_result

            # Step 5: Create vector indexes if needed
            if progress_callback:
                await progress_callback("creating_indexes", 0.9)

            await self._ensure_vector_indexes()

            # Done
            result["status"] = "completed"
            result["processing_time_seconds"] = (datetime.now(UTC) - start_time).total_seconds()

            logger.info("Hierarchical processing completed for %s", safe_video_id)

        except Exception as e:
            logger.exception("Hierarchical processing error")
            result["status"] = "failed"
            result["errors"].append(str(e))

        return result

    async def _store_hierarchy_in_graph(
        self, structure: VideoStructure, video_metadata: dict, video_embedding: list[float]
    ) -> dict:
        """Store the hierarchical structure in Neo4j using batched UNWIND operations."""
        counts = {"video": 0, "chapters": 0, "scenes": 0}

        # Create Video node
        video_node = VideoNode(
            video_id=structure.media_id,
            title=structure.video_title or video_metadata.get("title", "Untitled"),
            description=structure.video_summary,
            user_id=video_metadata.get("user_id"),
            duration_seconds=structure.total_duration,
            fps=video_metadata.get("fps", 30.0),
            resolution=video_metadata.get("resolution", (1920, 1080)),
            file_size_bytes=video_metadata.get("file_size_bytes", 0),
            format=video_metadata.get("format", "mp4"),
            total_frames=structure.total_frames,
            extracted_frames=sum(len(s.keyframe_indices) for s in structure.scenes),
            summary=structure.video_summary,
            topics=structure.key_topics or [],
            embedding=video_embedding if self.config.store_video_embeddings else None,
            embedding_model="text-embedding-3-large",
        )

        await asyncio.to_thread(self.graph_service.create_video_node, video_node)
        counts["video"] = 1

        # Store video embedding in vector index
        if self.config.store_video_embeddings and video_embedding:
            await asyncio.to_thread(
                self._node_factory.store_embedding_node,
                node_id=f"video:{structure.media_id}",
                embedding=video_embedding,
                node_type=NodeType.VIDEO,
            )

        # --- Batch create Chapter nodes + CONTAINS relationships ---
        chapter_node_ids = {}
        chapters_data = []
        chapter_rels = []
        chapter_embeddings = []

        for chapter in structure.chapters:
            chapter_node = ChapterNode(
                video_id=structure.media_id,
                user_id=video_node.user_id,
                start_time=chapter.get("start_time", 0),
                end_time=chapter.get("end_time", 0),
                chapter_index=chapter.get("chapter_id", 0),
                title=chapter.get("title"),
                summary=chapter.get("summary"),
                topics=chapter.get("themes", []),
                embedding=(
                    chapter.get("embedding") if self.config.store_chapter_embeddings else None
                ),
                embedding_model="text-embedding-3-large",
            )

            chapter_node_ids[chapter.get("chapter_id", 0)] = chapter_node.id
            chapters_data.append(
                {
                    "id": chapter_node.id,
                    "video_id": chapter_node.video_id,
                    "start_time": chapter_node.start_time,
                    "end_time": chapter_node.end_time,
                    "chapter_index": chapter_node.chapter_index,
                    "user_id": chapter_node.user_id,
                    "title": chapter_node.title,
                    "summary": chapter_node.summary,
                    "topics": chapter_node.topics,
                }
            )
            chapter_rels.append(
                {
                    "source_id": f"video:{structure.media_id}",
                    "target_id": chapter_node.id,
                }
            )

            if self.config.store_chapter_embeddings and chapter.get("embedding"):
                chapter_embeddings.append(
                    {
                        "node_id": chapter_node.id,
                        "embedding": chapter["embedding"],
                    }
                )

        if chapters_data:
            await asyncio.to_thread(self._node_factory.create_chapters_batch, chapters_data)
            await asyncio.to_thread(
                self._node_factory.create_relationships_batch,
                chapter_rels,
                RelationType.CONTAINS,
            )
            if chapter_embeddings:
                await asyncio.to_thread(
                    self._node_factory.store_embeddings_batch, chapter_embeddings
                )
            counts["chapters"] = len(chapters_data)

        # --- Batch create Scene nodes + CONTAINS relationships ---
        scenes_data = []
        scene_rels = []
        scene_embeddings = []

        for scene in structure.scenes:
            chapter_id_for_scene = self._find_chapter_for_scene(
                scene, structure.chapters, chapter_node_ids
            )

            scene_node = SceneNode(
                video_id=structure.media_id,
                chapter_id=chapter_id_for_scene,
                user_id=video_node.user_id,
                start_time=scene.start_time,
                end_time=scene.end_time,
                scene_index=scene.scene_id,
                description=scene.summary or scene.visual_description,
                embedding=scene.embedding if self.config.store_scene_embeddings else None,
                embedding_model="text-embedding-3-large",
                visual_change_score=getattr(scene, "visual_change_score", 0.0),
                dominant_colors=getattr(scene, "dominant_colors", None) or [],
                transition_type=getattr(scene, "transition_type", "cut"),
            )

            scenes_data.append(
                {
                    "id": scene_node.id,
                    "video_id": scene_node.video_id,
                    "chapter_id": scene_node.chapter_id,
                    "start_time": scene_node.start_time,
                    "end_time": scene_node.end_time,
                    "scene_index": scene_node.scene_index,
                    "user_id": scene_node.user_id,
                    "description": scene_node.description,
                }
            )

            if chapter_id_for_scene:
                scene_rels.append(
                    {
                        "source_id": chapter_id_for_scene,
                        "target_id": scene_node.id,
                    }
                )

            if self.config.store_scene_embeddings and scene.embedding:
                scene_embeddings.append(
                    {
                        "node_id": scene_node.id,
                        "embedding": scene.embedding,
                    }
                )

        if scenes_data:
            await asyncio.to_thread(self._node_factory.create_scenes_batch, scenes_data)
            if scene_rels:
                await asyncio.to_thread(
                    self._node_factory.create_relationships_batch,
                    scene_rels,
                    RelationType.CONTAINS,
                )
            if scene_embeddings:
                await asyncio.to_thread(self._node_factory.store_embeddings_batch, scene_embeddings)
            counts["scenes"] = len(scenes_data)

        return counts

    def _find_chapter_for_scene(
        self, scene: Scene, chapters: list[dict], chapter_node_ids: dict
    ) -> str | None:
        """Find the chapter that contains this scene."""
        for chapter in chapters:
            if scene.scene_id in chapter.get("scene_ids", []):
                return chapter_node_ids.get(chapter.get("chapter_id"))
        return None

    # =========================================================================
    # Neo4j Node Operations (delegated to HierarchyNodeFactory)
    # =========================================================================

    async def _ensure_vector_indexes(self):
        """Ensure vector indexes exist for all hierarchy levels (full + coarse)."""
        await self._node_factory.ensure_vector_indexes()

    # =========================================================================
    # Query Methods (delegated to HierarchicalQueryService)
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
        """Perform hierarchical drill-down search. Delegated to HierarchicalQueryService."""
        return await self._query_service.drill_down_search(
            query_text=query_text,
            video_id=video_id,
            start_level=start_level,
            target_level=target_level,
            top_k=top_k,
            include_context=include_context,
        )

    async def load_children(
        self,
        node_id: str,
        node_type: NodeType,
        child_type: NodeType,
        offset: int = 0,
        limit: int = 10,
    ) -> list[HierarchyLevel]:
        """Lazy-load children of a node. Delegated to HierarchicalQueryService."""
        return await self._query_service.load_children(
            node_id=node_id,
            node_type=node_type,
            child_type=child_type,
            offset=offset,
            limit=limit,
        )

    async def get_hierarchy_path(self, node_id: str, node_type: NodeType) -> list[HierarchyLevel]:
        """Get full path from root to a specific node. Delegated to HierarchicalQueryService."""
        return await self._query_service.get_hierarchy_path(node_id, node_type)

    async def get_hierarchy_stats(self, video_id: str) -> dict:
        """Get statistics about a video's hierarchy. Delegated to HierarchicalQueryService."""
        return await self._query_service.get_hierarchy_stats(video_id)


# =============================================================================
# Singleton
# =============================================================================

_hierarchical_service: HierarchicalContextService | None = None


def get_hierarchical_context_service(
    graph_service: KnowledgeGraphService | None = None,
    embedding_service: EmbeddingService | None = None,
) -> HierarchicalContextService:
    """Get singleton instance of HierarchicalContextService."""
    global _hierarchical_service
    if _hierarchical_service is None:
        _hierarchical_service = HierarchicalContextService(
            graph_service=graph_service, embedding_service=embedding_service
        )
    return _hierarchical_service
