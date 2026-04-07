"""
Tests for agent-facing query methods in GraphNodeRepository and
KnowledgeGraphService facade.

These methods were extracted from inline Cypher in agent tool files
to centralise queries in the service layer.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.graph_node_repository import GraphNodeRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_repo(execute_return=None):
    """Create a repository with mocked execute_query and session factory."""
    exec_fn = MagicMock(return_value=execute_return)
    sess_fn = MagicMock()
    repo = GraphNodeRepository(exec_fn, sess_fn)
    return repo, exec_fn, sess_fn


def _make_session(run_results=None):
    """Create a context-manager mock session.

    *run_results* is a list of return values; each call to ``session.run()``
    pops the first item.  Each item can be:
    - a list of dicts  → iterable result, ``single()`` returns first or None
    - a dict           → ``single()`` returns the dict
    - None             → ``single()`` returns None, iteration yields nothing
    """
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)

    if run_results is None:
        run_results = [None]

    call_counter = {"i": 0}

    def _run(*args, **kwargs):
        idx = call_counter["i"]
        call_counter["i"] += 1
        item = run_results[idx] if idx < len(run_results) else None

        result = MagicMock()
        if isinstance(item, list):
            result.__iter__ = MagicMock(return_value=iter(item))
            result.single.return_value = item[0] if item else None
        elif isinstance(item, dict):
            result.__iter__ = MagicMock(return_value=iter([item]))
            result.single.return_value = item
        else:
            result.__iter__ = MagicMock(return_value=iter([]))
            result.single.return_value = None
        return result

    session.run.side_effect = _run
    return session


# ===========================================================================
# get_video_summary_data
# ===========================================================================


@pytest.mark.unit
class TestGetVideoSummaryData:
    def test_returns_record(self):
        expected = {"summary": "A great video", "title": "Demo", "topics": ["AI"], "duration": 120}
        repo, exec_fn, _ = _make_repo(execute_return=expected)
        result = repo.get_video_summary_data("vid-1")
        assert result == expected
        exec_fn.assert_called_once()
        query = exec_fn.call_args.args[0]
        assert "v.summary" in query and "v.duration_seconds" in query

    def test_returns_none_when_not_found(self):
        repo, exec_fn, _ = _make_repo(execute_return=None)
        result = repo.get_video_summary_data("missing")
        assert result is None


# ===========================================================================
# get_nearest_frame
# ===========================================================================


@pytest.mark.unit
class TestGetNearestFrame:
    def test_returns_closest_frame(self):
        frame = {"timestamp": 10.5, "description": "A person talking"}
        repo, exec_fn, _ = _make_repo(execute_return=frame)
        result = repo.get_nearest_frame("vid-1", 10.0)
        assert result == frame
        query = exec_fn.call_args.args[0]
        assert "abs(f.timestamp" in query

    def test_returns_none_when_no_frames(self):
        repo, exec_fn, _ = _make_repo(execute_return=None)
        result = repo.get_nearest_frame("vid-1", 0.0)
        assert result is None


# ===========================================================================
# get_scene_at_timestamp
# ===========================================================================


@pytest.mark.unit
class TestGetSceneAtTimestamp:
    def test_returns_matching_scene(self):
        scene = {
            "start_time": 0.0,
            "end_time": 15.0,
            "description": "Intro",
            "scene_type": "intro",
        }
        repo, exec_fn, _ = _make_repo(execute_return=scene)
        result = repo.get_scene_at_timestamp("vid-1", 7.0)
        assert result == scene
        params = exec_fn.call_args.args[1]
        assert params["timestamp"] == 7.0

    def test_returns_none_when_no_scene(self):
        repo, exec_fn, _ = _make_repo(execute_return=None)
        assert repo.get_scene_at_timestamp("vid-1", 999.0) is None


# ===========================================================================
# get_transcript_segments
# ===========================================================================


@pytest.mark.unit
class TestGetTranscriptSegments:
    def test_full_transcript(self):
        segments = [
            {"timestamp": 0.0, "text": "Hello", "speaker": "A", "confidence": 0.9},
            {"timestamp": 1.0, "text": "World", "speaker": "A", "confidence": 0.9},
        ]
        repo, exec_fn, _ = _make_repo(execute_return=segments)
        result = repo.get_transcript_segments("vid-1")
        assert result == segments
        # Should use the simple full-list query (no chain walk)
        query = exec_fn.call_args.args[0]
        assert "ORDER BY a.start_time" in query

    def test_range_query_with_chain_walk(self):
        repo, _, sess_fn = _make_repo()
        anchor = {"id": "seg-5"}
        chain_data = [
            {"timestamp": 10.0, "text": "First", "speaker": None, "confidence": 0.8},
            {"timestamp": 11.0, "text": "Second", "speaker": None, "confidence": 0.8},
        ]
        session = _make_session(run_results=[anchor, chain_data])
        sess_fn.return_value = session

        result = repo.get_transcript_segments("vid-1", start_time=10.0, end_time=15.0)
        assert len(result) == 2
        assert result[0]["text"] == "First"

    def test_range_query_falls_back_to_property(self):
        repo, exec_fn, sess_fn = _make_repo()
        # Chain walk: no anchor found
        session = _make_session(run_results=[None])
        sess_fn.return_value = session

        fallback_data = [
            {"timestamp": 10.0, "text": "Fallback", "speaker": None, "confidence": 0.7}
        ]
        exec_fn.return_value = fallback_data

        result = repo.get_transcript_segments("vid-1", start_time=10.0, end_time=15.0)
        assert result == fallback_data


# ===========================================================================
# get_frames_in_window
# ===========================================================================


@pytest.mark.unit
class TestGetFramesInWindow:
    def test_chain_walk_returns_frames(self):
        repo, _, sess_fn = _make_repo()
        anchor = {"id": "f-10", "ts": 12.0}
        frames = [
            {"timestamp": 10.0, "description": "Frame A"},
            {"timestamp": 12.0, "description": "Frame B"},
            {"timestamp": 14.0, "description": "Frame C"},
        ]
        session = _make_session(run_results=[anchor, frames])
        sess_fn.return_value = session

        result = repo.get_frames_in_window("vid-1", 5.0, 20.0, center_timestamp=12.0)
        assert len(result) == 3

    def test_falls_back_when_no_anchor(self):
        repo, exec_fn, sess_fn = _make_repo()
        session = _make_session(run_results=[None])
        sess_fn.return_value = session

        fallback = [{"timestamp": 10.0, "description": "Fallback frame"}]
        exec_fn.return_value = fallback

        result = repo.get_frames_in_window("vid-1", 5.0, 20.0)
        assert result == fallback


# ===========================================================================
# get_audio_in_window
# ===========================================================================


@pytest.mark.unit
class TestGetAudioInWindow:
    def test_chain_walk_returns_audio(self):
        repo, _, sess_fn = _make_repo()
        anchor = {"id": "a-5"}
        audio = [
            {"timestamp": 10.0, "text": "Audio A"},
            {"timestamp": 12.0, "text": "Audio B"},
        ]
        session = _make_session(run_results=[anchor, audio])
        sess_fn.return_value = session

        result = repo.get_audio_in_window("vid-1", 5.0, 20.0, center_timestamp=10.0)
        assert len(result) == 2

    def test_falls_back_when_chain_empty(self):
        repo, exec_fn, sess_fn = _make_repo()
        # Anchor found but chain walk returns empty
        anchor = {"id": "a-5"}
        session = _make_session(run_results=[anchor, []])
        sess_fn.return_value = session

        fallback = [{"timestamp": 10.0, "text": "Fallback audio"}]
        exec_fn.return_value = fallback

        result = repo.get_audio_in_window("vid-1", 5.0, 20.0)
        assert result == fallback


# ===========================================================================
# find_entity_appearances
# ===========================================================================


@pytest.mark.unit
class TestFindEntityAppearances:
    def test_returns_visual_and_audio(self):
        visual = [
            {"name": "Cat", "entity_type": "object", "timestamp": 5.0, "description": "A cat"}
        ]
        audio = [{"timestamp": 10.0, "text": "Look at the cat"}]

        repo, exec_fn, _ = _make_repo()
        exec_fn.side_effect = [visual, audio]

        result = repo.find_entity_appearances("vid-1", "cat")
        assert result["visual"] == visual
        assert result["audio"] == audio
        assert exec_fn.call_count == 2

    def test_returns_empty_when_no_matches(self):
        repo, exec_fn, _ = _make_repo()
        exec_fn.side_effect = [[], []]

        result = repo.find_entity_appearances("vid-1", "nonexistent")
        assert result == {"visual": [], "audio": []}


# ===========================================================================
# get_moments_context (batched — replaces N+1 pattern)
# ===========================================================================


@pytest.mark.unit
class TestGetMomentsContext:
    def test_batched_retrieval(self):
        repo, _, sess_fn = _make_repo()

        frames = [
            {"timestamp": 5.0, "description": "Frame at 5"},
            {"timestamp": 15.0, "description": "Frame at 15"},
            {"timestamp": 25.0, "description": "Frame at 25"},
        ]
        audio = [
            {"timestamp": 9.0, "text": "Near 10", "speaker": "A"},
            {"timestamp": 19.0, "text": "Near 20", "speaker": "B"},
        ]
        session = _make_session(run_results=[frames, audio])
        sess_fn.return_value = session

        result = repo.get_moments_context("vid-1", [10.0, 20.0], window=5.0)

        assert len(result) == 2
        # First moment (ts=10): nearest frame is 5.0 (dist 5) vs 15.0 (dist 5) — picks first
        assert result[0]["timestamp"] == 10.0
        assert result[0]["visual"] is not None
        # Audio within window [5, 15]
        assert len(result[0]["audio"]) == 1
        assert result[0]["audio"][0]["text"] == "Near 10"

        # Second moment (ts=20): nearest frame is 15 or 25
        assert result[1]["timestamp"] == 20.0
        assert result[1]["visual"] is not None
        assert len(result[1]["audio"]) == 1
        assert result[1]["audio"][0]["text"] == "Near 20"

    def test_empty_timestamps(self):
        repo, _, _ = _make_repo()
        result = repo.get_moments_context("vid-1", [])
        assert result == []

    def test_single_query_count(self):
        """Ensure only 2 queries are executed (frames + audio), not N+1."""
        repo, _, sess_fn = _make_repo()
        session = _make_session(run_results=[[], []])
        sess_fn.return_value = session

        repo.get_moments_context("vid-1", [10.0, 20.0, 30.0], window=5.0)
        assert session.run.call_count == 2  # frames + audio, NOT 2*3=6
