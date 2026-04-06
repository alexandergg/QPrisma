"""
Hierarchy Node Factory for QPrisma
====================================

Creates and manages Neo4j nodes and relationships for the video hierarchy
(chapters, scenes) including embedding storage and vector index management.

Extracted from :class:`HierarchicalContextService` to isolate graph-write
concerns from embedding generation and search orchestration.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from models.graph_models import RelationType

if TYPE_CHECKING:
    from models.graph_models import ChapterNode, NodeType, SceneNode
    from services.knowledge_graph import KnowledgeGraphService

logger = logging.getLogger(__name__)


class HierarchyNodeFactory:
    """Creates Neo4j nodes, relationships, and vector indexes for the video hierarchy.

    All write operations use batched UNWIND queries for efficiency.
    """

    def __init__(self, knowledge_graph: KnowledgeGraphService) -> None:
        self._kg = knowledge_graph

    # =========================================================================
    # Single Node Creation
    # =========================================================================

    def create_chapter_node(self, chapter: ChapterNode) -> str:
        """Create a single chapter node in Neo4j."""
        query = """
        MATCH (v:Video {video_id: $video_id})
        CREATE (c:Chapter {
            id: $id,
            video_id: $video_id,
            user_id: COALESCE($user_id, v.user_id),
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

        with self._kg._driver.session() as session:
            result = session.run(
                query,
                id=chapter.id,
                video_id=chapter.video_id,
                user_id=chapter.user_id,
                start_time=chapter.start_time,
                end_time=chapter.end_time,
                chapter_index=chapter.chapter_index,
                title=chapter.title,
                summary=chapter.summary,
                topics=chapter.topics,
            )
            return result.single()["id"]

    def create_scene_node(self, scene: SceneNode) -> str:
        """Create a single scene node in Neo4j."""
        query = """
        MATCH (v:Video {video_id: $video_id})
        CREATE (s:Scene {
            id: $id,
            video_id: $video_id,
            chapter_id: $chapter_id,
            user_id: COALESCE($user_id, v.user_id),
            start_time: $start_time,
            end_time: $end_time,
            scene_index: $scene_index,
            description: $description,
            created_at: datetime()
        })
        RETURN s.id as id
        """

        with self._kg._driver.session() as session:
            result = session.run(
                query,
                id=scene.id,
                video_id=scene.video_id,
                chapter_id=scene.chapter_id,
                user_id=scene.user_id,
                start_time=scene.start_time,
                end_time=scene.end_time,
                scene_index=scene.scene_index,
                description=scene.description,
            )
            return result.single()["id"]

    # =========================================================================
    # Batch Creation
    # =========================================================================

    def create_chapters_batch(self, chapters: list[dict]) -> None:
        """Create all chapter nodes in a single UNWIND transaction."""
        query = """
        UNWIND $batch AS ch
        MATCH (v:Video {video_id: ch.video_id})
        CREATE (c:Chapter {
            id: ch.id,
            video_id: ch.video_id,
            user_id: COALESCE(ch.user_id, v.user_id),
            start_time: ch.start_time,
            end_time: ch.end_time,
            chapter_index: ch.chapter_index,
            title: ch.title,
            summary: ch.summary,
            topics: ch.topics,
            created_at: datetime()
        })
        """
        with self._kg._driver.session() as session:
            session.run(query, batch=chapters)

    def create_scenes_batch(self, scenes: list[dict]) -> None:
        """Create all scene nodes in a single UNWIND transaction."""
        query = """
        UNWIND $batch AS sc
        MATCH (v:Video {video_id: sc.video_id})
        CREATE (s:Scene {
            id: sc.id,
            video_id: sc.video_id,
            chapter_id: sc.chapter_id,
            user_id: COALESCE(sc.user_id, v.user_id),
            start_time: sc.start_time,
            end_time: sc.end_time,
            scene_index: sc.scene_index,
            description: sc.description,
            created_at: datetime()
        })
        """
        with self._kg._driver.session() as session:
            session.run(query, batch=scenes)

    # =========================================================================
    # Relationships
    # =========================================================================

    def create_relationship(self, source_id: str, target_id: str, relation_type: RelationType):
        """Create a single relationship between two nodes."""
        query = f"""
        MATCH (a), (b)
        WHERE a.id = $source_id AND b.id = $target_id
        CREATE (a)-[r:{relation_type.value}]->(b)
        RETURN type(r) as rel_type
        """

        with self._kg._driver.session() as session:
            session.run(query, source_id=source_id, target_id=target_id)

    def create_relationships_batch(self, rels: list[dict], relation_type: RelationType) -> None:
        """Create multiple relationships of the same type in a single UNWIND transaction."""
        query = f"""
        UNWIND $batch AS rel
        MATCH (a), (b)
        WHERE a.id = rel.source_id AND b.id = rel.target_id
        CREATE (a)-[:{relation_type.value}]->(b)
        """
        with self._kg._driver.session() as session:
            session.run(query, batch=rels)

    # =========================================================================
    # Embeddings
    # =========================================================================

    def store_embedding_node(self, node_id: str, embedding: list[float], node_type: NodeType):
        """Store embedding for a single node (for vector index)."""
        query = """
        MATCH (n) WHERE n.id = $node_id
        SET n.embedding = $embedding
        RETURN n.id
        """

        with self._kg._driver.session() as session:
            session.run(query, node_id=node_id, embedding=embedding)

    def store_embeddings_batch(self, embeddings: list[dict]) -> None:
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
        with self._kg._driver.session() as session:
            session.run(query, batch=embeddings)

    # =========================================================================
    # Vector Indexes
    # =========================================================================

    async def ensure_vector_indexes(self) -> None:
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
                with self._kg._driver.session() as session:
                    session.run(query)
            except Exception as e:
                logger.debug(f"Index {index_name} may already exist: {e}")
