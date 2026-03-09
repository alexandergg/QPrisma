"""
Tests for services/highlight_detection_service.py

Unit tests for the extracted highlight detection business logic.
Covers all four detection strategies, the orchestrating ``detect_highlights``
method, the ``format_result`` helper, and the ``time_range_overlaps`` utility.
"""

from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest

from services.highlight_detection_service import (
    HighlightDetectionService,
    time_range_overlaps,
)

# =============================================================================
# Helpers – fake Neo4j session / KG
# =============================================================================


class FakeRecord(dict):
    """Dict subclass so ``record.get(...)`` works like the real Neo4j Record."""

    def get(self, key: str, default: Any = None) -> Any:  # noqa: ANN401
        return super().get(key, default)


def _make_kg(query_results: dict[str, list[dict]] | None = None) -> MagicMock:
    """Build a mock KnowledgeGraphService.

    ``query_results`` maps a Cypher *fragment* (substring of the query) to
    the list of dicts that ``session.run(query, ...)`` should return.
    When several queries match the same fragment, keep the fragments
    specific enough so only one matches each call.
    """
    query_results = query_results or {}

    session = MagicMock()

    def _run(query: str, **kwargs: Any) -> MagicMock:
        result_mock = MagicMock()
        for fragment, rows in query_results.items():
            if fragment in query:
                records = [FakeRecord(r) for r in rows]
                result_mock.__iter__ = lambda _m, _r=records: iter(_r)
                result_mock.__next__ = lambda _m: next(iter(_m))
                result_mock.single.return_value = records[0] if records else None
                return result_mock

        # Default – empty result
        result_mock.__iter__ = lambda _m: iter([])
        result_mock.single.return_value = None
        return result_mock

    session.run = _run

    @contextmanager
    def _get_session():
        yield session

    kg = MagicMock()
    kg.get_session = _get_session
    kg.is_connected = True
    return kg


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def kg_empty():
    """KG that returns nothing for all queries."""
    return _make_kg()


@pytest.fixture
def kg_with_video_duration():
    """KG that knows the video is 600 s long."""
    return _make_kg({"v.duration as duration": [{"duration": 600}]})


@pytest.fixture
def kg_with_frames():
    """KG with rich-frame candidates and a known duration."""
    return _make_kg(
        {
            "v.duration as duration": [{"duration": 600}],
            "max(s.end_time) as max_end": [{"max_end": 600}],
            "size(f.description) as desc_length": [
                {"timestamp": 30, "description": "A" * 120, "desc_length": 120},
                {"timestamp": 90, "description": "B" * 100, "desc_length": 100},
                {"timestamp": 200, "description": "C" * 90, "desc_length": 90},
            ],
        }
    )


@pytest.fixture
def kg_with_scenes():
    """KG with distributed scene data."""
    return _make_kg(
        {
            "v.duration as duration": [{"duration": 600}],
            "max(s.end_time) as max_end": [{"max_end": 600}],
            "scene.start_time as start": [
                {"start": 10, "end": 30},
                {"start": 150, "end": 175},
            ],
            "f.description as description\n": [
                {"description": "Scene frame description here"},
            ],
        }
    )


@pytest.fixture
def kg_with_entities():
    """KG with entity-rich frames."""
    return _make_kg(
        {
            "v.duration as duration": [{"duration": 600}],
            "max(s.end_time) as max_end": [{"max_end": 600}],
            "entity_count": [
                {"timestamp": 100, "description": "Three people talking", "entity_count": 5},
                {"timestamp": 200, "description": "Group scene", "entity_count": 4},
            ],
        }
    )


@pytest.fixture
def service_empty(kg_empty):
    return HighlightDetectionService(kg_empty)


@pytest.fixture
def service_with_frames(kg_with_frames):
    return HighlightDetectionService(kg_with_frames)


@pytest.fixture
def service_with_scenes(kg_with_scenes):
    return HighlightDetectionService(kg_with_scenes)


@pytest.fixture
def service_with_entities(kg_with_entities):
    return HighlightDetectionService(kg_with_entities)


# =============================================================================
# time_range_overlaps
# =============================================================================


class TestTimeRangeOverlaps:
    def test_no_ranges(self):
        assert time_range_overlaps(0, 10, []) is False

    def test_non_overlapping(self):
        assert time_range_overlaps(20, 30, [(0, 10), (40, 50)]) is False

    def test_overlapping(self):
        assert time_range_overlaps(5, 15, [(10, 20)]) is True

    def test_contained(self):
        assert time_range_overlaps(12, 18, [(10, 20)]) is True

    def test_exact_boundary_no_overlap(self):
        # start == used_end means no overlap (strict <)
        assert time_range_overlaps(10, 20, [(0, 10)]) is False

    def test_adjacent_end_start(self):
        assert time_range_overlaps(0, 10, [(10, 20)]) is False


# =============================================================================
# format_result
# =============================================================================


class TestFormatResult:
    def test_empty(self):
        result = HighlightDetectionService.format_result("all", [])
        assert result["criteria"] == "all"
        assert result["total_highlights"] == 0
        assert result["highlights"] == []
        assert result["exportable"] is True
        assert "0 potential highlight" in result["message"]

    def test_with_highlights(self):
        highlights = [{"start_time": 0}, {"start_time": 10}]
        result = HighlightDetectionService.format_result("engagement", highlights)
        assert result["total_highlights"] == 2
        assert result["criteria"] == "engagement"


# =============================================================================
# find_frame_highlights
# =============================================================================


class TestFindFrameHighlights:
    def test_returns_highlights_from_frames(self, service_with_frames):
        used = []
        highlights = service_with_frames.find_frame_highlights(
            media_id="vid1",
            segment_duration=60,
            max_clips=5,
            min_duration=10,
            max_duration=60,
            used_ranges=used,
        )
        assert len(highlights) > 0
        for h in highlights:
            assert "start_time" in h
            assert "end_time" in h
            assert "start_formatted" in h
            assert "end_formatted" in h
            assert "duration" in h
            assert h["title"] == "Content Highlight"
            assert "social_clip" in h["suggested_for"]

    def test_respects_max_clips(self, service_with_frames):
        highlights = service_with_frames.find_frame_highlights(
            media_id="vid1",
            segment_duration=60,
            max_clips=1,
            min_duration=10,
            max_duration=60,
            used_ranges=[],
        )
        assert len(highlights) <= 1

    def test_updates_used_ranges(self, service_with_frames):
        used: list[tuple[float, float]] = []
        service_with_frames.find_frame_highlights(
            media_id="vid1",
            segment_duration=60,
            max_clips=5,
            min_duration=10,
            max_duration=60,
            used_ranges=used,
        )
        assert len(used) > 0

    def test_no_candidates_returns_empty(self, service_empty):
        highlights = service_empty.find_frame_highlights(
            media_id="vid1",
            segment_duration=60,
            max_clips=5,
            min_duration=10,
            max_duration=60,
            used_ranges=[],
        )
        assert highlights == []


# =============================================================================
# find_scene_highlights
# =============================================================================


class TestFindSceneHighlights:
    def test_returns_scene_highlights(self, service_with_scenes):
        used = []
        highlights = service_with_scenes.find_scene_highlights(
            media_id="vid1",
            segment_duration=60,
            max_clips=5,
            min_duration=10,
            max_duration=60,
            used_ranges=used,
        )
        assert len(highlights) > 0
        for h in highlights:
            assert h["title"] == "Visual Highlight"
            assert h["highlight_reason"] == "Key visual moment"

    def test_skips_too_short_scenes(self):
        kg = _make_kg(
            {
                "v.duration as duration": [{"duration": 600}],
                "scene.start_time as start": [{"start": 10, "end": 12}],
            }
        )
        svc = HighlightDetectionService(kg)
        highlights = svc.find_scene_highlights(
            media_id="vid1",
            segment_duration=60,
            max_clips=5,
            min_duration=15,
            max_duration=60,
            used_ranges=[],
        )
        assert highlights == []

    def test_skips_too_long_scenes(self):
        kg = _make_kg(
            {
                "v.duration as duration": [{"duration": 600}],
                "scene.start_time as start": [{"start": 0, "end": 120}],
            }
        )
        svc = HighlightDetectionService(kg)
        highlights = svc.find_scene_highlights(
            media_id="vid1",
            segment_duration=60,
            max_clips=5,
            min_duration=10,
            max_duration=60,
            used_ranges=[],
        )
        assert highlights == []


# =============================================================================
# find_entity_highlights
# =============================================================================


class TestFindEntityHighlights:
    def test_returns_entity_highlights(self, service_with_entities):
        used = []
        highlights = service_with_entities.find_entity_highlights(
            media_id="vid1",
            max_clips=5,
            min_duration=10,
            used_ranges=used,
        )
        assert len(highlights) > 0
        for h in highlights:
            assert h["title"] == "Key Moment"
            assert "entities" in h["highlight_reason"]
            assert "highlight_reel" in h["suggested_for"]

    def test_respects_max_clips(self, service_with_entities):
        highlights = service_with_entities.find_entity_highlights(
            media_id="vid1",
            max_clips=1,
            min_duration=10,
            used_ranges=[],
        )
        assert len(highlights) <= 1

    def test_no_entities_returns_empty(self, service_empty):
        highlights = service_empty.find_entity_highlights(
            media_id="vid1",
            max_clips=5,
            min_duration=10,
            used_ranges=[],
        )
        assert highlights == []


# =============================================================================
# find_fallback_highlights
# =============================================================================


class TestFindFallbackHighlights:
    def test_returns_evenly_spaced(self, service_with_frames):
        used = []
        highlights = service_with_frames.find_fallback_highlights(
            media_id="vid1",
            video_duration=600,
            max_clips=5,
            min_duration=10,
            used_ranges=used,
        )
        assert len(highlights) == 3  # 10%, 50%, 85%
        for h in highlights:
            assert h["highlight_reason"] == "Representative sample"
            assert "preview" in h["suggested_for"]
            assert "Sample at" in h["title"]

    def test_zero_duration_looks_up_from_kg(self, kg_with_video_duration):
        svc = HighlightDetectionService(kg_with_video_duration)
        highlights = svc.find_fallback_highlights(
            media_id="vid1",
            video_duration=0,
            max_clips=5,
            min_duration=10,
            used_ranges=[],
        )
        assert len(highlights) == 3

    def test_no_duration_at_all(self, service_empty):
        highlights = service_empty.find_fallback_highlights(
            media_id="vid1",
            video_duration=0,
            max_clips=5,
            min_duration=10,
            used_ranges=[],
        )
        assert highlights == []

    def test_skips_used_ranges(self, service_with_frames):
        # Pre-fill used_ranges to cover the 10% sample point (600*0.1 = 60)
        used = [(55.0, 65.0)]
        highlights = service_with_frames.find_fallback_highlights(
            media_id="vid1",
            video_duration=600,
            max_clips=5,
            min_duration=10,
            used_ranges=used,
        )
        starts = [h["start_time"] for h in highlights]
        # The 10% point (55..65) should be skipped
        assert not any(55 <= s <= 65 for s in starts)


# =============================================================================
# detect_highlights (orchestrator)
# =============================================================================


class TestDetectHighlights:
    def test_returns_sorted_highlights(self, service_with_frames):
        result = service_with_frames.detect_highlights(media_id="vid1")
        starts = [h["start_time"] for h in result["highlights"]]
        assert starts == sorted(starts)

    def test_result_shape(self, service_with_frames):
        result = service_with_frames.detect_highlights(media_id="vid1", criteria="action")
        assert result["criteria"] == "action"
        assert "total_highlights" in result
        assert isinstance(result["highlights"], list)
        assert result["exportable"] is True
        assert "message" in result

    def test_empty_kg_still_returns_valid_shape(self, service_empty):
        result = service_empty.detect_highlights(media_id="vid1")
        assert result["total_highlights"] == 0
        assert result["highlights"] == []

    def test_max_clips_respected(self, service_with_frames):
        result = service_with_frames.detect_highlights(media_id="vid1", max_clips=1)
        assert result["total_highlights"] <= 1

    def test_fallback_kicks_in_when_few_highlights(self):
        """When the first three strategies find < 3, fallback adds samples."""
        kg = _make_kg({"v.duration as duration": [{"duration": 300}]})
        svc = HighlightDetectionService(kg)
        result = svc.detect_highlights(media_id="vid1")
        # Should get fallback samples since no frames/scenes/entities exist
        assert result["total_highlights"] == 3


# =============================================================================
# _get_video_duration
# =============================================================================


class TestGetVideoDuration:
    def test_from_video_node(self, kg_with_video_duration):
        svc = HighlightDetectionService(kg_with_video_duration)
        assert svc._get_video_duration("vid1") == 600.0

    def test_falls_back_to_scene_max(self):
        kg = _make_kg(
            {
                "v.duration as duration": [{"duration": 0}],
                "max(s.end_time) as max_end": [{"max_end": 450}],
            }
        )
        svc = HighlightDetectionService(kg)
        assert svc._get_video_duration("vid1") == 450.0

    def test_zero_when_nothing(self, service_empty):
        assert service_empty._get_video_duration("vid1") == 0.0
