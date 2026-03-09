"""
Graph Node Repository for QPrisma

Encapsulates all CRUD operations for graph nodes (Video, Scene, Frame, Entity,
AudioSegment) and relations.  Receives a callable that executes Cypher queries
so it stays decoupled from connection management.
"""

import logging
from collections import defaultdict
from collections.abc import Callable

from models.graph_models import (
    AudioSegmentNode,
    EntityNode,
    EntityType,
    FrameNode,
    RelationType,
    SceneNode,
    VideoNode,
)

logger = logging.getLogger(__name__)

# Type alias for the session context-manager factory used by CRUD helpers
# that need raw session access (batch writes, etc.).
SessionFactory = Callable


class GraphNodeRepository:
    """
    CRUD operations for Knowledge-Graph nodes and relations.

    Parameters
    ----------
    execute_query_fn:
        ``KnowledgeGraphService._execute_query`` (or compatible callable).
    get_session_fn:
        ``KnowledgeGraphService.get_session`` context-manager factory so that
        batch helpers can run multiple statements within one session.
    """

    def __init__(
        self,
        execute_query_fn: Callable,
        get_session_fn: SessionFactory,
    ):
        self._execute_query = execute_query_fn
        self._get_session = get_session_fn

    # =====================================================================
    # Video Node Operations
    # =====================================================================

    def create_video_node(self, video: VideoNode) -> str:
        """Create a Video node in the graph."""
        query = """
        CREATE (v:Video {
            id: $id,
            video_id: $video_id,
            title: $title,
            description: $description,
            duration_seconds: $duration_seconds,
            fps: $fps,
            resolution: $resolution,
            file_size_bytes: $file_size_bytes,
            format: $format,
            total_frames: $total_frames,
            extracted_frames: $extracted_frames,
            ai_summary: $ai_summary,
            topics: $topics,
            blob_url: $blob_url,
            thumbnail_url: $thumbnail_url,
            created_at: datetime($created_at),
            updated_at: datetime($updated_at)
        })
        RETURN v.id as id
        """

        with self._get_session() as session:
            result = session.run(
                query,
                id=video.id,
                video_id=video.video_id,
                title=video.title,
                description=video.description,
                duration_seconds=video.duration_seconds,
                fps=video.fps,
                resolution=list(video.resolution),
                file_size_bytes=video.file_size_bytes,
                format=video.format,
                total_frames=video.total_frames,
                extracted_frames=video.extracted_frames,
                ai_summary=video.ai_summary,
                topics=video.topics,
                blob_url=video.blob_url,
                thumbnail_url=video.thumbnail_url,
                created_at=video.created_at.isoformat(),
                updated_at=video.updated_at.isoformat(),
            )
            record = result.single()
            logger.info(f"Created Video node: {video.id}")
            return record["id"]

    def get_video_node(self, video_id: str) -> dict | None:
        """Retrieve a Video node by its video_id (or legacy id)."""
        query = """
        MATCH (v:Video)
        WHERE v.video_id = $video_id OR v.id = $video_id
        RETURN v
        """
        return self._execute_query(query, {"video_id": video_id}, single=True, unpack_key="v")

    def get_video_summary(self, video_id: str) -> tuple[str | None, list[str]]:
        """Get video summary and topics from the knowledge graph.

        Returns:
            Tuple of (summary, topics_list). Summary may be None if not found.
        """
        query = """
        MATCH (v:Video)
        WHERE v.video_id = $media_id OR v.id = $media_id
        RETURN v.summary as summary, v.topics as topics
        """
        record = self._execute_query(query, {"media_id": video_id}, single=True)
        if record:
            summary = record.get("summary")
            topics = record.get("topics", [])
            if isinstance(topics, str):
                topics = [t.strip() for t in topics.split(",") if t.strip()]
            return summary, topics or []
        return None, []

    def update_video_summary(self, video_id: str, summary: str, topics: list[str]):
        """Update the AI summary and topics for a video."""
        query = """
        MATCH (v:Video {video_id: $video_id})
        SET v.ai_summary = $summary,
            v.topics = $topics,
            v.updated_at = datetime()
        RETURN v.id
        """
        self._execute_query(query, {"video_id": video_id, "summary": summary, "topics": topics})

    # =====================================================================
    # Scene Node Operations
    # =====================================================================

    def create_scene_node(self, scene: SceneNode) -> str:
        """Create a Scene node and connect it to its Video."""
        query = """
        MATCH (v:Video {video_id: $video_id})
        CREATE (s:Scene {
            id: $id,
            video_id: $video_id,
            start_time: $start_time,
            end_time: $end_time,
            scene_index: $scene_index,
            description: $description,
            dominant_colors: $dominant_colors,
            scene_type: $scene_type,
            transition_type: $transition_type,
            visual_change_score: $visual_change_score,
            created_at: datetime($created_at)
        })
        CREATE (v)-[:CONTAINS]->(s)
        RETURN s.id as id
        """

        with self._get_session() as session:
            result = session.run(
                query,
                id=scene.id,
                video_id=scene.video_id,
                start_time=scene.start_time,
                end_time=scene.end_time,
                scene_index=scene.scene_index,
                description=scene.description,
                dominant_colors=scene.dominant_colors,
                scene_type=scene.scene_type,
                transition_type=scene.transition_type,
                visual_change_score=scene.visual_change_score,
                created_at=scene.created_at.isoformat(),
            )
            record = result.single()
            return record["id"]

    def get_video_scenes(self, video_id: str) -> list[dict]:
        """Retrieve all scenes for a video, ordered by start time."""
        query = """
        MATCH (v:Video)-[:CONTAINS]->(s:Scene)
        WHERE v.video_id = $video_id OR v.id = $video_id
        RETURN s
        ORDER BY s.start_time
        """
        return self._execute_query(query, {"video_id": video_id}, unpack_key="s")

    def get_scene_frames(self, scene_id: str) -> list[dict]:
        """Retrieve all frames for a scene, ordered by timestamp."""
        query = """
        MATCH (s:Scene {id: $scene_id})-[:CONTAINS]->(f:Frame)
        RETURN f.id as id, f.timestamp as timestamp, f.description as description
        ORDER BY f.timestamp
        """
        return self._execute_query(query, {"scene_id": scene_id})

    def get_video_frames(self, video_id: str) -> list[dict]:
        """Retrieve all frames for a video together with their descriptions."""
        query = """
        MATCH (v:Video)-[:CONTAINS*1..2]->(f:Frame)
        WHERE v.video_id = $video_id OR v.id = $video_id
        RETURN DISTINCT f.id as id, f.timestamp as timestamp, f.frame_number as frame_number,
               f.description as description, f.scene_id as scene_id
        ORDER BY f.timestamp
        """
        return self._execute_query(query, {"video_id": video_id})

    # =====================================================================
    # Frame Node Operations
    # =====================================================================

    def create_frame_node(self, frame: FrameNode) -> str:
        """Create a Frame node and connect it to its Scene (if present) or Video."""
        if frame.scene_id:
            query = """
            MATCH (s:Scene {id: $scene_id})
            CREATE (f:Frame {
                id: $id,
                video_id: $video_id,
                scene_id: $scene_id,
                timestamp: $timestamp,
                frame_number: $frame_number,
                description: $description,
                perceptual_hash: $perceptual_hash,
                content_hash: $content_hash,
                image_url: $image_url,
                blur_score: $blur_score,
                brightness: $brightness,
                is_keyframe: $is_keyframe,
                created_at: datetime($created_at)
            })
            CREATE (s)-[:CONTAINS]->(f)
            RETURN f.id as id
            """
        else:
            query = """
            MATCH (v:Video {video_id: $video_id})
            CREATE (f:Frame {
                id: $id,
                video_id: $video_id,
                timestamp: $timestamp,
                frame_number: $frame_number,
                description: $description,
                perceptual_hash: $perceptual_hash,
                content_hash: $content_hash,
                image_url: $image_url,
                blur_score: $blur_score,
                brightness: $brightness,
                is_keyframe: $is_keyframe,
                created_at: datetime($created_at)
            })
            CREATE (v)-[:CONTAINS]->(f)
            RETURN f.id as id
            """

        with self._get_session() as session:
            result = session.run(
                query,
                id=frame.id,
                video_id=frame.video_id,
                scene_id=frame.scene_id,
                timestamp=frame.timestamp,
                frame_number=frame.frame_number,
                description=frame.description,
                perceptual_hash=frame.perceptual_hash,
                content_hash=frame.content_hash,
                image_url=frame.image_url,
                blur_score=frame.blur_score,
                brightness=frame.brightness,
                is_keyframe=frame.is_keyframe,
                created_at=frame.created_at.isoformat(),
            )
            record = result.single()
            return record["id"]

    def create_frames_batch(self, frames: list[FrameNode]) -> int:
        """Create multiple Frame nodes in a single batch for better performance."""
        query = """
        UNWIND $frames as frame
        MATCH (v:Video {video_id: frame.video_id})
        CREATE (f:Frame {
            id: frame.id,
            video_id: frame.video_id,
            timestamp: frame.timestamp,
            frame_number: frame.frame_number,
            description: frame.description,
            perceptual_hash: frame.perceptual_hash,
            image_url: frame.image_url,
            is_keyframe: frame.is_keyframe,
            created_at: datetime(frame.created_at)
        })
        CREATE (v)-[:CONTAINS]->(f)
        RETURN count(f) as created
        """

        frames_data = [
            {
                "id": f.id,
                "video_id": f.video_id,
                "timestamp": f.timestamp,
                "frame_number": f.frame_number,
                "description": f.description,
                "perceptual_hash": f.perceptual_hash,
                "image_url": f.image_url,
                "is_keyframe": f.is_keyframe,
                "created_at": f.created_at.isoformat(),
            }
            for f in frames
        ]

        with self._get_session() as session:
            result = session.run(query, frames=frames_data)
            record = result.single()
            count = record["created"]
            logger.info(f"Created {count} Frame nodes in batch")
            return count

    # =====================================================================
    # Entity Node Operations
    # =====================================================================

    def create_entity_node(self, entity: EntityNode, frame_id: str) -> str:
        """Create an Entity node and connect it to the Frame where it was detected."""
        query = """
        MATCH (f:Frame {id: $frame_id})
        MERGE (e:Entity {normalized_name: $normalized_name, entity_type: $entity_type})
        ON CREATE SET
            e.id = $id,
            e.name = $name,
            e.description = $description,
            e.attributes = $attributes,
            e.confidence = $confidence,
            e.occurrence_count = 1,
            e.first_seen_time = f.timestamp,
            e.last_seen_time = f.timestamp,
            e.created_at = datetime($created_at)
        ON MATCH SET
            e.occurrence_count = e.occurrence_count + 1,
            e.last_seen_time = f.timestamp,
            e.confidence = CASE WHEN $confidence > e.confidence THEN $confidence ELSE e.confidence END
        CREATE (f)-[:CONTAINS {confidence: $confidence, bounding_box: $bounding_box}]->(e)
        RETURN e.id as id
        """

        with self._get_session() as session:
            result = session.run(
                query,
                id=entity.id,
                frame_id=frame_id,
                name=entity.name,
                normalized_name=entity.normalized_name,
                entity_type=entity.entity_type.value,
                description=entity.description,
                attributes=str(entity.attributes),  # Neo4j does not support nested maps directly
                confidence=entity.confidence,
                bounding_box=str(entity.bounding_box) if entity.bounding_box else None,
                created_at=entity.created_at.isoformat(),
            )
            record = result.single()
            return record["id"]

    def create_entities_batch(self, entities: list[tuple[EntityNode, str]]) -> int:
        """
        Create multiple Entity nodes in a single batch.

        Args:
            entities: List of (EntityNode, frame_id) tuples
        """
        query = """
        UNWIND $entities as entity
        MATCH (f:Frame {id: entity.frame_id})
        MERGE (e:Entity {normalized_name: entity.normalized_name, entity_type: entity.entity_type})
        ON CREATE SET
            e.id = entity.id,
            e.name = entity.name,
            e.description = entity.description,
            e.confidence = entity.confidence,
            e.occurrence_count = 1,
            e.first_seen_time = f.timestamp,
            e.created_at = datetime(entity.created_at)
        ON MATCH SET
            e.occurrence_count = e.occurrence_count + 1,
            e.last_seen_time = f.timestamp
        CREATE (f)-[:CONTAINS {confidence: entity.confidence}]->(e)
        RETURN count(e) as created
        """

        entities_data = [
            {
                "id": e.id,
                "frame_id": frame_id,
                "name": e.name,
                "normalized_name": e.normalized_name,
                "entity_type": e.entity_type.value,
                "description": e.description,
                "confidence": e.confidence,
                "created_at": e.created_at.isoformat(),
            }
            for e, frame_id in entities
        ]

        with self._get_session() as session:
            result = session.run(query, entities=entities_data)
            record = result.single()
            return record["created"]

    def get_entity_by_name(self, name: str, entity_type: EntityType | None = None) -> dict | None:
        """Look up an entity by its normalized name."""
        normalized = name.lower().strip()

        if entity_type:
            query = """
            MATCH (e:Entity {normalized_name: $name, entity_type: $type})
            RETURN e
            """
            params = {"name": normalized, "type": entity_type.value}
        else:
            query = """
            MATCH (e:Entity {normalized_name: $name})
            RETURN e
            """
            params = {"name": normalized}

        return self._execute_query(query, params, single=True, unpack_key="e")

    # =====================================================================
    # Audio Segment (Transcript) Operations
    # =====================================================================

    def create_audio_segment(self, segment: AudioSegmentNode) -> str:
        """Create an AudioSegment (transcript) node and connect it to its Video."""
        query = """
        MATCH (v:Video)
        WHERE v.video_id = $video_id OR v.id = $video_id
        CREATE (a:AudioSegment {
            id: $id,
            video_id: $video_id,
            start_time: $start_time,
            end_time: $end_time,
            text: $text,
            language: $language,
            confidence: $confidence,
            speaker_id: $speaker_id,
            speaker_label: $speaker_label,
            created_at: datetime($created_at)
        })
        CREATE (v)-[:HAS_TRANSCRIPT]->(a)
        RETURN a.id as id
        """

        with self._get_session() as session:
            result = session.run(
                query,
                id=segment.id,
                video_id=segment.video_id,
                start_time=segment.start_time,
                end_time=segment.end_time,
                text=segment.text,
                language=segment.language,
                confidence=segment.confidence,
                speaker_id=segment.speaker_id,
                speaker_label=segment.speaker_label,
                created_at=segment.created_at.isoformat(),
            )
            record = result.single()
            if record:
                return record["id"]
            return segment.id

    def create_audio_segments_batch(
        self, segments: list[AudioSegmentNode], batch_size: int = 100
    ) -> int:
        """
        Create multiple AudioSegment nodes in batches.

        Args:
            segments: List of AudioSegmentNode instances to create
            batch_size: Number of nodes per batch to avoid timeouts

        Returns:
            Total number of segments created
        """
        if not segments:
            return 0

        # Use MERGE to avoid duplicate errors
        query = """
        UNWIND $segments as seg
        MERGE (a:AudioSegment {id: seg.id})
        SET a.video_id = seg.video_id,
            a.start_time = seg.start_time,
            a.end_time = seg.end_time,
            a.text = seg.text,
            a.language = seg.language,
            a.confidence = seg.confidence,
            a.created_at = datetime(seg.created_at)
        WITH a, seg
        OPTIONAL MATCH (v:Video)
        WHERE v.video_id = seg.video_id OR v.id = seg.video_id
        FOREACH (_ IN CASE WHEN v IS NOT NULL THEN [1] ELSE [] END |
            MERGE (v)-[:HAS_TRANSCRIPT]->(a)
        )
        RETURN count(a) as created
        """

        total_created = 0

        # Process in batches to avoid timeouts on large volumes
        for i in range(0, len(segments), batch_size):
            batch = segments[i : i + batch_size]
            segments_data = [
                {
                    "id": s.id,
                    "video_id": s.video_id,
                    "start_time": s.start_time,
                    "end_time": s.end_time,
                    "text": s.text,
                    "language": s.language,
                    "confidence": s.confidence,
                    "created_at": s.created_at.isoformat(),
                }
                for s in batch
            ]

            try:
                with self._get_session() as session:
                    result = session.run(query, segments=segments_data)
                    record = result.single()
                    count = record["created"] if record else 0
                    total_created += count
            except Exception as e:
                logger.error(f"Failed to create batch {i // batch_size + 1}: {e}")
                # Continue with the next batch rather than failing completely
                continue

        logger.info(
            f"Created {total_created} AudioSegment nodes in "
            f"{(len(segments) + batch_size - 1) // batch_size} batches"
        )
        return total_created

    def get_video_transcripts(self, video_id: str) -> list[dict]:
        """Retrieve all transcript segments for a video."""
        query = """
        MATCH (v:Video)-[:HAS_TRANSCRIPT]->(a:AudioSegment)
        WHERE v.video_id = $video_id OR v.id = $video_id
        RETURN a.id as id, a.start_time as start_time, a.end_time as end_time,
               a.text as text, a.language as language, a.confidence as confidence
        ORDER BY a.start_time
        """
        return self._execute_query(query, {"video_id": video_id})

    def search_transcripts(
        self, query_text: str, video_id: str | None = None, limit: int = 20
    ) -> list[dict]:
        """
        Search audio transcripts for a given text.

        Args:
            query_text: Text to search for
            video_id: Filter to a specific video (optional)
            limit: Maximum number of results to return

        Returns:
            List of transcript segments that contain the text
        """
        if video_id:
            query = """
            MATCH (v:Video)-[:HAS_TRANSCRIPT]->(a:AudioSegment)
            WHERE (v.video_id = $video_id OR v.id = $video_id)
              AND toLower(a.text) CONTAINS toLower($query_text)
            RETURN a.id as id, a.video_id as video_id,
                   a.start_time as start_time, a.end_time as end_time,
                   a.text as text, a.language as language,
                   v.title as video_title
            ORDER BY a.start_time
            LIMIT $limit
            """
        else:
            query = """
            MATCH (v:Video)-[:HAS_TRANSCRIPT]->(a:AudioSegment)
            WHERE toLower(a.text) CONTAINS toLower($query_text)
            RETURN a.id as id, a.video_id as video_id,
                   a.start_time as start_time, a.end_time as end_time,
                   a.text as text, a.language as language,
                   v.title as video_title
            ORDER BY a.start_time
            LIMIT $limit
            """

        with self._get_session() as session:
            result = session.run(query, query_text=query_text, video_id=video_id, limit=limit)
            return [dict(record) for record in result]

    def delete_video_transcripts(self, video_id: str) -> int:
        """Delete all transcript segments for a video."""
        # Count first, then delete
        count_query = """
        MATCH (a:AudioSegment)
        WHERE a.video_id = $video_id
        RETURN count(a) as count
        """

        delete_query = """
        MATCH (a:AudioSegment)
        WHERE a.video_id = $video_id
        DETACH DELETE a
        """

        try:
            # Count before deleting
            result = self._execute_query(count_query, {"video_id": video_id}, single=True)
            count = result["count"] if result else 0

            if count > 0:
                # Delete in batches to avoid memory issues
                self._execute_query(delete_query, {"video_id": video_id})
                logger.info(f"Deleted {count} AudioSegment nodes for video {video_id}")

            return count
        except Exception as e:
            logger.error(f"Error deleting transcripts for video {video_id}: {e}")
            return 0

    # =====================================================================
    # Relation Operations
    # =====================================================================

    def create_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: RelationType,
        properties: dict | None = None,
    ) -> bool:
        """Create a relation between two nodes."""
        props = properties or {}
        props_string = ", ".join([f"{k}: ${k}" for k in props])

        query = f"""
        MATCH (a {{id: $source_id}})
        MATCH (b {{id: $target_id}})
        CREATE (a)-[r:{relation_type.value} {{{props_string}}}]->(b)
        RETURN type(r) as rel_type
        """

        params = {"source_id": source_id, "target_id": target_id, **props}

        with self._get_session() as session:
            result = session.run(query, **params)
            record = result.single()
            return record is not None

    def create_relations_batch(
        self,
        relations: list[dict],
    ) -> int:
        """
        Create multiple relations in batched UNWIND operations, grouped by type.

        Each dict in relations must have: source_id, target_id, relation_type (str),
        and optionally confidence (float) and evidence_count (int).

        Returns the total number of relations created.
        """
        grouped: dict[str, list[dict]] = defaultdict(list)
        for rel in relations:
            grouped[rel["relation_type"]].append(rel)

        total_created = 0
        for rel_type, rels in grouped.items():
            batch_data = [
                {
                    "source_id": r["source_id"],
                    "target_id": r["target_id"],
                    "confidence": r.get("confidence", 0.0),
                    "evidence_count": r.get("evidence_count", 0),
                }
                for r in rels
            ]

            query = f"""
            UNWIND $batch AS rel
            MATCH (a {{id: rel.source_id}})
            MATCH (b {{id: rel.target_id}})
            CREATE (a)-[r:{rel_type} {{
                confidence: rel.confidence,
                evidence_count: rel.evidence_count
            }}]->(b)
            RETURN count(r) as created
            """

            try:
                with self._get_session() as session:
                    result = session.run(query, batch=batch_data)
                    record = result.single()
                    total_created += record["created"] if record else 0
            except Exception as e:
                logger.error(f"Batch relation creation failed for type {rel_type}: {e}")

        return total_created

    def create_temporal_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: RelationType,
        time_gap: float | None = None,
    ):
        """Create a temporal relation between two nodes."""
        query = f"""
        MATCH (a {{id: $source_id}})
        MATCH (b {{id: $target_id}})
        CREATE (a)-[r:{relation_type.value} {{time_gap_seconds: $time_gap}}]->(b)
        RETURN type(r)
        """

        with self._get_session() as session:
            session.run(query, source_id=source_id, target_id=target_id, time_gap=time_gap)

    def create_entity_cooccurrence(self, frame_id: str):
        """
        Create APPEARS_WITH relations between entities that appear in the same frame.
        """
        query = """
        MATCH (f:Frame {id: $frame_id})-[:CONTAINS]->(e1:Entity)
        MATCH (f)-[:CONTAINS]->(e2:Entity)
        WHERE e1.id < e2.id
        MERGE (e1)-[r:APPEARS_WITH]-(e2)
        ON CREATE SET r.count = 1, r.frames = [$frame_id]
        ON MATCH SET r.count = r.count + 1, r.frames = r.frames + $frame_id
        RETURN count(r) as relations_created
        """

        with self._get_session() as session:
            result = session.run(query, frame_id=frame_id)
            record = result.single()
            return record["relations_created"]
