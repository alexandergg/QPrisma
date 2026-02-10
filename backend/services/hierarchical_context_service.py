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

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, UTC
from enum import Enum

import numpy as np

from models.graph_models import ChapterNode, NodeType, RelationType, SceneNode, VideoNode
from services.embedding_service import EmbeddingService
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

        # Ensure graph connection
        if not self.graph_service.is_connected:
            self.graph_service.connect()

    # =========================================================================
    # Embedding Generation & Pooling
    # =========================================================================

    def _pool_embeddings(
        self,
        embeddings: list[list[float]],
        weights: list[float] | None = None,
        strategy: EmbeddingPoolStrategy | None = None,
    ) -> list[float]:
        """
        Pool multiple embeddings into a single embedding.

        Args:
            embeddings: List of embeddings to pool
            weights: Optional weights for weighted averaging
            strategy: Pooling strategy to use

        Returns:
            Single pooled embedding
        """
        if not embeddings:
            return [0.0] * self.config.embedding_dimensions

        if len(embeddings) == 1:
            return embeddings[0]

        strategy = strategy or self.config.pool_strategy
        embeddings_array = np.array(embeddings)

        if strategy == EmbeddingPoolStrategy.MEAN:
            pooled = np.mean(embeddings_array, axis=0)

        elif strategy == EmbeddingPoolStrategy.WEIGHTED_MEAN:
            if weights is None:
                weights = [1.0] * len(embeddings)
            weights = np.array(weights) / sum(weights)
            pooled = np.average(embeddings_array, axis=0, weights=weights)

        elif strategy == EmbeddingPoolStrategy.MAX_POOL:
            pooled = np.max(embeddings_array, axis=0)

        else:  # Default to mean
            pooled = np.mean(embeddings_array, axis=0)

        # Normalize
        norm = np.linalg.norm(pooled)
        if norm > 0:
            pooled = pooled / norm

        return pooled.tolist()

    def _compress_embedding(self, embedding: list[float], target_dims: int) -> list[float]:
        """
        Compress embedding to lower dimensionality using PCA-like reduction.

        Simple approach: select evenly spaced dimensions.
        For production, use proper PCA or learned projection.
        """
        if len(embedding) <= target_dims:
            return embedding

        # Simple dimensionality reduction: select evenly spaced
        step = len(embedding) / target_dims
        indices = [int(i * step) for i in range(target_dims)]
        compressed = [embedding[i] for i in indices]

        # Normalize
        norm = np.linalg.norm(compressed)
        if norm > 0:
            compressed = (np.array(compressed) / norm).tolist()

        return compressed

    async def generate_scene_embedding(
        self, scene: Scene, frame_embeddings: list[list[float]] | None = None
    ) -> list[float]:
        """
        Generate embedding for a scene.

        Combines:
        1. Summary text embedding
        2. Pooled frame embeddings (if available)
        """
        embeddings_to_pool = []
        weights = []

        # Generate summary embedding (primary)
        summary_text = self._build_scene_text(scene)
        if summary_text:
            summary_embedding = await self.embedding_service.generate_embedding(summary_text)
            embeddings_to_pool.append(summary_embedding)
            weights.append(2.0)  # Higher weight for summary

        # Pool frame embeddings (secondary)
        if frame_embeddings:
            pooled_frames = self._pool_embeddings(frame_embeddings)
            embeddings_to_pool.append(pooled_frames)
            weights.append(1.0)

        if not embeddings_to_pool:
            return [0.0] * self.config.embedding_dimensions

        return self._pool_embeddings(embeddings_to_pool, weights)

    async def generate_chapter_embedding(
        self, chapter: dict, scene_embeddings: list[list[float]], scene_durations: list[float]
    ) -> list[float]:
        """
        Generate embedding for a chapter.

        Combines:
        1. Chapter summary embedding
        2. Weighted pool of scene embeddings (by duration)
        """
        embeddings_to_pool = []
        weights = []

        # Generate chapter summary embedding
        chapter_text = self._build_chapter_text(chapter)
        if chapter_text:
            chapter_embedding = await self.embedding_service.generate_embedding(chapter_text)
            embeddings_to_pool.append(chapter_embedding)
            weights.append(2.0)

        # Pool scene embeddings weighted by duration
        if scene_embeddings:
            pooled_scenes = self._pool_embeddings(
                scene_embeddings, scene_durations, EmbeddingPoolStrategy.WEIGHTED_MEAN
            )
            embeddings_to_pool.append(pooled_scenes)
            weights.append(1.0)

        result = self._pool_embeddings(embeddings_to_pool, weights)

        # Optionally compress
        if self.config.compress_chapter_embeddings:
            result = self._compress_embedding(result, self.config.compressed_dimensions)

        return result

    async def generate_video_embedding(
        self,
        structure: VideoStructure,
        chapter_embeddings: list[list[float]],
        chapter_durations: list[float],
    ) -> list[float]:
        """
        Generate embedding for entire video.

        Combines:
        1. Video summary embedding
        2. Weighted pool of chapter embeddings
        """
        embeddings_to_pool = []
        weights = []

        # Generate video summary embedding
        video_text = self._build_video_text(structure)
        if video_text:
            video_embedding = await self.embedding_service.generate_embedding(video_text)
            embeddings_to_pool.append(video_embedding)
            weights.append(2.0)

        # Pool chapter embeddings weighted by duration
        if chapter_embeddings:
            pooled_chapters = self._pool_embeddings(
                chapter_embeddings, chapter_durations, EmbeddingPoolStrategy.WEIGHTED_MEAN
            )
            embeddings_to_pool.append(pooled_chapters)
            weights.append(1.0)

        result = self._pool_embeddings(embeddings_to_pool, weights)

        # Optionally compress
        if self.config.compress_video_embeddings:
            result = self._compress_embedding(result, self.config.compressed_dimensions)

        return result

    def _build_scene_text(self, scene: Scene) -> str:
        """Build text representation for scene embedding."""
        parts = []

        if scene.title:
            parts.append(scene.title)
        if scene.summary:
            parts.append(scene.summary)
        if scene.visual_description:
            parts.append(f"Visual: {scene.visual_description}")
        if scene.transcript_segment:
            parts.append(f"Speech: {scene.transcript_segment[:500]}")
        if scene.detected_objects:
            parts.append(f"Contains: {', '.join(scene.detected_objects[:10])}")

        return " | ".join(parts) if parts else ""

    def _build_chapter_text(self, chapter: dict) -> str:
        """Build text representation for chapter embedding."""
        parts = []

        if chapter.get("title"):
            parts.append(chapter["title"])
        if chapter.get("summary"):
            parts.append(chapter["summary"])
        if chapter.get("themes"):
            parts.append(f"Themes: {', '.join(chapter['themes'])}")

        return " | ".join(parts) if parts else ""

    def _build_video_text(self, structure: VideoStructure) -> str:
        """Build text representation for video embedding."""
        parts = []

        if structure.video_title:
            parts.append(structure.video_title)
        if structure.video_summary:
            parts.append(structure.video_summary)
        if structure.key_topics:
            parts.append(f"Topics: {', '.join(structure.key_topics)}")

        return " | ".join(parts) if parts else ""

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

        logger.info(f"Starting hierarchical processing for video: {video_id}")

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

            logger.info(f"Hierarchical processing completed for {video_id}")

        except Exception as e:
            logger.error(f"Hierarchical processing error: {e}")
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
            duration_seconds=structure.total_duration,
            fps=video_metadata.get("fps", 30.0),
            resolution=video_metadata.get("resolution", (1920, 1080)),
            file_size_bytes=video_metadata.get("file_size_bytes", 0),
            format=video_metadata.get("format", "mp4"),
            total_frames=structure.total_frames,
            extracted_frames=sum(len(s.keyframe_indices) for s in structure.scenes),
            ai_summary=structure.video_summary,
            topics=structure.key_topics or [],
            embedding=video_embedding if self.config.store_video_embeddings else None,
            embedding_model="text-embedding-3-large",
        )

        self.graph_service.create_video_node(video_node)
        counts["video"] = 1

        # Store video embedding in vector index
        if self.config.store_video_embeddings and video_embedding:
            self._store_embedding_node(
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
            chapters_data.append({
                "id": chapter_node.id,
                "video_id": chapter_node.video_id,
                "start_time": chapter_node.start_time,
                "end_time": chapter_node.end_time,
                "chapter_index": chapter_node.chapter_index,
                "title": chapter_node.title,
                "summary": chapter_node.summary,
                "topics": chapter_node.topics,
            })
            chapter_rels.append({
                "source_id": f"video:{structure.media_id}",
                "target_id": chapter_node.id,
            })

            if self.config.store_chapter_embeddings and chapter.get("embedding"):
                chapter_embeddings.append({
                    "node_id": chapter_node.id,
                    "embedding": chapter["embedding"],
                })

        if chapters_data:
            self._create_chapters_batch(chapters_data)
            self._create_relationships_batch(chapter_rels, RelationType.CONTAINS)
            if chapter_embeddings:
                self._store_embeddings_batch(chapter_embeddings)
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
                start_time=scene.start_time,
                end_time=scene.end_time,
                scene_index=scene.scene_id,
                description=scene.summary or scene.visual_description,
                embedding=scene.embedding if self.config.store_scene_embeddings else None,
                embedding_model="text-embedding-3-large",
                visual_change_score=getattr(scene, 'visual_change_score', 0.0),
                dominant_colors=getattr(scene, 'dominant_colors', None) or [],
                transition_type=getattr(scene, 'transition_type', 'cut'),
            )

            scenes_data.append({
                "id": scene_node.id,
                "video_id": scene_node.video_id,
                "chapter_id": scene_node.chapter_id,
                "start_time": scene_node.start_time,
                "end_time": scene_node.end_time,
                "scene_index": scene_node.scene_index,
                "description": scene_node.description,
            })

            if chapter_id_for_scene:
                scene_rels.append({
                    "source_id": chapter_id_for_scene,
                    "target_id": scene_node.id,
                })

            if self.config.store_scene_embeddings and scene.embedding:
                scene_embeddings.append({
                    "node_id": scene_node.id,
                    "embedding": scene.embedding,
                })

        if scenes_data:
            self._create_scenes_batch(scenes_data)
            if scene_rels:
                self._create_relationships_batch(scene_rels, RelationType.CONTAINS)
            if scene_embeddings:
                self._store_embeddings_batch(scene_embeddings)
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

    def _create_chapter_node(self, chapter: ChapterNode) -> str:
        """Create a single chapter node in Neo4j."""
        query = """
        CREATE (c:Chapter {
            id: $id,
            video_id: $video_id,
            start_time: $start_time,
            end_time: $end_time,
            chapter_index: $chapter_index,
            title: $title,
            summary: $summary,
            topics: $topics,
            created_at: datetime()
        })
        RETURN c.id as id
        """

        with self.graph_service._driver.session() as session:
            result = session.run(
                query,
                id=chapter.id,
                video_id=chapter.video_id,
                start_time=chapter.start_time,
                end_time=chapter.end_time,
                chapter_index=chapter.chapter_index,
                title=chapter.title,
                summary=chapter.summary,
                topics=chapter.topics,
            )
            return result.single()["id"]

    def _create_chapters_batch(self, chapters: list[dict]) -> None:
        """Create all chapter nodes in a single UNWIND transaction."""
        query = """
        UNWIND $batch AS ch
        CREATE (c:Chapter {
            id: ch.id,
            video_id: ch.video_id,
            start_time: ch.start_time,
            end_time: ch.end_time,
            chapter_index: ch.chapter_index,
            title: ch.title,
            summary: ch.summary,
            topics: ch.topics,
            created_at: datetime()
        })
        """
        with self.graph_service._driver.session() as session:
            session.run(query, batch=chapters)

    def _create_scene_node(self, scene: SceneNode) -> str:
        """Create a single scene node in Neo4j."""
        query = """
        CREATE (s:Scene {
            id: $id,
            video_id: $video_id,
            chapter_id: $chapter_id,
            start_time: $start_time,
            end_time: $end_time,
            scene_index: $scene_index,
            description: $description,
            created_at: datetime()
        })
        RETURN s.id as id
        """

        with self.graph_service._driver.session() as session:
            result = session.run(
                query,
                id=scene.id,
                video_id=scene.video_id,
                chapter_id=scene.chapter_id,
                start_time=scene.start_time,
                end_time=scene.end_time,
                scene_index=scene.scene_index,
                description=scene.description,
            )
            return result.single()["id"]

    def _create_scenes_batch(self, scenes: list[dict]) -> None:
        """Create all scene nodes in a single UNWIND transaction."""
        query = """
        UNWIND $batch AS sc
        CREATE (s:Scene {
            id: sc.id,
            video_id: sc.video_id,
            chapter_id: sc.chapter_id,
            start_time: sc.start_time,
            end_time: sc.end_time,
            scene_index: sc.scene_index,
            description: sc.description,
            created_at: datetime()
        })
        """
        with self.graph_service._driver.session() as session:
            session.run(query, batch=scenes)

    def _create_relationship(self, source_id: str, target_id: str, relation_type: RelationType):
        """Create a single relationship between two nodes."""
        query = f"""
        MATCH (a), (b)
        WHERE a.id = $source_id AND b.id = $target_id
        CREATE (a)-[r:{relation_type.value}]->(b)
        RETURN type(r) as rel_type
        """

        with self.graph_service._driver.session() as session:
            session.run(query, source_id=source_id, target_id=target_id)

    def _create_relationships_batch(
        self, rels: list[dict], relation_type: RelationType
    ) -> None:
        """Create multiple relationships of the same type in a single UNWIND transaction."""
        query = f"""
        UNWIND $batch AS rel
        MATCH (a), (b)
        WHERE a.id = rel.source_id AND b.id = rel.target_id
        CREATE (a)-[:{relation_type.value}]->(b)
        """
        with self.graph_service._driver.session() as session:
            session.run(query, batch=rels)

    def _store_embedding_node(self, node_id: str, embedding: list[float], node_type: NodeType):
        """Store embedding for a single node (for vector index)."""
        query = """
        MATCH (n) WHERE n.id = $node_id
        SET n.embedding = $embedding
        RETURN n.id
        """

        with self.graph_service._driver.session() as session:
            session.run(query, node_id=node_id, embedding=embedding)

    def _store_embeddings_batch(self, embeddings: list[dict]) -> None:
        """Store full and coarse embeddings for multiple nodes in a single UNWIND transaction."""
        # Add coarse truncations
        for item in embeddings:
            emb = item.get("embedding", [])
            item["embedding_coarse"] = emb[:512] if len(emb) >= 512 else emb

        query = """
        UNWIND $batch AS item
        MATCH (n) WHERE n.id = item.node_id
        SET n.embedding = item.embedding,
            n.embedding_coarse = item.embedding_coarse
        """
        with self.graph_service._driver.session() as session:
            session.run(query, batch=embeddings)

    async def _ensure_vector_indexes(self):
        """Ensure vector indexes exist for all hierarchy levels (full + coarse)."""
        index_configs = [
            ("video_embedding_idx", "Video", "embedding", 3072),
            ("chapter_embedding_idx", "Chapter", "embedding", 3072),
            ("scene_embedding_idx", "Scene", "embedding", 3072),
            # Coarse Matryoshka indexes for fast filtering
            ("video_embedding_coarse_idx", "Video", "embedding_coarse", 512),
            ("chapter_embedding_coarse_idx", "Chapter", "embedding_coarse", 512),
            ("scene_embedding_coarse_idx", "Scene", "embedding_coarse", 512),
        ]

        for index_name, label, prop, dims in index_configs:
            try:
                query = f"""
                CREATE VECTOR INDEX {index_name} IF NOT EXISTS
                FOR (n:{label})
                ON n.{prop}
                OPTIONS {{
                    indexConfig: {{
                        `vector.dimensions`: {dims},
                        `vector.similarity_function`: 'cosine'
                    }}
                }}
                """
                with self.graph_service._driver.session() as session:
                    session.run(query)
            except Exception as e:
                logger.debug(f"Index {index_name} may already exist: {e}")

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
        # Generate query embedding
        query_embedding = await self.embedding_service.generate_embedding(query_text)

        results = []

        # Level 1: Find relevant videos
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
                    summary=video.get("ai_summary"),
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
                    # Drill down to chapters
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
                            # Drill down to scenes
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
                                        path_from_root=[video_level, chapter_level, scene_level],
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
        # Use parameterized query to prevent SQL injection
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
            with self.graph_service._driver.session() as session:
                params = {"query_embedding": query_embedding, "top_k": top_k}
                if video_id:
                    params["video_id"] = video_id
                result = session.run(query, **params)
                return [dict(record["n"]) for record in result]
        except Exception as e:
            # Fallback if GDS not available
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
            with self.graph_service._driver.session() as session:
                result = session.run(
                    query, parent_id=parent_id, query_embedding=query_embedding, top_k=top_k
                )
                return [dict(record["c"]) for record in result]
        except Exception as e:
            logger.warning(f"Child search failed: {e}")
            return []

    async def _fallback_search(
        self, node_type: NodeType, video_id: str | None, top_k: int
    ) -> list[dict]:
        """Fallback search when vector search is not available."""
        # Use parameterized query to prevent SQL injection
        video_filter = "WHERE n.video_id = $video_id" if video_id else ""

        query = f"""
        MATCH (n:{node_type.value})
        {video_filter}
        RETURN n
        LIMIT $top_k
        """

        with self.graph_service._driver.session() as session:
            params = {"top_k": top_k}
            if video_id:
                params["video_id"] = video_id
            result = session.run(query, **params)
            return [dict(record["n"]) for record in result]

    # =========================================================================
    # Lazy Loading
    # =========================================================================

    async def load_children(
        self, node_id: str, node_type: NodeType, limit: int = 20, offset: int = 0
    ) -> list[HierarchyLevel]:
        """
        Lazy load children of a node.

        Used for on-demand loading of deeper hierarchy levels.
        """
        child_type_map = {
            NodeType.VIDEO: NodeType.CHAPTER,
            NodeType.CHAPTER: NodeType.SCENE,
            NodeType.SCENE: NodeType.FRAME,
        }

        child_type = child_type_map.get(node_type)
        if not child_type:
            return []

        query = f"""
        MATCH (p)-[:CONTAINS]->(c:{child_type.value})
        WHERE p.id = $node_id
        RETURN c
        ORDER BY c.start_time
        SKIP $offset
        LIMIT $limit
        """

        with self.graph_service._driver.session() as session:
            result = session.run(query, node_id=node_id, offset=offset, limit=limit)

            children = []
            for record in result:
                node = dict(record["c"])
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

    async def get_hierarchy_path(self, node_id: str, node_type: NodeType) -> list[HierarchyLevel]:
        """
        Get the full path from root (video) to a specific node.

        Useful for breadcrumb navigation.
        """
        query = """
        MATCH path = (v:Video)-[:CONTAINS*0..3]->(n)
        WHERE n.id = $node_id
        RETURN nodes(path) as path_nodes
        """

        with self.graph_service._driver.session() as session:
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

    # =========================================================================
    # Statistics
    # =========================================================================

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

        with self.graph_service._driver.session() as session:
            result = session.run(query, video_id=video_id)
            record = result.single()

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
