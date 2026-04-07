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
    ChapterNode,
    CommunityNode,
    EntityNode,
    EntityType,
    FrameNode,
    RelationType,
    SceneNode,
    TopicNode,
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
            user_id: $user_id,
            title: $title,
            description: $description,
            duration_seconds: $duration_seconds,
            fps: $fps,
            resolution: $resolution,
            file_size_bytes: $file_size_bytes,
            format: $format,
            total_frames: $total_frames,
            extracted_frames: $extracted_frames,
            summary: $summary,
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
                user_id=video.user_id,
                title=video.title,
                description=video.description,
                duration_seconds=video.duration_seconds,
                fps=video.fps,
                resolution=list(video.resolution),
                file_size_bytes=video.file_size_bytes,
                format=video.format,
                total_frames=video.total_frames,
                extracted_frames=video.extracted_frames,
                summary=video.summary,
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

    def get_node_video_id(self, node_id: str) -> str | None:
        """Resolve the owning video_id for a graph node."""
        query = """
        MATCH (n {id: $node_id})
        CALL {
            WITH n
            WITH n WHERE n.video_id IS NOT NULL
            RETURN n.video_id AS video_id
            UNION
            WITH n
            MATCH (v:Video)-[:CONTAINS*0..5]->(n)
            RETURN v.video_id AS video_id
            UNION
            WITH n
            MATCH (v:Video)-[:ABOUT]->(n)
            RETURN v.video_id AS video_id
        }
        RETURN video_id
        LIMIT 1
        """
        record = self._execute_query(query, {"node_id": node_id}, single=True)
        if not record:
            return None
        return record.get("video_id")

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
        SET v.summary = $summary,
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
            user_id: COALESCE($user_id, v.user_id),
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
                user_id=scene.user_id,
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

    def create_chapter_node(self, chapter: ChapterNode) -> str:
        """Create a Chapter node and connect it to its Video and contained Scenes."""
        query = """
        MATCH (v:Video {video_id: $video_id})
        CREATE (ch:Chapter {
            id: $id,
            video_id: $video_id,
            user_id: COALESCE($user_id, v.user_id),
            start_time: $start_time,
            end_time: $end_time,
            chapter_index: $chapter_index,
            title: $title,
            summary: $summary,
            topics: $topics,
            detection_method: $detection_method,
            created_at: datetime($created_at)
        })
        CREATE (v)-[:CONTAINS]->(ch)
        WITH ch
        MATCH (s:Scene {video_id: $video_id})
        WHERE s.start_time >= $start_time AND s.end_time <= $end_time
        CREATE (ch)-[:CONTAINS]->(s)
        RETURN ch.id as id
        """

        with self._get_session() as session:
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
                detection_method=chapter.detection_method,
                created_at=chapter.created_at.isoformat(),
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
                user_id: COALESCE($user_id, s.user_id),
                timestamp: $timestamp,
                frame_number: $frame_number,
                description: $description,
                perceptual_hash: $perceptual_hash,
                content_hash: $content_hash,
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
                user_id: COALESCE($user_id, v.user_id),
                timestamp: $timestamp,
                frame_number: $frame_number,
                description: $description,
                perceptual_hash: $perceptual_hash,
                content_hash: $content_hash,
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
                user_id=frame.user_id,
                timestamp=frame.timestamp,
                frame_number=frame.frame_number,
                description=frame.description,
                perceptual_hash=frame.perceptual_hash,
                content_hash=frame.content_hash,
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
            user_id: COALESCE(frame.user_id, v.user_id),
            timestamp: frame.timestamp,
            frame_number: frame.frame_number,
            description: frame.description,
            perceptual_hash: frame.perceptual_hash,
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
                "user_id": f.user_id,
                "timestamp": f.timestamp,
                "frame_number": f.frame_number,
                "description": f.description,
                "perceptual_hash": f.perceptual_hash,
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
        MERGE (e:Entity {
            normalized_name: $normalized_name,
            entity_type: $entity_type,
            video_id: f.video_id
        })
        ON CREATE SET
            e.id = $id,
            e.name = $name,
            e.video_id = f.video_id,
            e.user_id = COALESCE($user_id, f.user_id),
            e.description = $description,
            e.description_list = CASE WHEN $description IS NOT NULL THEN [$description] ELSE [] END,
            e.attributes = $attributes,
            e.confidence = $confidence,
            e.occurrence_count = 1,
            e.first_seen_time = f.timestamp,
            e.last_seen_time = f.timestamp,
            e.created_at = datetime($created_at)
        ON MATCH SET
            e.occurrence_count = e.occurrence_count + 1,
            e.last_seen_time = f.timestamp,
            e.confidence = CASE WHEN $confidence > e.confidence THEN $confidence ELSE e.confidence END,
            e.description = CASE
                WHEN $description IS NOT NULL AND size($description) > size(coalesce(e.description, ''))
                THEN $description ELSE e.description END,
            e.description_list = CASE
                WHEN $description IS NOT NULL
                    AND NOT $description IN coalesce(e.description_list, [])
                    AND size(coalesce(e.description_list, [])) < 5
                THEN coalesce(e.description_list, []) + $description
                ELSE coalesce(e.description_list, []) END
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
                user_id=entity.user_id,
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
        MERGE (e:Entity {
            normalized_name: entity.normalized_name,
            entity_type: entity.entity_type,
            video_id: f.video_id
        })
        ON CREATE SET
            e.id = entity.id,
            e.name = entity.name,
            e.video_id = f.video_id,
            e.user_id = COALESCE(entity.user_id, f.user_id),
            e.description = entity.description,
            e.description_list = CASE WHEN entity.description IS NOT NULL THEN [entity.description] ELSE [] END,
            e.confidence = entity.confidence,
            e.occurrence_count = 1,
            e.first_seen_time = f.timestamp,
            e.created_at = datetime(entity.created_at)
        ON MATCH SET
            e.occurrence_count = e.occurrence_count + 1,
            e.last_seen_time = f.timestamp,
            e.description = CASE
                WHEN entity.description IS NOT NULL AND size(entity.description) > size(coalesce(e.description, ''))
                THEN entity.description ELSE e.description END,
            e.description_list = CASE
                WHEN entity.description IS NOT NULL
                    AND NOT entity.description IN coalesce(e.description_list, [])
                    AND size(coalesce(e.description_list, [])) < 5
                THEN coalesce(e.description_list, []) + entity.description
                ELSE coalesce(e.description_list, []) END
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
                "user_id": e.user_id,
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
            user_id: COALESCE($user_id, v.user_id),
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
                user_id=segment.user_id,
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
        WITH a, seg
        OPTIONAL MATCH (v:Video)
        WHERE v.video_id = seg.video_id OR v.id = seg.video_id
        SET a.video_id = seg.video_id,
            a.user_id = COALESCE(seg.user_id, v.user_id),
            a.start_time = seg.start_time,
            a.end_time = seg.end_time,
            a.text = seg.text,
            a.language = seg.language,
            a.confidence = seg.confidence,
            a.created_at = datetime(seg.created_at)
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
                    "user_id": s.user_id,
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

    def create_semantic_relations_batch(self, relations: list[dict]) -> int:
        """Create semantic relations between entities extracted by the LLM.

        Each dict must contain: source_name, target_name, relation_type, frame_id.
        Optional: description, timestamp.

        Entities are matched via the Frame they both belong to (CONTAINS edge)
        to avoid cross-video ambiguity.  Uses MERGE to deduplicate edges and
        increments ``evidence_count`` on repeated observations.
        """
        if not relations:
            return 0

        grouped: dict[str, list[dict]] = defaultdict(list)
        for rel in relations:
            grouped[rel["relation_type"]].append(rel)

        total_created = 0
        for rel_type, rels in grouped.items():
            batch_data = [
                {
                    "source_name": r["source_name"],
                    "target_name": r["target_name"],
                    "frame_id": r["frame_id"],
                    "description": r.get("description", ""),
                    "timestamp": r.get("timestamp", 0.0),
                    "weight": r.get("weight", 0.5),
                }
                for r in rels
            ]

            query = f"""
            UNWIND $batch AS rel
            MATCH (f:Frame {{id: rel.frame_id}})-[:CONTAINS]->(src:Entity)
            WHERE src.normalized_name = rel.source_name
            MATCH (f)-[:CONTAINS]->(tgt:Entity)
            WHERE tgt.normalized_name = rel.target_name AND tgt.id <> src.id
            MERGE (src)-[r:{rel_type}]->(tgt)
            ON CREATE SET
                r.description = rel.description,
                r.weight = rel.weight,
                r.evidence_count = 1,
                r.first_seen = rel.timestamp
            ON MATCH SET
                r.evidence_count = r.evidence_count + 1,
                r.weight = CASE WHEN rel.weight > r.weight THEN rel.weight ELSE r.weight END,
                r.last_seen = rel.timestamp
            RETURN count(r) as created
            """

            try:
                with self._get_session() as session:
                    result = session.run(query, batch=batch_data)
                    record = result.single()
                    total_created += record["created"] if record else 0
            except Exception as e:
                logger.error(f"Semantic relation creation failed for type {rel_type}: {e}")

        return total_created

    def resolve_cross_video_entities(self, video_id: str) -> int:
        """Find and link entities that likely represent the same real-world entity
        across different videos using name similarity.

        Creates SAME_ENTITY edges between entity pairs from different videos
        that share the same entity_type and have matching or overlapping
        normalized_names. Uses conservative matching to avoid false positives.

        Only compares entities from the given video_id against entities from
        other videos, so this is called once per newly processed video.
        """
        query = """
        MATCH (e1:Entity {video_id: $video_id})
        WHERE e1.user_id IS NOT NULL
        MATCH (e2:Entity)
        WHERE e2.video_id <> $video_id
          AND e2.user_id = e1.user_id
          AND e1.entity_type = e2.entity_type
          AND e1.id <> e2.id
          AND (
            e1.normalized_name = e2.normalized_name
            OR (size(e1.normalized_name) > 3 AND size(e2.normalized_name) > 3
                AND (e1.normalized_name CONTAINS e2.normalized_name
                     OR e2.normalized_name CONTAINS e1.normalized_name))
          )
        WITH e1, e2,
             CASE
               WHEN e1.normalized_name = e2.normalized_name THEN 1.0
               ELSE 0.7
             END AS similarity
        MERGE (e1)-[r:SAME_ENTITY]-(e2)
        ON CREATE SET
            r.similarity_score = similarity,
            r.source_video_id = e1.video_id,
            r.target_video_id = e2.video_id,
            r.created_at = datetime()
        ON MATCH SET
            r.similarity_score = CASE
                WHEN similarity > r.similarity_score
                THEN similarity ELSE r.similarity_score END
        RETURN count(r) as linked
        """

        with self._get_session() as session:
            result = session.run(query, video_id=video_id)
            record = result.single()
            count = record["linked"] if record else 0
            if count > 0:
                logger.info(f"Resolved {count} cross-video entity matches for video {video_id}")
            return count

    # =====================================================================
    # Dense Temporal Chain Operations
    # =====================================================================

    def create_frame_chain(self, video_id: str) -> int:
        """Create NEXT_FRAME edges between consecutive frames ordered by frame_number.

        Forms a linked list: f1 -[:NEXT_FRAME]-> f2 -[:NEXT_FRAME]-> f3 ...
        Idempotent — deletes existing chains before recreating.
        """
        # Delete existing chain for idempotent re-runs
        delete_query = """
        MATCH (:Frame {video_id: $video_id})-[r:NEXT_FRAME]->(:Frame)
        DELETE r
        RETURN count(r) AS deleted
        """
        create_query = """
        MATCH (f:Frame {video_id: $video_id})
        WITH f ORDER BY f.frame_number
        WITH collect(f) AS frames
        UNWIND range(0, size(frames) - 2) AS i
        WITH frames[i] AS current, frames[i + 1] AS next
        CREATE (current)-[:NEXT_FRAME]->(next)
        RETURN count(*) AS created
        """

        with self._get_session() as session:
            session.run(delete_query, video_id=video_id)
            result = session.run(create_query, video_id=video_id)
            record = result.single()
            count = record["created"] if record else 0
            logger.info(f"Created {count} NEXT_FRAME edges for video {video_id}")
            return count

    def create_segment_chain(self, video_id: str) -> int:
        """Create NEXT_SEGMENT edges between consecutive audio segments ordered by start_time.

        Forms a linked list: s1 -[:NEXT_SEGMENT]-> s2 -[:NEXT_SEGMENT]-> s3 ...
        Idempotent — deletes existing chains before recreating.
        """
        delete_query = """
        MATCH (:AudioSegment {video_id: $video_id})-[r:NEXT_SEGMENT]->(:AudioSegment)
        DELETE r
        RETURN count(r) AS deleted
        """
        create_query = """
        MATCH (a:AudioSegment {video_id: $video_id})
        WITH a ORDER BY a.start_time
        WITH collect(a) AS segments
        UNWIND range(0, size(segments) - 2) AS i
        WITH segments[i] AS current, segments[i + 1] AS next
        CREATE (current)-[:NEXT_SEGMENT]->(next)
        RETURN count(*) AS created
        """

        with self._get_session() as session:
            session.run(delete_query, video_id=video_id)
            result = session.run(create_query, video_id=video_id)
            record = result.single()
            count = record["created"] if record else 0
            logger.info(f"Created {count} NEXT_SEGMENT edges for video {video_id}")
            return count

    def create_scene_chain(self, video_id: str) -> int:
        """Create NEXT_SCENE edges between consecutive scenes ordered by scene_index.

        Forms a linked list: sc1 -[:NEXT_SCENE]-> sc2 -[:NEXT_SCENE]-> sc3 ...
        Idempotent — deletes existing chains before recreating.
        """
        delete_query = """
        MATCH (:Scene {video_id: $video_id})-[r:NEXT_SCENE]->(:Scene)
        DELETE r
        RETURN count(r) AS deleted
        """
        create_query = """
        MATCH (s:Scene {video_id: $video_id})
        WITH s ORDER BY s.scene_index
        WITH collect(s) AS scenes
        UNWIND range(0, size(scenes) - 2) AS i
        WITH scenes[i] AS current, scenes[i + 1] AS next
        CREATE (current)-[:NEXT_SCENE]->(next)
        RETURN count(*) AS created
        """

        with self._get_session() as session:
            session.run(delete_query, video_id=video_id)
            result = session.run(create_query, video_id=video_id)
            record = result.single()
            count = record["created"] if record else 0
            logger.info(f"Created {count} NEXT_SCENE edges for video {video_id}")
            return count

    # =====================================================================
    # Community Node Operations
    # =====================================================================

    def create_community_node(self, community: CommunityNode) -> str:
        """Create a Community node and link it to its Video with SUMMARIZES."""
        query = """
        MATCH (v:Video {video_id: $video_id})
        CREATE (c:Community {
            id: $id,
            community_id: $community_id,
            video_id: $video_id,
            user_id: COALESCE($user_id, v.user_id),
            title: $title,
            summary: $summary,
            themes: $themes,
            themes_text: $themes_text,
            member_entity_ids: $member_entity_ids,
            member_count: $member_count,
            time_span_start: $time_span_start,
            time_span_end: $time_span_end,
            level: $level,
            created_at: datetime(),
            updated_at: datetime()
        })
        CREATE (c)-[:SUMMARIZES]->(v)
        RETURN c.id as id
        """
        with self._get_session() as session:
            result = session.run(
                query,
                id=community.id,
                community_id=community.community_id,
                video_id=community.video_id,
                user_id=community.user_id,
                title=community.title,
                summary=community.summary,
                themes=community.themes,
                themes_text=", ".join(community.themes) if community.themes else "",
                member_entity_ids=community.member_entity_ids,
                member_count=community.member_count,
                time_span_start=community.time_span_start,
                time_span_end=community.time_span_end,
                level=community.level,
            )
            record = result.single()
            return record["id"] if record else community.id

    def create_communities_batch(self, communities: list[CommunityNode]) -> int:
        """Create multiple Community nodes in a single batch."""
        if not communities:
            return 0

        batch_data = [
            {
                "id": c.id,
                "community_id": c.community_id,
                "video_id": c.video_id,
                "user_id": c.user_id,
                "title": c.title,
                "summary": c.summary,
                "themes": c.themes,
                "themes_text": ", ".join(c.themes) if c.themes else "",
                "member_entity_ids": c.member_entity_ids,
                "member_count": c.member_count,
                "time_span_start": c.time_span_start,
                "time_span_end": c.time_span_end,
                "level": c.level,
            }
            for c in communities
        ]

        query = """
        UNWIND $communities AS comm
        MATCH (v:Video {video_id: comm.video_id})
        CREATE (c:Community {
            id: comm.id,
            community_id: comm.community_id,
            video_id: comm.video_id,
            user_id: COALESCE(comm.user_id, v.user_id),
            title: comm.title,
            summary: comm.summary,
            themes: comm.themes,
            themes_text: comm.themes_text,
            member_entity_ids: comm.member_entity_ids,
            member_count: comm.member_count,
            time_span_start: comm.time_span_start,
            time_span_end: comm.time_span_end,
            level: comm.level,
            created_at: datetime(),
            updated_at: datetime()
        })
        CREATE (c)-[:SUMMARIZES]->(v)
        RETURN count(c) as created
        """

        try:
            with self._get_session() as session:
                result = session.run(query, communities=batch_data)
                record = result.single()
                created = record["created"] if record else 0
                logger.info(f"Batch created {created} Community nodes")
                return created
        except Exception as e:
            logger.error(f"Batch community creation failed: {e}")
            return 0

    def link_entities_to_community(self, community_id: str, entity_ids: list[str]) -> int:
        """Create IN_COMMUNITY relationships from entities to a community."""
        if not entity_ids:
            return 0

        query = """
        UNWIND $entity_ids AS eid
        MATCH (e:Entity {id: eid})
        MATCH (c:Community {id: $community_id})
        CREATE (e)-[:IN_COMMUNITY]->(c)
        RETURN count(*) as linked
        """

        with self._get_session() as session:
            result = session.run(query, community_id=community_id, entity_ids=entity_ids)
            record = result.single()
            return record["linked"] if record else 0

    def get_video_communities(self, video_id: str) -> list[dict]:
        """Retrieve all communities for a video, ordered by member count."""
        query = """
        MATCH (c:Community {video_id: $video_id})
        RETURN c {
            .id, .community_id, .video_id, .title, .summary,
            .themes, .member_entity_ids, .member_count,
            .time_span_start, .time_span_end, .level
        } AS community
        ORDER BY c.member_count DESC
        """

        with self._get_session() as session:
            result = session.run(query, video_id=video_id)
            return [record["community"] for record in result]

    def get_community_members(self, community_id: str) -> list[dict]:
        """Retrieve all entities belonging to a community."""
        query = """
        MATCH (e:Entity)-[:IN_COMMUNITY]->(c:Community {id: $community_id})
        RETURN e {
            .id, .name, .normalized_name, .entity_type,
            .description, .occurrence_count,
            .first_seen_time, .last_seen_time
        } AS entity
        ORDER BY e.occurrence_count DESC
        """

        with self._get_session() as session:
            result = session.run(query, community_id=community_id)
            return [record["entity"] for record in result]

    def delete_video_communities(self, video_id: str) -> int:
        """Delete all Community nodes and their relationships for a video."""
        query = """
        MATCH (c:Community {video_id: $video_id})
        DETACH DELETE c
        RETURN count(c) as deleted
        """

        with self._get_session() as session:
            result = session.run(query, video_id=video_id)
            record = result.single()
            deleted = record["deleted"] if record else 0
            logger.info(f"Deleted {deleted} community nodes for video {video_id}")
            return deleted

    # =====================================================================
    # Topic Node Operations
    # =====================================================================

    def create_topic_nodes_batch(self, topics: list[TopicNode], video_id: str) -> int:
        """Create Topic nodes and link them to the Video.

        Uses MERGE on ``(video_id, normalized_name)`` so topics are unique per-video.
        Links each topic to the Video via an ABOUT relationship.
        """
        if not topics:
            return 0

        topics_data = [
            {
                "id": t.id,
                "name": t.name,
                "normalized_name": t.normalized_name,
                "description": t.description,
                "keywords": t.keywords,
                "relevance_score": t.relevance_score,
                "user_id": t.user_id,
                "created_at": t.created_at.isoformat(),
            }
            for t in topics
        ]

        query = """
        MATCH (v:Video {video_id: $video_id})
        UNWIND $topics AS topic
        MERGE (t:Topic {normalized_name: topic.normalized_name, video_id: $video_id})
        ON CREATE SET
            t.id = topic.id,
            t.name = topic.name,
            t.description = topic.description,
            t.keywords = topic.keywords,
            t.relevance_score = topic.relevance_score,
            t.user_id = COALESCE(topic.user_id, v.user_id),
            t.created_at = datetime(topic.created_at)
        ON MATCH SET
            t.relevance_score = CASE
                WHEN topic.relevance_score > t.relevance_score
                THEN topic.relevance_score ELSE t.relevance_score END
        WITH v, t
        MERGE (v)-[:ABOUT]->(t)
        RETURN count(t) as created
        """

        with self._get_session() as session:
            result = session.run(query, topics=topics_data, video_id=video_id)
            record = result.single()
            count = record["created"] if record else 0
            logger.info(f"Created {count} Topic nodes for video {video_id}")
            return count

    def link_entities_to_topics(self, video_id: str) -> int:
        """Link entities to topics based on matching keywords and names.

        Creates ABOUT edges from Entity → Topic when the entity name or
        description matches topic keywords or name.
        """
        query = """
        MATCH (v:Video {video_id: $video_id})-[:ABOUT]->(t:Topic)
        MATCH (e:Entity)
        WHERE e.video_id = $video_id
          AND (
            e.normalized_name CONTAINS t.normalized_name
            OR t.normalized_name CONTAINS e.normalized_name
            OR ANY(kw IN coalesce(t.keywords, []) WHERE e.normalized_name CONTAINS toLower(kw))
          )
        MERGE (e)-[:ABOUT]->(t)
        RETURN count(*) as linked
        """

        with self._get_session() as session:
            result = session.run(query, video_id=video_id)
            record = result.single()
            count = record["linked"] if record else 0
            logger.info(f"Linked {count} entity-topic pairs for video {video_id}")
            return count

    # =====================================================================
    # Agent-facing query methods
    # =====================================================================
    # These methods consolidate inline Cypher previously scattered across
    # agent tool files.  They keep the same query semantics but centralise
    # the statements for testability and reuse.

    def get_video_summary_data(self, video_id: str) -> dict | None:
        """Return video summary, title, topics, and duration in one query."""
        query = """
        MATCH (v:Video)
        WHERE v.video_id = $video_id OR v.id = $video_id
        RETURN v.summary AS summary, v.title AS title,
               v.topics AS topics, v.duration_seconds AS duration
        """
        return self._execute_query(query, {"video_id": video_id}, single=True)

    def get_transcript_segments(
        self,
        video_id: str,
        start_time: float | None = None,
        end_time: float | None = None,
    ) -> list[dict]:
        """Retrieve ordered transcript segments, optionally within a time range.

        Uses chain-walk via NEXT_SEGMENT when a range is specified, falling
        back to a property-based query when no chain is available.
        """
        if start_time is None and end_time is None:
            # Full transcript
            query = """
            MATCH (a:AudioSegment)
            WHERE a.video_id = $video_id
            RETURN a.start_time AS timestamp, a.text AS text,
                   a.speaker_label AS speaker, a.confidence AS confidence
            ORDER BY a.start_time
            """
            return self._execute_query(query, {"video_id": video_id})

        eff_start = start_time if start_time is not None else 0.0
        eff_end = end_time if end_time is not None else 999999.0

        # Try chain-walk from the first anchor in the range
        with self._get_session() as session:
            anchor_result = session.run(
                """
                MATCH (a:AudioSegment)
                WHERE a.video_id = $video_id
                  AND a.start_time >= $start_time AND a.start_time <= $end_time
                RETURN a.id AS id
                ORDER BY a.start_time
                LIMIT 1
                """,
                video_id=video_id,
                start_time=eff_start,
                end_time=eff_end,
            )
            anchor = anchor_result.single()

            if anchor:
                chain_result = session.run(
                    """
                    MATCH (start:AudioSegment {id: $anchor_id})
                    OPTIONAL MATCH path = (start)-[:NEXT_SEGMENT*0..100]->(n:AudioSegment)
                    WHERE n.start_time <= $end_time
                    WITH n ORDER BY n.start_time
                    RETURN n.start_time AS timestamp, n.text AS text,
                           n.speaker_label AS speaker, n.confidence AS confidence
                    """,
                    anchor_id=anchor["id"],
                    end_time=eff_end,
                )
                segments = [dict(r) for r in chain_result]
                if segments:
                    return segments

        # Fallback: property-based range query
        query = """
        MATCH (a:AudioSegment)
        WHERE a.video_id = $video_id
          AND a.start_time >= $start_time AND a.start_time <= $end_time
        RETURN a.start_time AS timestamp, a.text AS text,
               a.speaker_label AS speaker, a.confidence AS confidence
        ORDER BY a.start_time
        """
        return self._execute_query(
            query,
            {"video_id": video_id, "start_time": eff_start, "end_time": eff_end},
        )

    def get_nearest_frame(self, video_id: str, timestamp: float) -> dict | None:
        """Return the single frame closest to *timestamp*."""
        query = """
        MATCH (f:Frame)
        WHERE f.video_id = $video_id
        RETURN f.timestamp AS timestamp, f.description AS description
        ORDER BY abs(f.timestamp - $timestamp)
        LIMIT 1
        """
        return self._execute_query(
            query, {"video_id": video_id, "timestamp": timestamp}, single=True
        )

    def get_frames_in_window(
        self,
        video_id: str,
        start_time: float,
        end_time: float,
        center_timestamp: float | None = None,
    ) -> list[dict]:
        """Return frames within [start_time, end_time].

        Tries a chain-walk from the nearest anchor frame first, then falls
        back to a simple property-range query.
        """
        with self._get_session() as session:
            # Find anchor frame closest to center (or midpoint)
            center = center_timestamp if center_timestamp is not None else (start_time + end_time) / 2
            anchor_result = session.run(
                """
                MATCH (f:Frame)
                WHERE f.video_id = $video_id
                  AND f.timestamp >= $start_time AND f.timestamp <= $end_time
                RETURN f.id AS id, f.timestamp AS ts
                ORDER BY abs(f.timestamp - $center)
                LIMIT 1
                """,
                video_id=video_id,
                start_time=start_time,
                end_time=end_time,
                center=center,
            )
            anchor = anchor_result.single()

            if anchor:
                max_hops = max(int((end_time - start_time) / 2), 10)
                chain_result = session.run(
                    f"""
                    MATCH (anchor:Frame {{id: $anchor_id}})
                    OPTIONAL MATCH (prev:Frame)-[:NEXT_FRAME*1..{max_hops}]->(anchor)
                    WHERE prev.timestamp >= $start_time
                    WITH anchor, collect(DISTINCT prev) AS before_nodes
                    OPTIONAL MATCH (anchor)-[:NEXT_FRAME*1..{max_hops}]->(nxt:Frame)
                    WHERE nxt.timestamp <= $end_time
                    WITH anchor, before_nodes, collect(DISTINCT nxt) AS after_nodes
                    WITH before_nodes + [anchor] + after_nodes AS all_nodes
                    UNWIND all_nodes AS f
                    WITH DISTINCT f
                    RETURN f.timestamp AS timestamp, f.description AS description
                    ORDER BY f.timestamp
                    """,
                    anchor_id=anchor["id"],
                    start_time=start_time,
                    end_time=end_time,
                )
                frames = [dict(r) for r in chain_result]
                if frames:
                    return frames

        # Fallback: property-range query
        query = """
        MATCH (f:Frame)
        WHERE f.video_id = $video_id
          AND f.timestamp >= $start_time AND f.timestamp <= $end_time
        RETURN f.timestamp AS timestamp, f.description AS description
        ORDER BY f.timestamp
        """
        return self._execute_query(
            query,
            {"video_id": video_id, "start_time": start_time, "end_time": end_time},
        )

    def get_audio_in_window(
        self,
        video_id: str,
        start_time: float,
        end_time: float,
        center_timestamp: float | None = None,
    ) -> list[dict]:
        """Return audio segments within [start_time, end_time].

        Tries a chain-walk via NEXT_SEGMENT first, then falls back to
        a property-range query.
        """
        with self._get_session() as session:
            center = center_timestamp if center_timestamp is not None else (start_time + end_time) / 2
            anchor_result = session.run(
                """
                MATCH (a:AudioSegment)
                WHERE a.video_id = $video_id
                  AND a.start_time >= $start_time AND a.start_time <= $end_time
                RETURN a.id AS id
                ORDER BY abs(a.start_time - $center)
                LIMIT 1
                """,
                video_id=video_id,
                start_time=start_time,
                end_time=end_time,
                center=center,
            )
            anchor = anchor_result.single()

            if anchor:
                max_hops = max(int(end_time - start_time), 20)
                chain_result = session.run(
                    f"""
                    MATCH (anchor:AudioSegment {{id: $anchor_id}})
                    OPTIONAL MATCH (prev:AudioSegment)-[:NEXT_SEGMENT*1..{max_hops}]->(anchor)
                    WHERE prev.start_time >= $start_time
                    WITH anchor, collect(DISTINCT prev) AS before_nodes
                    OPTIONAL MATCH (anchor)-[:NEXT_SEGMENT*1..{max_hops}]->(nxt:AudioSegment)
                    WHERE nxt.start_time <= $end_time
                    WITH anchor, before_nodes, collect(DISTINCT nxt) AS after_nodes
                    WITH before_nodes + [anchor] + after_nodes AS all_nodes
                    UNWIND all_nodes AS a
                    WITH DISTINCT a
                    RETURN a.start_time AS timestamp, a.text AS text
                    ORDER BY a.start_time
                    """,
                    anchor_id=anchor["id"],
                    start_time=start_time,
                    end_time=end_time,
                )
                segments = [dict(r) for r in chain_result]
                if segments:
                    return segments

        # Fallback: property-range query
        query = """
        MATCH (a:AudioSegment)
        WHERE a.video_id = $video_id
          AND a.start_time >= $start_time AND a.start_time <= $end_time
        RETURN a.start_time AS timestamp, a.text AS text
        ORDER BY a.start_time
        """
        return self._execute_query(
            query,
            {"video_id": video_id, "start_time": start_time, "end_time": end_time},
        )

    def get_scene_at_timestamp(self, video_id: str, timestamp: float) -> dict | None:
        """Return the scene that contains *timestamp*."""
        query = """
        MATCH (s:Scene)
        WHERE s.video_id = $video_id
          AND s.start_time <= $timestamp AND s.end_time >= $timestamp
        RETURN s.start_time AS start_time, s.end_time AS end_time,
               s.description AS description, s.scene_type AS scene_type
        LIMIT 1
        """
        return self._execute_query(
            query, {"video_id": video_id, "timestamp": timestamp}, single=True
        )

    def find_entity_appearances(
        self, video_id: str, entity_name: str
    ) -> dict[str, list[dict]]:
        """Find visual and audio appearances of an entity.

        Returns ``{"visual": [...], "audio": [...]}``.
        """
        visual_query = """
        MATCH (e:Entity)<-[:CONTAINS]-(f:Frame)
        WHERE e.video_id = $video_id
          AND toLower(e.name) CONTAINS toLower($entity_name)
        RETURN e.name AS name, e.entity_type AS entity_type,
               f.timestamp AS timestamp, f.description AS description
        ORDER BY f.timestamp
        """
        visual = self._execute_query(
            visual_query, {"video_id": video_id, "entity_name": entity_name}
        )

        audio_query = """
        MATCH (a:AudioSegment)
        WHERE a.video_id = $video_id
          AND toLower(a.text) CONTAINS toLower($entity_name)
        RETURN a.start_time AS timestamp, a.text AS text
        ORDER BY a.start_time
        """
        audio = self._execute_query(
            audio_query, {"video_id": video_id, "entity_name": entity_name}
        )

        return {"visual": visual, "audio": audio}

    def get_moments_context(
        self,
        video_id: str,
        timestamps: list[float],
        window: float = 5.0,
    ) -> list[dict]:
        """Retrieve frame + audio context for multiple timestamps in batched queries.

        Returns one entry per timestamp with ``visual`` and ``audio`` keys.
        This replaces the N+1 per-timestamp loop pattern.
        """
        if not timestamps:
            return []

        # Batch frame lookup: one query for all timestamps
        with self._get_session() as session:
            # Get ALL frames for this video, ordered by timestamp
            all_frames_result = session.run(
                """
                MATCH (f:Frame)
                WHERE f.video_id = $video_id
                RETURN f.timestamp AS timestamp, f.description AS description
                ORDER BY f.timestamp
                """,
                video_id=video_id,
            )
            all_frames = [dict(r) for r in all_frames_result]

            # Get ALL audio segments that overlap any of the windows
            min_ts = min(timestamps) - window
            max_ts = max(timestamps) + window
            all_audio_result = session.run(
                """
                MATCH (a:AudioSegment)
                WHERE a.video_id = $video_id
                  AND a.start_time >= $min_ts AND a.start_time <= $max_ts
                RETURN a.start_time AS timestamp, a.text AS text,
                       a.speaker_label AS speaker
                ORDER BY a.start_time
                """,
                video_id=video_id,
                min_ts=min_ts,
                max_ts=max_ts,
            )
            all_audio = [dict(r) for r in all_audio_result]

        moments = []
        for ts in sorted(timestamps):
            # Find nearest frame
            nearest_frame = None
            min_dist = float("inf")
            for f in all_frames:
                dist = abs(f["timestamp"] - ts)
                if dist < min_dist:
                    min_dist = dist
                    nearest_frame = f

            # Find audio in window
            audio_in_window = [
                a for a in all_audio
                if ts - window <= a["timestamp"] <= ts + window
            ]

            moments.append({
                "timestamp": ts,
                "visual": nearest_frame,
                "audio": audio_in_window,
            })

        return moments
