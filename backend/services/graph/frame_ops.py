"""
Frame node operations.

Covers creation (single and batch) of Frame nodes and the NEXT_FRAME
temporal chain.
"""

from __future__ import annotations

import logging

from models.graph_models import FrameNode

logger = logging.getLogger(__name__)


class FrameOpsMixin:
    """Mixin providing Frame CRUD and frame-chain helpers."""

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
    # Frame Chain Operations
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
