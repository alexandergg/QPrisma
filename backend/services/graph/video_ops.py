"""
Video, Scene, and Chapter node operations.

Covers creation and retrieval of Video, Scene, and Chapter nodes as well as
the NEXT_SCENE temporal chain.
"""

from __future__ import annotations

import logging

from models.graph_models import ChapterNode, SceneNode, VideoNode

logger = logging.getLogger(__name__)


class VideoOpsMixin:
    """Mixin providing Video / Scene / Chapter CRUD and scene-chain helpers."""

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
        """Retrieve a Video node by its video_id."""
        query = """
        MATCH (v:Video)
        WHERE v.video_id = $video_id
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
        WHERE v.video_id = $media_id
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

    def update_video_summary(self, video_id: str, summary: str, topics: list[str]) -> None:
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
        WHERE v.video_id = $video_id
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
        WHERE v.video_id = $video_id
        RETURN DISTINCT f.id as id, f.timestamp as timestamp, f.frame_number as frame_number,
               f.description as description, f.scene_id as scene_id
        ORDER BY f.timestamp
        """
        return self._execute_query(query, {"video_id": video_id})

    # =====================================================================
    # Scene Chain Operations
    # =====================================================================

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
