from __future__ import annotations

# ruff: noqa: S101
from qprisma_video_pipeline import gold


def test_list_strings_flattens_supported_payload_shapes() -> None:
    assert gold.list_strings(
        [
            "person",
            {"name": "screen", "ignored": "value"},
            {"entity": "Databricks"},
            ["nested", {"text": "caption"}],
            42,
        ]
    ) == ["person", "screen", "Databricks", "nested", "caption"]


def test_unique_strings_deduplicates_case_insensitively_and_limits() -> None:
    assert gold.unique_strings(["Car", "car", "Bike", "Plane"], limit=2) == ["Car", "Bike"]


def test_scene_boundaries_use_midpoints_and_duration_tail() -> None:
    boundaries = gold.scene_boundaries(
        [
            {"timestamp_ms": 0},
            {"timestamp_ms": 10_000},
            {"timestamp_ms": 20_000},
        ],
        duration_seconds=30.0,
    )

    assert boundaries == [(0.0, 5.0), (5.0, 15.0), (15.0, 30.0)]


def test_transcript_segments_for_range_returns_overlapping_text() -> None:
    text = gold.transcript_segments_for_range(
        [
            {"start_ms": 0, "end_ms": 1_000, "text": "before"},
            {"start_ms": 1_000, "end_ms": 2_000, "text": "inside"},
            {"start_ms": 3_000, "end_ms": 4_000, "text": "after"},
        ],
        start_seconds=0.5,
        end_seconds=2.5,
    )

    assert text == "before inside"
