from __future__ import annotations

# ruff: noqa: S101
import json

from qprisma_video_pipeline import scenes


def test_scene_boundary_points_include_start_end_gaps_frames_and_forced_boundaries() -> None:
    boundaries = scenes.scene_boundary_points(
        frames=[{"timestamp_ms": 5_000}, {"timestamp_ms": 25_000}],
        segments=[
            {"start_ms": 0, "end_ms": 1_000},
            {"start_ms": 8_000, "end_ms": 9_000},
        ],
        duration=35.0,
        config={"transcript_gap_seconds": 2.5, "max_scene_seconds": 15.0},
    )

    assert boundaries[0] == {"start"}
    assert boundaries[5_000] == {"frame_anchor"}
    assert boundaries[8_000] == {"transcript_gap"}
    assert boundaries[15_000] == {"max_scene_duration"}
    assert boundaries[30_000] == {"max_scene_duration"}
    assert boundaries[35_000] == {"end"}


def test_build_temporal_window_rows_uses_overlap_and_stable_ids(monkeypatch) -> None:
    monkeypatch.setattr(
        scenes,
        "pipeline_config",
        {"scene_detection": {"target_window_seconds": 10, "window_overlap_seconds": 2}},
        raising=False,
    )
    monkeypatch.setattr(scenes, "media_id", "media-1", raising=False)
    monkeypatch.setattr(scenes, "dispatch_id", "dispatch-1", raising=False)
    monkeypatch.setattr(scenes, "config_hash", "abcdef1234567890", raising=False)

    rows = scenes.build_temporal_window_rows(
        frames=[
            {"frame_asset_id": "frame-1", "timestamp_ms": 1_000},
            {"frame_asset_id": "frame-2", "timestamp_ms": 9_000},
            {"frame_asset_id": "frame-3", "timestamp_ms": 12_000},
        ],
        segments=[
            {"segment_id": "segment-1", "start_ms": 0, "end_ms": 2_000},
            {"segment_id": "segment-2", "start_ms": 11_000, "end_ms": 13_000},
        ],
        duration=18.0,
    )

    assert [row["start_ms"] for row in rows] == [0, 8_000]
    assert [row["end_ms"] for row in rows] == [10_000, 18_000]
    assert rows[0]["window_id"] == "media-1:dispatch-1:window:abcdef123456:000000"
    assert json.loads(rows[0]["frame_asset_ids"]) == ["frame-1", "frame-2"]
    assert json.loads(rows[1]["transcript_segment_ids"]) == ["segment-2"]
