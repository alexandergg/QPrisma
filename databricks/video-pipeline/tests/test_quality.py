from __future__ import annotations

# ruff: noqa: S101
import pytest
from qprisma_video_pipeline import quality


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("30000/1001", pytest.approx(29.97002997)),
        ("25", 25.0),
        ("0/0", None),
        ("not-a-rate", None),
    ],
)
def test_frame_rate_parsing(raw_value: str, expected: object) -> None:
    assert quality.frame_rate(raw_value) == expected


def test_quality_gate_config_uses_bounded_defaults_and_normalizes_codecs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        quality,
        "pipeline_config",
        {"quality_gates": {"allowed_video_codecs": ["H264", "vp9"], "require_audio": True}},
        raising=False,
    )

    cfg = quality.quality_gate_config()

    assert cfg["min_size_bytes"] == 1024
    assert cfg["allowed_video_codecs"] == {"h264", "vp9"}
    assert cfg["require_audio"] is True


def test_quality_gate_config_rejects_out_of_bounds_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(quality, "pipeline_config", {"quality_gates": {"max_fps": 500}}, raising=False)

    with pytest.raises(ValueError, match="max_fps"):
        quality.quality_gate_config()


def test_string_set_rejects_unsupported_types() -> None:
    with pytest.raises(ValueError, match="Expected a comma-separated string or list"):
        quality.string_set({"codec": "h264"})
