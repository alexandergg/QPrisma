"""
Audio segment (transcript) operations.

Covers creation (single and batch), retrieval, search, and deletion of
AudioSegment nodes as well as the NEXT_SEGMENT temporal chain.
"""

from __future__ import annotations

import logging

from models.graph_models import AudioSegmentNode

logger = logging.getLogger(__name__)


class AudioOpsMixin:
    """Mixin providing AudioSegment CRUD, search, and segment-chain helpers."""

    # =====================================================================
    # Audio Segment (Transcript) Operations
    # =====================================================================

    def create_audio_segment(self, segment: AudioSegmentNode) -> str:
        """Create an AudioSegment (transcript) node and connect it to its Video."""
        query = """
        MATCH (v:Video)
        WHERE v.video_id = $video_id
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

        record = self._execute_query(
            query,
            {
                "id": segment.id,
                "video_id": segment.video_id,
                "user_id": segment.user_id,
                "start_time": segment.start_time,
                "end_time": segment.end_time,
                "text": segment.text,
                "language": segment.language,
                "confidence": segment.confidence,
                "speaker_id": segment.speaker_id,
                "speaker_label": segment.speaker_label,
                "created_at": segment.created_at.isoformat(),
            },
            single=True,
        )
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
        WHERE v.video_id = seg.video_id
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
                record = self._execute_query(query, {"segments": segments_data}, single=True)
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
        WHERE v.video_id = $video_id
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
            WHERE (v.video_id = $video_id)
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

        return self._execute_query(
            query, {"query_text": query_text, "video_id": video_id, "limit": limit}
        )

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
    # Segment Chain Operations
    # =====================================================================

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

        count = self._execute_chain_rebuild(delete_query, create_query, {"video_id": video_id})
        logger.info(f"Created {count} NEXT_SEGMENT edges for video {video_id}")
        return count
