"""Tests for evaluation_foundry.generate_eval_data.

Verifies that the data generator correctly:
- Expands video-specific templates across all configured media IDs
- Includes media_ids list in multi-video query context
- Skips rows when required config is missing
- Produces balanced coverage across all configured videos
"""

from __future__ import annotations

import json
import re

import pytest

from evaluation_foundry.data.query_templates import QueryTemplate
from evaluation_foundry.generate_eval_data import (
    _build_query,
    _format_context,
    generate_data_file,
)

# ── Fixtures ──────────────────────────────────────────────────────────────

MEDIA_ID_1 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
MEDIA_ID_2 = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
USER_ID = "user_7541242e88e3"

CONTEXT_RE = re.compile(r"^\[QPRISMA_CONTEXT:(\{.*?\})\]\n", re.DOTALL)


def _extract_context(query: str) -> dict | None:
    """Parse the QPRISMA_CONTEXT JSON from a query string."""
    m = CONTEXT_RE.match(query)
    return json.loads(m.group(1)) if m else None


# ── _format_context ───────────────────────────────────────────────────────


class TestFormatContext:
    def test_empty_when_no_params(self):
        assert _format_context(None, None) == ""

    def test_media_id_only(self):
        result = _format_context(MEDIA_ID_1, None)
        ctx = _extract_context(result + "dummy")
        assert ctx == {"media_id": MEDIA_ID_1}

    def test_user_id_only(self):
        result = _format_context(None, USER_ID)
        ctx = _extract_context(result + "dummy")
        assert ctx == {"user_id": USER_ID}

    def test_media_and_user(self):
        result = _format_context(MEDIA_ID_1, USER_ID)
        ctx = _extract_context(result + "dummy")
        assert ctx == {"media_id": MEDIA_ID_1, "user_id": USER_ID}

    def test_media_ids_list(self):
        result = _format_context(None, USER_ID, media_ids=[MEDIA_ID_1, MEDIA_ID_2])
        ctx = _extract_context(result + "dummy")
        assert ctx["media_ids"] == [MEDIA_ID_1, MEDIA_ID_2]
        assert ctx["user_id"] == USER_ID

    def test_all_fields(self):
        result = _format_context(MEDIA_ID_1, USER_ID, media_ids=[MEDIA_ID_1, MEDIA_ID_2])
        ctx = _extract_context(result + "dummy")
        assert ctx["media_id"] == MEDIA_ID_1
        assert ctx["media_ids"] == [MEDIA_ID_1, MEDIA_ID_2]
        assert ctx["user_id"] == USER_ID

    def test_response_mode_is_opt_in(self):
        result = _format_context(MEDIA_ID_1, USER_ID)
        ctx = _extract_context(result + "dummy")
        assert "response_mode" not in ctx

    def test_response_mode_override_included_when_requested(self):
        result = _format_context(MEDIA_ID_1, USER_ID, response_mode="final_answer")
        ctx = _extract_context(result + "dummy")
        assert ctx["response_mode"] == "final_answer"


# ── _build_query ──────────────────────────────────────────────────────────


class TestBuildQuery:
    def test_general_query_no_context(self):
        t = QueryTemplate(text="What is QPrisma?")
        row = _build_query(t, media_id=None, user_id=None)
        assert row is not None
        assert row["query"] == "What is QPrisma?"
        assert _extract_context(row["query"]) is None

    def test_video_query_includes_media_id(self):
        t = QueryTemplate(text="Summarize this video", needs_media=True)
        row = _build_query(t, media_id=MEDIA_ID_1, user_id=USER_ID)
        assert row is not None
        ctx = _extract_context(row["query"])
        assert ctx["media_id"] == MEDIA_ID_1
        assert ctx["user_id"] == USER_ID
        assert "media_ids" not in ctx

    def test_video_query_skipped_when_no_media_id(self):
        t = QueryTemplate(text="Summarize this video", needs_media=True)
        row = _build_query(t, media_id=None, user_id=USER_ID)
        assert row is None

    def test_multi_video_query_includes_media_ids(self):
        t = QueryTemplate(text="Compare all videos", needs_user=True)
        row = _build_query(
            t,
            media_id=None,
            user_id=USER_ID,
            media_ids=[MEDIA_ID_1, MEDIA_ID_2],
        )
        assert row is not None
        ctx = _extract_context(row["query"])
        assert ctx["media_ids"] == [MEDIA_ID_1, MEDIA_ID_2]
        assert ctx["user_id"] == USER_ID

    def test_multi_video_query_skipped_when_no_user(self):
        t = QueryTemplate(text="Compare all videos", needs_user=True)
        row = _build_query(t, media_id=None, user_id=None, media_ids=[MEDIA_ID_1])
        assert row is None

    def test_ground_truth_included(self):
        t = QueryTemplate(text="Test?", ground_truth="Answer")
        row = _build_query(t, media_id=None, user_id=None)
        assert row is not None
        assert row["ground_truth"] == "Answer"

    def test_tool_definitions_included(self):
        t = QueryTemplate(text="Test?")
        row = _build_query(t, media_id=None, user_id=None, include_tool_definitions=True)
        assert row is not None
        assert "tool_definitions" in row
        assert isinstance(row["tool_definitions"], list)


# ── generate_data_file ────────────────────────────────────────────────────


class TestGenerateDataFile:
    @pytest.fixture
    def mixed_templates(self) -> list[QueryTemplate]:
        """Fixture with one template per category."""
        return [
            QueryTemplate(text="General question"),
            QueryTemplate(text="Video detail", needs_media=True),
            QueryTemplate(text="Cross-video search", needs_user=True),
        ]

    def test_video_templates_expand_across_all_videos(self, mixed_templates):
        result = generate_data_file(
            name="test",
            templates=mixed_templates,
            evaluators=["builtin.coherence"],
            media_ids=[MEDIA_ID_1, MEDIA_ID_2],
            user_id=USER_ID,
        )
        queries = [r["query"] for r in result["data"]]
        # 1 general + 2 video (one per media_id) + 1 multi-video = 4
        assert len(queries) == 4

        # Both video IDs appear in video-specific queries
        video_queries = [q for q in queries if MEDIA_ID_1 in q or MEDIA_ID_2 in q]
        assert any(MEDIA_ID_1 in q for q in video_queries)
        assert any(MEDIA_ID_2 in q for q in video_queries)

    def test_multi_video_query_has_media_ids(self, mixed_templates):
        result = generate_data_file(
            name="test",
            templates=mixed_templates,
            evaluators=["builtin.coherence"],
            media_ids=[MEDIA_ID_1, MEDIA_ID_2],
            user_id=USER_ID,
        )
        multi_rows = [r for r in result["data"] if "Cross-video search" in r["query"]]
        assert len(multi_rows) == 1
        ctx = _extract_context(multi_rows[0]["query"])
        assert ctx is not None
        assert ctx["media_ids"] == [MEDIA_ID_1, MEDIA_ID_2]

    def test_no_media_ids_skips_video_templates(self):
        templates = [
            QueryTemplate(text="General question"),
            QueryTemplate(text="Video detail", needs_media=True),
        ]
        result = generate_data_file(
            name="test",
            templates=templates,
            evaluators=["builtin.coherence"],
            media_ids=[],
            user_id=USER_ID,
        )
        # Only general query survives — video query has needs_media but
        # the expansion loop is skipped since media_ids is empty, and the
        # else branch passes media_id=None which triggers the skip
        assert len(result["data"]) == 1
        assert "General question" in result["data"][0]["query"]

    def test_balanced_coverage_across_videos(self):
        """Every video-specific template produces one row per video."""
        templates = [
            QueryTemplate(text="Q1", needs_media=True),
            QueryTemplate(text="Q2", needs_media=True),
            QueryTemplate(text="Q3", needs_media=True),
        ]
        result = generate_data_file(
            name="test",
            templates=templates,
            evaluators=["builtin.coherence"],
            media_ids=[MEDIA_ID_1, MEDIA_ID_2],
            user_id=USER_ID,
        )
        # 3 templates × 2 videos = 6 rows
        assert len(result["data"]) == 6
        v1_count = sum(1 for r in result["data"] if MEDIA_ID_1 in r["query"])
        v2_count = sum(1 for r in result["data"] if MEDIA_ID_2 in r["query"])
        assert v1_count == 3
        assert v2_count == 3

    def test_evaluators_and_structure(self, mixed_templates):
        evals = ["builtin.coherence", "builtin.fluency"]
        result = generate_data_file(
            name="my-eval",
            templates=mixed_templates,
            evaluators=evals,
            media_ids=[MEDIA_ID_1],
            user_id=USER_ID,
        )
        assert result["name"] == "my-eval"
        assert result["evaluators"] == evals
        assert isinstance(result["data"], list)
        assert result["data_mapping"] == {}

    def test_tool_definitions_in_data_mapping(self, mixed_templates):
        result = generate_data_file(
            name="test",
            templates=mixed_templates,
            evaluators=["builtin.coherence"],
            media_ids=[MEDIA_ID_1],
            user_id=USER_ID,
            include_tool_definitions=True,
        )
        assert "tool_definitions" in result["data_mapping"]
        assert all("tool_definitions" in r for r in result["data"])
