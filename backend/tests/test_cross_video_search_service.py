"""
Unit tests for CrossVideoSearchService.

Covers the business logic extracted from multi-video agent tools:
- Cross-video search with scoped and unscoped modes
- Audio fallback when frame search yields no results
- Match formatting and result aggregation
- Video comparison with metadata, frame, and audio matches
- Moment merging and relevance scoring
- Edge cases: empty results, missing metadata, singleton wiring
"""

import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure backend is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.cross_video_search_service import (
    CompareVideosResult,
    CrossVideoSearchResult,
    CrossVideoSearchService,
    VideoSearchResult,
    get_cross_video_search_service,
)

# =============================================================================
# Helpers
# =============================================================================


def _make_mock_kg(session_results=None):
    """Create a mocked KnowledgeGraphService with a fake get_session.

    Each entry in *session_results* is either:
    - a list of dicts  → ``session.run()`` returns an iterable **and**
      ``result.single()`` returns the first element (or ``None``).
    - ``None``          → ``result.single()`` returns ``None`` and
      iteration yields nothing.
    """
    kg = MagicMock()
    kg.is_connected = True

    if session_results is None:
        session_results = [[]]

    call_index = {"i": 0}

    @contextmanager
    def fake_get_session():
        session = MagicMock()
        idx = min(call_index["i"], len(session_results) - 1)
        data = session_results[idx]
        call_index["i"] += 1

        result_obj = MagicMock()
        if data is None:
            result_obj.__iter__ = MagicMock(return_value=iter([]))
            result_obj.single.return_value = None
        else:
            result_obj.__iter__ = MagicMock(return_value=iter(data))
            result_obj.single.return_value = data[0] if data else None
        session.run.return_value = result_obj

        yield session

    kg.get_session = fake_get_session
    return kg


def _make_frame_row(video_id="v1", title="Video 1", matches=None):
    """Build a dict mimicking a Cypher result row from a frame search."""
    if matches is None:
        matches = [
            {"timestamp": 10.0, "description": "A sunset", "score": 2.5},
            {"timestamp": 25.0, "description": "A cityscape", "score": 1.8},
        ]
    return {"video_id": video_id, "video_title": title, "matches": matches}


def _make_audio_row(video_id="v1", title="Video 1", matches=None):
    """Build a dict mimicking a Cypher result row from an audio search."""
    if matches is None:
        matches = [
            {"timestamp": 5.0, "text": "Welcome everyone", "score": 1.5},
        ]
    return {"video_id": video_id, "video_title": title, "matches": matches}


# =============================================================================
# _format_match
# =============================================================================


@pytest.mark.unit
class TestFormatMatch:
    def test_frame_match(self):
        raw = {"timestamp": 90.5, "description": "A dog", "score": 2.123456}
        result = CrossVideoSearchService._format_match(raw)

        assert result["timestamp"] == 90.5
        assert result["timestamp_formatted"] == "1:30"
        assert result["content"] == "A dog"
        assert result["score"] == 2.123

    def test_audio_match_uses_text(self):
        raw = {"timestamp": 0.0, "text": "Hello world", "score": 0.7777}
        result = CrossVideoSearchService._format_match(raw)

        assert result["content"] == "Hello world"
        assert result["score"] == 0.778

    def test_missing_fields_default(self):
        result = CrossVideoSearchService._format_match({})

        assert result["timestamp"] == 0
        assert result["content"] == ""
        assert result["score"] == 0

    def test_content_truncated_to_200(self):
        long_text = "x" * 300
        result = CrossVideoSearchService._format_match({"description": long_text})
        assert len(result["content"]) == 200


# =============================================================================
# _format_video_result
# =============================================================================


@pytest.mark.unit
class TestFormatVideoResult:
    def test_basic(self):
        row = _make_frame_row()
        vr = CrossVideoSearchService._format_video_result(row)

        assert isinstance(vr, VideoSearchResult)
        assert vr.video_id == "v1"
        assert vr.video_title == "Video 1"
        assert vr.match_count == 2
        assert len(vr.matches) == 2

    def test_untitled_fallback(self):
        row = {"video_id": "v2", "video_title": None, "matches": []}
        vr = CrossVideoSearchService._format_video_result(row)
        assert vr.video_title == "Untitled"

    def test_empty_matches(self):
        row = {"video_id": "v3", "video_title": "Empty", "matches": []}
        vr = CrossVideoSearchService._format_video_result(row)
        assert vr.match_count == 0


# =============================================================================
# _build_moments
# =============================================================================


@pytest.mark.unit
class TestBuildMoments:
    def test_merges_and_sorts_by_score(self):
        frames = [{"timestamp": 10, "description": "frame", "score": 2.0}]
        audios = [{"timestamp": 5, "text": "audio", "score": 3.0}]

        moments = CrossVideoSearchService._build_moments(frames, audios)

        assert len(moments) == 2
        # Audio has higher score, should come first
        assert moments[0]["type"] == "audio"
        assert moments[0]["score"] == 3.0
        assert moments[1]["type"] == "visual"

    def test_empty_inputs(self):
        assert CrossVideoSearchService._build_moments([], []) == []

    def test_only_frames(self):
        frames = [{"timestamp": 1, "description": "f1", "score": 1.0}]
        moments = CrossVideoSearchService._build_moments(frames, [])
        assert len(moments) == 1
        assert moments[0]["type"] == "visual"

    def test_only_audio(self):
        audios = [{"timestamp": 2, "text": "a1", "score": 0.5}]
        moments = CrossVideoSearchService._build_moments([], audios)
        assert len(moments) == 1
        assert moments[0]["type"] == "audio"


# =============================================================================
# search_across_videos
# =============================================================================


@pytest.mark.unit
class TestSearchAcrossVideos:
    def test_scoped_search_with_frame_results(self):
        row = _make_frame_row("v1", "Demo")
        kg = _make_mock_kg(session_results=[[row]])

        svc = CrossVideoSearchService(knowledge_graph_service=kg)
        result = svc.search_across_videos("sunset", media_ids=["v1"], user_id="user-1")

        assert isinstance(result, CrossVideoSearchResult)
        assert result.query == "sunset"
        assert result.scoped_to_selection is True
        assert result.videos_searched == 1
        assert result.total_matches == 2
        assert result.error is None
        assert result.results_by_video[0]["video_id"] == "v1"

    def test_user_scoped_search_when_media_ids_omitted(self):
        row = _make_frame_row("v2", "Other Video")
        kg = _make_mock_kg(session_results=[[]])
        mock_db = MagicMock()
        mock_db.get_media_by_user.return_value = [
            MagicMock(id="v2", processed=True),
            MagicMock(id="v3", processed=False),
        ]

        with (
            patch("services.database_service.get_database_service", return_value=mock_db),
            patch.object(
                CrossVideoSearchService, "_run_query", return_value=[row]
            ) as mock_run_query,
        ):
            svc = CrossVideoSearchService(knowledge_graph_service=kg)
            result = svc.search_across_videos("topic", user_id="user-1", media_ids=None)

        assert result.scoped_to_selection is False
        assert result.videos_searched == 1
        assert mock_run_query.call_args.args[2]["media_ids"] == ["v2"]
        assert mock_run_query.call_args.args[2]["user_id"] == "user-1"

    def test_missing_user_context_does_not_fallback_to_global_search(self):
        kg = _make_mock_kg(session_results=[[]])

        with patch.object(CrossVideoSearchService, "_run_query") as mock_run_query:
            svc = CrossVideoSearchService(knowledge_graph_service=kg)
            result = svc.search_across_videos("topic", media_ids=None, user_id=None)

        assert result.error == "User context required for cross-video search."
        assert result.videos_searched == 0
        mock_run_query.assert_not_called()

    def test_empty_explicit_selection_does_not_expand_scope(self):
        kg = _make_mock_kg(session_results=[[]])

        with patch.object(CrossVideoSearchService, "_run_query") as mock_run_query:
            svc = CrossVideoSearchService(knowledge_graph_service=kg)
            result = svc.search_across_videos("topic", media_ids=[], user_id="user-1")

        assert result.error is None
        assert result.scoped_to_selection is True
        assert result.videos_searched == 0
        mock_run_query.assert_not_called()

    def test_fallback_to_audio_when_frames_empty(self):
        """When frame search returns empty, service falls back to audio."""
        audio_row = _make_audio_row("v1", "Audio Vid")
        # First call (frame) returns empty, second call (audio) returns results
        kg = _make_mock_kg(session_results=[[], [audio_row]])

        svc = CrossVideoSearchService(knowledge_graph_service=kg)
        result = svc.search_across_videos("greeting", media_ids=["v1"], user_id="user-1")

        assert result.total_matches == 1
        assert result.results_by_video[0]["video_title"] == "Audio Vid"

    def test_no_results_at_all(self):
        kg = _make_mock_kg(session_results=[[], []])

        svc = CrossVideoSearchService(knowledge_graph_service=kg)
        result = svc.search_across_videos("nonexistent", media_ids=["v99"], user_id="user-1")

        assert result.total_matches == 0
        assert result.videos_searched == 0

    def test_multiple_videos_returned(self):
        rows = [
            _make_frame_row("v1", "First"),
            _make_frame_row("v2", "Second"),
        ]
        kg = _make_mock_kg(session_results=[rows])

        svc = CrossVideoSearchService(knowledge_graph_service=kg)
        result = svc.search_across_videos("topic", media_ids=["v1", "v2"], user_id="user-1")

        assert result.videos_searched == 2
        assert result.total_matches == 4  # 2 matches per video

    def test_lazy_kg_resolution(self):
        """Service lazily resolves KG when none provided."""
        mock_kg = _make_mock_kg(session_results=[[]])
        with patch(
            "services.knowledge_graph.get_knowledge_graph_service",
            return_value=mock_kg,
        ):
            svc = CrossVideoSearchService()  # No kg injected
            result = svc.search_across_videos("test", media_ids=["v1"], user_id="user-1")
            assert result.error is None


# =============================================================================
# compare_videos
# =============================================================================


@pytest.mark.unit
class TestCompareVideos:
    def _setup_kg_for_compare(self, videos_data):
        """
        Build a mock KG where each video needs 3 session calls:
        metadata, frame search, audio search.
        """
        session_results = []
        for vdata in videos_data:
            session_results.append([vdata["meta"]])  # metadata
            session_results.append(vdata.get("frames", []))  # frame matches
            session_results.append(vdata.get("audios", []))  # audio matches
        return _make_mock_kg(session_results=session_results)

    def test_basic_comparison(self):
        kg = self._setup_kg_for_compare(
            [
                {
                    "meta": {
                        "title": "Video A",
                        "summary": "About cats",
                        "topics": ["cats"],
                        "duration": 120.0,
                    },
                    "frames": [
                        {"timestamp": 10, "description": "A cat", "score": 2.5},
                    ],
                    "audios": [],
                },
                {
                    "meta": {
                        "title": "Video B",
                        "summary": "About dogs",
                        "topics": ["dogs"],
                        "duration": 60.0,
                    },
                    "frames": [],
                    "audios": [
                        {"timestamp": 5, "text": "Here is a dog", "score": 1.8},
                    ],
                },
            ]
        )

        svc = CrossVideoSearchService(knowledge_graph_service=kg)
        result = svc.compare_videos("animals", ["v1", "v2"], user_id="user-1")

        assert isinstance(result, CompareVideosResult)
        assert result.query == "animals"
        assert result.videos_compared == 2
        assert result.error is None

        # Sorted by relevance: Video A (2.5) > Video B (1.8)
        assert result.comparison[0]["video_title"] == "Video A"
        assert result.comparison[0]["relevance_score"] == 2.5
        assert result.comparison[1]["video_title"] == "Video B"
        assert result.comparison[1]["relevance_score"] == 1.8

    def test_requires_user_context(self):
        kg = _make_mock_kg(session_results=[[]])

        svc = CrossVideoSearchService(knowledge_graph_service=kg)
        result = svc.compare_videos("animals", ["v1", "v2"], user_id=None)

        assert result.error == "User context required for video comparison."
        assert result.videos_compared == 0

    def test_video_with_no_matches(self):
        kg = self._setup_kg_for_compare(
            [
                {
                    "meta": {
                        "title": "Silent Video",
                        "summary": "",
                        "topics": [],
                        "duration": 30.0,
                    },
                    "frames": [],
                    "audios": [],
                },
                {
                    "meta": {
                        "title": "Active Video",
                        "summary": "Lots of content",
                        "topics": ["topic"],
                        "duration": 90.0,
                    },
                    "frames": [
                        {"timestamp": 15, "description": "Something", "score": 1.0},
                    ],
                    "audios": [],
                },
            ]
        )

        svc = CrossVideoSearchService(knowledge_graph_service=kg)
        result = svc.compare_videos("anything", ["v1", "v2"], user_id="user-1")

        # Video with no matches has relevance 0
        silent = [c for c in result.comparison if c["video_title"] == "Silent Video"][0]
        assert silent["relevance_score"] == 0
        assert len(silent["relevant_moments"]) == 0

    def test_missing_video_metadata(self):
        """When video metadata query returns None (single() returns None)."""
        # metadata=None, frames=[], audios=[] for one video;
        # second video gets same pattern via the clamped index
        kg = _make_mock_kg(session_results=[None, [], [], None, [], []])

        svc = CrossVideoSearchService(knowledge_graph_service=kg)
        result = svc.compare_videos("test", ["v1", "v2"], user_id="user-1")

        # Should not error — falls back to "Untitled" and empty fields
        entry = result.comparison[0]
        assert entry["video_title"] == "Untitled"
        assert entry["summary"] == ""
        assert entry["topics"] == []

    def test_max_videos_capped_at_10(self):
        """Only first 10 videos are compared even if more are provided."""
        many_ids = [f"v{i}" for i in range(15)]
        # Build session results for 10 videos (3 calls each)
        session_results = []
        for i in range(10):
            session_results.append(
                [{"title": f"V{i}", "summary": "", "topics": [], "duration": 10}]
            )
            session_results.append([])  # frames
            session_results.append([])  # audios
        kg = _make_mock_kg(session_results=session_results)

        svc = CrossVideoSearchService(knowledge_graph_service=kg)
        result = svc.compare_videos("test", many_ids, user_id="user-1")

        assert result.videos_compared == 10

    def test_moments_limited_to_5(self):
        """relevant_moments should be capped at MAX_COMPARE_MOMENTS (5)."""
        frames = [
            {"timestamp": i, "description": f"Frame {i}", "score": float(10 - i)} for i in range(8)
        ]
        kg = self._setup_kg_for_compare(
            [
                {
                    "meta": {"title": "V1", "summary": "", "topics": [], "duration": 100},
                    "frames": frames,
                    "audios": [],
                },
                {
                    "meta": {"title": "V2", "summary": "", "topics": [], "duration": 50},
                    "frames": [],
                    "audios": [],
                },
            ]
        )

        svc = CrossVideoSearchService(knowledge_graph_service=kg)
        result = svc.compare_videos("frames", ["v1", "v2"], user_id="user-1")

        v1_entry = [c for c in result.comparison if c["video_title"] == "V1"][0]
        assert len(v1_entry["relevant_moments"]) == 5

    def test_duration_formatted_none_when_missing(self):
        """When video has no duration, duration_formatted should be None."""
        kg = self._setup_kg_for_compare(
            [
                {
                    "meta": {"title": "NoDuration", "summary": "", "topics": [], "duration": None},
                    "frames": [],
                    "audios": [],
                },
                {
                    "meta": {"title": "HasDuration", "summary": "", "topics": [], "duration": 90},
                    "frames": [],
                    "audios": [],
                },
            ]
        )

        svc = CrossVideoSearchService(knowledge_graph_service=kg)
        result = svc.compare_videos("test", ["v1", "v2"], user_id="user-1")

        no_dur = [c for c in result.comparison if c["video_title"] == "NoDuration"][0]
        has_dur = [c for c in result.comparison if c["video_title"] == "HasDuration"][0]
        assert no_dur["duration_formatted"] is None
        assert has_dur["duration_formatted"] == "1:30"


# =============================================================================
# _result_to_dict
# =============================================================================


@pytest.mark.unit
class TestResultToDict:
    def test_serialises_correctly(self):
        vr = VideoSearchResult(
            video_id="v1",
            video_title="Demo",
            matches=[{"score": 1.0}],
            match_count=1,
        )
        d = CrossVideoSearchService._result_to_dict(vr)

        assert d == {
            "video_id": "v1",
            "video_title": "Demo",
            "matches": [{"score": 1.0}],
            "match_count": 1,
        }


# =============================================================================
# Singleton
# =============================================================================


@pytest.mark.unit
class TestSingleton:
    def test_returns_same_instance(self):
        import services.cross_video_search_service as mod

        mod._cross_video_search_service = None  # Reset

        svc1 = get_cross_video_search_service()
        svc2 = get_cross_video_search_service()

        assert svc1 is svc2

        mod._cross_video_search_service = None  # Cleanup

    def test_returns_fresh_after_reset(self):
        import services.cross_video_search_service as mod

        mod._cross_video_search_service = None
        svc1 = get_cross_video_search_service()

        mod._cross_video_search_service = None
        svc2 = get_cross_video_search_service()

        assert svc1 is not svc2

        mod._cross_video_search_service = None  # Cleanup


# =============================================================================
# _ensure_kg
# =============================================================================


@pytest.mark.unit
class TestEnsureKg:
    def test_connects_if_not_connected(self):
        kg = MagicMock()
        kg.is_connected = False

        svc = CrossVideoSearchService(knowledge_graph_service=kg)
        result = svc._ensure_kg()

        kg.connect.assert_called_once()
        assert result is kg

    def test_no_connect_if_already_connected(self):
        kg = MagicMock()
        kg.is_connected = True

        svc = CrossVideoSearchService(knowledge_graph_service=kg)
        result = svc._ensure_kg()

        kg.connect.assert_not_called()
        assert result is kg

    def test_lazy_resolve_when_none(self):
        mock_kg = MagicMock()
        mock_kg.is_connected = True

        with patch(
            "services.knowledge_graph.get_knowledge_graph_service",
            return_value=mock_kg,
        ):
            svc = CrossVideoSearchService()
            result = svc._ensure_kg()
            assert result is mock_kg
