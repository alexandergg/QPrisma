"""FFprobe metadata extraction and Bronze source quality gates."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from .contracts import *

class QualityGateError(ValueError):
    """Raised when source media fails pre-inference quality gates."""

    def __init__(self, quality: dict):
        self.quality = quality
        super().__init__(json_dumps(quality))


def string_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {item.strip().lower() for item in value.split(",") if item.strip()}
    if isinstance(value, list):
        return {str(item).strip().lower() for item in value if str(item).strip()}
    raise ValueError(f"Expected a comma-separated string or list, got {value!r}")


def bounded_int(name: str, value: Any, *, default: int, minimum: int, maximum: int) -> int:
    parsed = int(value if value is not None else default)
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"quality_gates.{name} must be between {minimum} and {maximum}")
    return parsed


def bounded_float(name: str, value: Any, *, default: float, minimum: float, maximum: float) -> float:
    parsed = float(value if value is not None else default)
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"quality_gates.{name} must be between {minimum} and {maximum}")
    return parsed


def quality_gate_config() -> dict:
    cfg = pipeline_config.get("quality_gates") or pipeline_config.get("quality") or {}
    if not isinstance(cfg, dict):
        raise ValueError("pipeline_config.quality_gates/quality must be an object when provided")
    return {
        "min_size_bytes": bounded_int(
            "min_size_bytes", cfg.get("min_size_bytes"), default=1024, minimum=1, maximum=1024 * 1024
        ),
        "max_size_bytes": bounded_int(
            "max_size_bytes",
            cfg.get("max_size_bytes"),
            default=20 * 1024 * 1024 * 1024,
            minimum=1024,
            maximum=50 * 1024 * 1024 * 1024,
        ),
        "min_duration_seconds": bounded_float(
            "min_duration_seconds", cfg.get("min_duration_seconds"), default=0.1, minimum=0.001, maximum=60
        ),
        "max_duration_seconds": bounded_float(
            "max_duration_seconds", cfg.get("max_duration_seconds"), default=4 * 60 * 60, minimum=1, maximum=8 * 60 * 60
        ),
        "max_width": bounded_int("max_width", cfg.get("max_width"), default=7680, minimum=64, maximum=8192),
        "max_height": bounded_int("max_height", cfg.get("max_height"), default=4320, minimum=64, maximum=8192),
        "max_fps": bounded_float("max_fps", cfg.get("max_fps"), default=120, minimum=1, maximum=240),
        "require_audio": config_bool(cfg.get("require_audio"), default=False),
        "sample_decode_seconds": bounded_float(
            "sample_decode_seconds", cfg.get("sample_decode_seconds"), default=1.0, minimum=0.1, maximum=30
        ),
        "allowed_video_codecs": string_set(
            cfg.get("allowed_video_codecs") or "av1,h264,hevc,mjpeg,mpeg4,vp8,vp9"
        ),
    }


def frame_rate(value: str | None) -> float | None:
    if not value:
        return None
    try:
        if "/" not in value:
            return float(value)
        numerator, denominator = value.split("/", 1)
        denominator_float = float(denominator or 0)
        if denominator_float == 0:
            return None
        return float(numerator) / denominator_float
    except ValueError:
        return None


def ffprobe_source_metadata(input_path: str) -> dict:
    result = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            input_path,
        ]
    )
    probe = json.loads(result.stdout or "{}")
    video_stream = next(
        (stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video"),
        None,
    )
    audio_stream = next(
        (stream for stream in probe.get("streams", []) if stream.get("codec_type") == "audio"),
        None,
    )
    format_info = probe.get("format", {})
    return {
        "format_name": format_info.get("format_name"),
        "duration_seconds": float(format_info.get("duration") or 0),
        "video_codec": video_stream.get("codec_name") if video_stream else None,
        "audio_codec": audio_stream.get("codec_name") if audio_stream else None,
        "width": int(video_stream.get("width") or 0) if video_stream else None,
        "height": int(video_stream.get("height") or 0) if video_stream else None,
        "fps": frame_rate(video_stream.get("avg_frame_rate")) if video_stream else None,
        "has_audio": audio_stream is not None,
        "has_video": video_stream is not None,
        "stream_count": len(probe.get("streams", [])),
    }


def verify_decode_sample(input_path: str, metadata: dict, config: dict) -> None:
    sample_seconds = float(config["sample_decode_seconds"])
    if sample_seconds <= 0:
        return
    duration_seconds = float(metadata.get("duration_seconds") or 0)
    seek_seconds = max(0.0, min(duration_seconds / 2, max(duration_seconds - sample_seconds, 0.0)))
    run_command(
        [
            "ffmpeg",
            "-hide_banner",
            "-v",
            "error",
            "-ss",
            f"{seek_seconds:.3f}",
            "-i",
            input_path,
            "-t",
            f"{sample_seconds:.3f}",
            "-map",
            "0:v:0",
            "-f",
            "null",
            "-",
        ]
    )


def evaluate_source_quality(uri: str, probe: dict) -> dict:
    input_path = ffmpeg_input_path(uri)
    config = quality_gate_config()
    metadata = ffprobe_source_metadata(input_path)
    violations: list[dict] = []

    length = int(probe["length"])
    duration = float(metadata.get("duration_seconds") or 0)
    width = int(metadata.get("width") or 0)
    height = int(metadata.get("height") or 0)
    fps = float(metadata.get("fps") or 0)
    video_codec = str(metadata.get("video_codec") or "").lower()

    if length < config["min_size_bytes"]:
        violations.append({"gate": "min_size_bytes", "actual": length, "expected": config["min_size_bytes"]})
    if length > config["max_size_bytes"]:
        violations.append({"gate": "max_size_bytes", "actual": length, "expected": config["max_size_bytes"]})
    if not metadata.get("has_video"):
        violations.append({"gate": "has_video", "actual": False, "expected": True})
    if duration < config["min_duration_seconds"]:
        violations.append(
            {"gate": "min_duration_seconds", "actual": duration, "expected": config["min_duration_seconds"]}
        )
    if duration > config["max_duration_seconds"]:
        violations.append(
            {"gate": "max_duration_seconds", "actual": duration, "expected": config["max_duration_seconds"]}
        )
    if width > config["max_width"] or height > config["max_height"]:
        violations.append(
            {
                "gate": "max_resolution",
                "actual": {"width": width, "height": height},
                "expected": {"width": config["max_width"], "height": config["max_height"]},
            }
        )
    if fps > config["max_fps"]:
        violations.append({"gate": "max_fps", "actual": fps, "expected": config["max_fps"]})
    if config["require_audio"] and not metadata.get("has_audio"):
        violations.append({"gate": "require_audio", "actual": False, "expected": True})
    if video_codec and video_codec not in config["allowed_video_codecs"]:
        violations.append(
            {
                "gate": "allowed_video_codecs",
                "actual": video_codec,
                "expected": sorted(config["allowed_video_codecs"]),
            }
        )

    if not violations:
        try:
            verify_decode_sample(input_path, metadata, config)
        except RuntimeError as exc:
            violations.append({"gate": "decode_sample", "actual": "failed", "expected": "readable"})
            metadata["decode_error"] = str(exc)

    quality = {
        "status": "passed" if not violations else "failed",
        "config": {**config, "allowed_video_codecs": sorted(config["allowed_video_codecs"])},
        "metadata": metadata,
        "violations": violations,
    }
    if violations:
        raise QualityGateError(quality)
    return quality

