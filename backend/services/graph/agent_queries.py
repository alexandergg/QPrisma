"""
Agent-facing query methods.

Consolidates Cypher queries previously scattered across agent tool files.
These methods centralise the statements for testability and reuse.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class AgentQueryMixin:
    """Mixin providing read-only queries used by the agent tool layer."""

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
            center = (
                center_timestamp if center_timestamp is not None else (start_time + end_time) / 2
            )
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
            center = (
                center_timestamp if center_timestamp is not None else (start_time + end_time) / 2
            )
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

    def find_entity_appearances(self, video_id: str, entity_name: str) -> dict[str, list[dict]]:
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
        audio = self._execute_query(audio_query, {"video_id": video_id, "entity_name": entity_name})

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
            audio_in_window = [a for a in all_audio if ts - window <= a["timestamp"] <= ts + window]

            moments.append(
                {
                    "timestamp": ts,
                    "visual": nearest_frame,
                    "audio": audio_in_window,
                }
            )

        return moments
