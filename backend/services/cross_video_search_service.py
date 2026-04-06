"""
Cross-Video Search Service for QPrisma

Encapsulates business logic extracted from multi-video agent tools.
Provides cross-video search, comparison, and result formatting
for the Knowledge Graph.

Agent tool functions delegate to this service for anything beyond
trivial parameter wiring.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agent.utils.formatting import format_timestamp

from services.graph_search_queries import sanitize_fulltext_query

if TYPE_CHECKING:
    from services.knowledge_graph import KnowledgeGraphService

logger = logging.getLogger(__name__)


# =============================================================================
# Result Data-Classes
# =============================================================================


@dataclass
class VideoMatch:
    """A single match within a video."""

    timestamp: float
    timestamp_formatted: str
    content: str
    score: float
    match_type: str = "visual"


@dataclass
class VideoSearchResult:
    """Search results for one video."""

    video_id: str | None
    video_title: str
    matches: list[dict[str, Any]] = field(default_factory=list)
    match_count: int = 0


@dataclass
class CrossVideoSearchResult:
    """Complete cross-video search result."""

    query: str
    videos_searched: int
    scoped_to_selection: bool
    results_by_video: list[dict[str, Any]] = field(default_factory=list)
    total_matches: int = 0
    error: str | None = None


@dataclass
class VideoComparisonEntry:
    """Comparison data for a single video."""

    video_id: str
    video_title: str
    summary: str
    topics: list[str]
    duration_formatted: str | None
    relevant_moments: list[dict[str, Any]]
    relevance_score: float


@dataclass
class CompareVideosResult:
    """Complete video comparison result."""

    query: str
    videos_compared: int
    comparison: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


# =============================================================================
# Cypher Query Constants
# =============================================================================

_FRAME_SEARCH_SCOPED = """
CALL db.index.fulltext.queryNodes('frame_search', $search_text) YIELD node, score
WITH node as f, score
WHERE f.video_id IN $media_ids AND f.user_id = $user_id
MATCH (v:Video {video_id: f.video_id, user_id: $user_id})
RETURN v.video_id as video_id, v.title as video_title,
       collect({
           timestamp: f.timestamp,
           description: f.description,
           score: score
       })[0..$limit] as matches
ORDER BY max(score) DESC
LIMIT $max_videos
"""

_AUDIO_SEARCH_SCOPED = """
CALL db.index.fulltext.queryNodes('audio_search', $search_text) YIELD node, score
WITH node as a, score
WHERE a.video_id IN $media_ids AND a.user_id = $user_id
MATCH (v:Video {video_id: a.video_id, user_id: $user_id})
RETURN v.video_id as video_id, v.title as video_title,
       collect({
           timestamp: a.start_time,
           text: a.text,
           score: score
       })[0..$limit] as matches
ORDER BY max(score) DESC
LIMIT $max_videos
"""

_VIDEO_METADATA = """
MATCH (v:Video)
WHERE (v.video_id = $vid OR v.id = $vid) AND v.user_id = $user_id
RETURN v.title as title, v.summary as summary, v.topics as topics,
       v.duration_seconds as duration
LIMIT 1
"""

_FRAME_SEARCH_SINGLE = """
CALL db.index.fulltext.queryNodes('frame_search', $search_text) YIELD node, score
WITH node as f, score
WHERE f.video_id = $vid AND f.user_id = $user_id
RETURN f.timestamp as timestamp, f.description as description, score
ORDER BY score DESC
LIMIT 3
"""

_AUDIO_SEARCH_SINGLE = """
CALL db.index.fulltext.queryNodes('audio_search', $search_text) YIELD node, score
WITH node as a, score
WHERE a.video_id = $vid AND a.user_id = $user_id
RETURN a.start_time as timestamp, a.text as text, score
ORDER BY score DESC
LIMIT 3
"""


# =============================================================================
# Service
# =============================================================================


class CrossVideoSearchService:
    """
    Service encapsulating cross-video search and comparison logic.

    All dependencies are injected via the constructor so the class is
    easily testable.  Methods never raise — they return result
    data-classes; the calling tool maps errors to error dicts.
    """

    MAX_COMPARE_VIDEOS = 10
    MAX_COMPARE_MOMENTS = 5

    def __init__(
        self,
        knowledge_graph_service: KnowledgeGraphService | None = None,
    ) -> None:
        self._kg = knowledge_graph_service

    # ------------------------------------------------------------------
    # Dependency helpers
    # ------------------------------------------------------------------

    def _ensure_kg(self) -> KnowledgeGraphService:
        """Return a connected KG service, lazily resolving if needed."""
        if self._kg is None:
            from services.knowledge_graph import get_knowledge_graph_service

            self._kg = get_knowledge_graph_service()

        if not self._kg.is_connected:
            self._kg.connect()

        return self._kg

    @staticmethod
    def _resolve_user_media_ids(user_id: str) -> list[str]:
        """Return all processed media IDs that belong to the given user."""
        from services.database_service import get_database_service

        db = get_database_service()
        media_ids: list[str] = []
        offset = 0
        batch_size = 500

        while True:
            media_batch = db.get_media_by_user(user_id, limit=batch_size, offset=offset)
            if not media_batch:
                break

            media_ids.extend(
                media.id for media in media_batch if getattr(media, "processed", False)
            )

            if len(media_batch) < batch_size:
                break
            offset += batch_size

        return media_ids

    # ------------------------------------------------------------------
    # Cross-video search
    # ------------------------------------------------------------------

    def search_across_videos(
        self,
        query: str,
        *,
        limit_per_video: int = 3,
        max_videos: int = 5,
        media_ids: list[str] | None = None,
        user_id: str | None = None,
    ) -> CrossVideoSearchResult:
        """
        Search for content across multiple videos.

        When *media_ids* is provided, only those videos are searched.
        Otherwise the user's processed videos are queried. Falls back
        from frame search to audio search when no frame hits are found.
        """
        kg = self._ensure_kg()

        safe_text = sanitize_fulltext_query(query)
        if safe_text is None:
            return CrossVideoSearchResult(
                query=query,
                videos_searched=0,
                scoped_to_selection=media_ids is not None,
                results_by_video=[],
                total_matches=0,
            )

        scoped_to_selection = media_ids is not None
        if not user_id:
            return CrossVideoSearchResult(
                query=query,
                videos_searched=0,
                scoped_to_selection=scoped_to_selection,
                results_by_video=[],
                total_matches=0,
                error="User context required for cross-video search.",
            )

        effective_media_ids = list(media_ids) if media_ids is not None else None
        if effective_media_ids is None:
            effective_media_ids = self._resolve_user_media_ids(user_id)

        if not effective_media_ids:
            return CrossVideoSearchResult(
                query=query,
                videos_searched=0,
                scoped_to_selection=scoped_to_selection,
                results_by_video=[],
                total_matches=0,
            )

        params: dict[str, Any] = {
            "search_text": safe_text,
            "limit": limit_per_video,
            "max_videos": max_videos,
            "media_ids": effective_media_ids,
            "user_id": user_id,
        }

        video_results = self._run_query(kg, _FRAME_SEARCH_SCOPED, params)
        if not video_results:
            video_results = self._run_query(kg, _AUDIO_SEARCH_SCOPED, params)

        results_by_video = [self._format_video_result(vr) for vr in video_results]

        return CrossVideoSearchResult(
            query=query,
            videos_searched=len(results_by_video),
            scoped_to_selection=scoped_to_selection,
            results_by_video=[self._result_to_dict(r) for r in results_by_video],
            total_matches=sum(r.match_count for r in results_by_video),
        )

    # ------------------------------------------------------------------
    # Video comparison
    # ------------------------------------------------------------------

    def compare_videos(
        self,
        query: str,
        effective_ids: list[str],
        user_id: str | None = None,
    ) -> CompareVideosResult:
        """
        Compare how each video covers a given topic.

        Returns per-video metadata, relevant moments (visual + audio),
        and a relevance score, sorted by relevance descending.
        """
        kg = self._ensure_kg()

        if not user_id:
            return CompareVideosResult(
                query=query,
                videos_compared=0,
                comparison=[],
                error="User context required for video comparison.",
            )

        comparison: list[dict[str, Any]] = []
        for vid in effective_ids[: self.MAX_COMPARE_VIDEOS]:
            entry = self._build_comparison_entry(kg, query, vid, user_id)
            comparison.append(entry)

        comparison.sort(key=lambda x: x["relevance_score"], reverse=True)

        return CompareVideosResult(
            query=query,
            videos_compared=len(comparison),
            comparison=comparison,
        )

    # ------------------------------------------------------------------
    # Private helpers — query execution
    # ------------------------------------------------------------------

    @staticmethod
    def _run_query(
        kg: KnowledgeGraphService,
        cypher: str,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Execute a Cypher query and return the result records as dicts."""
        with kg.get_session() as session:
            result = session.run(cypher, parameters=params)
            return list(result)

    # ------------------------------------------------------------------
    # Private helpers — result formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _format_match(m: dict[str, Any]) -> dict[str, Any]:
        """Format a single match record from a Cypher result row."""
        return {
            "timestamp": m.get("timestamp", 0),
            "timestamp_formatted": format_timestamp(m.get("timestamp", 0)),
            "content": (m.get("description") or m.get("text", ""))[:200],
            "score": round(m.get("score", 0), 3),
        }

    @classmethod
    def _format_video_result(cls, vr: dict[str, Any]) -> VideoSearchResult:
        """Build a *VideoSearchResult* from a raw Cypher result row."""
        matches = [cls._format_match(m) for m in vr.get("matches", [])]
        return VideoSearchResult(
            video_id=vr.get("video_id"),
            video_title=vr.get("video_title") or "Untitled",
            matches=matches,
            match_count=len(matches),
        )

    @staticmethod
    def _result_to_dict(r: VideoSearchResult) -> dict[str, Any]:
        """Serialise a *VideoSearchResult* to a plain dict."""
        return {
            "video_id": r.video_id,
            "video_title": r.video_title,
            "matches": r.matches,
            "match_count": r.match_count,
        }

    # ------------------------------------------------------------------
    # Private helpers — comparison entry
    # ------------------------------------------------------------------

    def _build_comparison_entry(
        self,
        kg: KnowledgeGraphService,
        query: str,
        vid: str,
        user_id: str,
    ) -> dict[str, Any]:
        """Assemble comparison data for a single video."""
        safe_text = sanitize_fulltext_query(query) or ""

        # Video metadata
        with kg.get_session() as session:
            result = session.run(_VIDEO_METADATA, parameters={"vid": vid, "user_id": user_id})
            video = result.single()

        # Frame matches
        with kg.get_session() as session:
            result = session.run(
                _FRAME_SEARCH_SINGLE,
                parameters={"search_text": safe_text, "vid": vid, "user_id": user_id},
            )
            frame_matches = list(result)

        # Audio matches
        with kg.get_session() as session:
            result = session.run(
                _AUDIO_SEARCH_SINGLE,
                parameters={"search_text": safe_text, "vid": vid, "user_id": user_id},
            )
            audio_matches = list(result)

        moments = self._build_moments(frame_matches, audio_matches)

        return {
            "video_id": vid,
            "video_title": (video.get("title") if video else None) or "Untitled",
            "summary": (video.get("summary") if video else None) or "",
            "topics": (video.get("topics") if video else None) or [],
            "duration_formatted": (
                format_timestamp(video.get("duration", 0))
                if video and video.get("duration")
                else None
            ),
            "relevant_moments": moments[: self.MAX_COMPARE_MOMENTS],
            "relevance_score": round(max((m["score"] for m in moments), default=0), 3),
        }

    @staticmethod
    def _build_moments(
        frame_matches: list[dict[str, Any]],
        audio_matches: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Merge frame and audio matches into a unified moments list."""
        moments: list[dict[str, Any]] = []
        for m in frame_matches:
            moments.append(
                {
                    "timestamp": m.get("timestamp", 0),
                    "timestamp_formatted": format_timestamp(m.get("timestamp", 0)),
                    "type": "visual",
                    "content": (m.get("description") or "")[:200],
                    "score": round(m.get("score", 0), 3),
                }
            )
        for m in audio_matches:
            moments.append(
                {
                    "timestamp": m.get("timestamp", 0),
                    "timestamp_formatted": format_timestamp(m.get("timestamp", 0)),
                    "type": "audio",
                    "content": (m.get("text") or "")[:200],
                    "score": round(m.get("score", 0), 3),
                }
            )
        moments.sort(key=lambda x: x["score"], reverse=True)
        return moments


# =============================================================================
# Lazy singleton
# =============================================================================

_cross_video_search_service: CrossVideoSearchService | None = None


def get_cross_video_search_service() -> CrossVideoSearchService:
    """Return the singleton instance of CrossVideoSearchService."""
    global _cross_video_search_service
    if _cross_video_search_service is None:
        _cross_video_search_service = CrossVideoSearchService()
    return _cross_video_search_service
