"""Frame extraction, timestamp sampling, and frame asset persistence."""

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

def frame_extraction_config() -> dict:
    cfg = pipeline_config.get("frames") or pipeline_config.get("frame_extraction") or {}
    if not isinstance(cfg, dict):
        raise ValueError("pipeline_config.frames/frame_extraction must be an object when provided")
    interval_seconds = cfg.get("interval_seconds") or pipeline_config.get("frame_interval")
    return {
        "method": str(cfg.get("method") or "uniform"),
        "max_frames": bounded_int(
            "max_frames",
            cfg.get("max_frames") or pipeline_config.get("max_frames"),
            default=20,
            minimum=1,
            maximum=120,
        ),
        "interval_seconds": None
        if interval_seconds is None
        else bounded_float(
            "interval_seconds",
            interval_seconds,
            default=10.0,
            minimum=0.5,
            maximum=600.0,
        ),
        "format": str(cfg.get("format") or "jpg"),
        "quality": bounded_int("quality", cfg.get("quality"), default=2, minimum=1, maximum=31),
        "min_spacing_seconds": bounded_float(
            "min_spacing_seconds",
            cfg.get("min_spacing_seconds"),
            default=0.2,
            minimum=0.0,
            maximum=60.0,
        ),
        "dedupe_hashes": config_bool(cfg.get("dedupe_hashes"), default=True),
    }


def ffprobe_video_metadata(input_path: str) -> dict:
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
    if not video_stream:
        raise ValueError("No video stream found for frame extraction")
    format_info = probe.get("format", {})
    return {
        "duration_seconds": float(format_info.get("duration") or 0),
        "width": int(video_stream.get("width") or 0),
        "height": int(video_stream.get("height") or 0),
        "codec": video_stream.get("codec_name") or "",
    }


def frame_timestamps(video_metadata: dict, config: dict) -> list[float]:
    duration = float(video_metadata["duration_seconds"] or 0)
    max_frames = max(1, int(config["max_frames"]))
    method = config["method"].lower()
    interval = config.get("interval_seconds")

    if duration <= 0:
        return [0.0]
    if method == "interval" and interval:
        timestamps = []
        current = 0.0
        while current < duration and len(timestamps) < max_frames:
            timestamps.append(current)
            current += float(interval)
        return timestamps or [min(duration / 2, max(duration - 0.1, 0))]
    if max_frames == 1:
        return [min(duration / 2, max(duration - 0.1, 0))]

    step = duration / (max_frames - 1)
    return [min(index * step, max(duration - 0.1, 0)) for index in range(max_frames)]


def dedupe_frame_timestamps(timestamps: list[float], min_spacing_seconds: float) -> list[float]:
    if min_spacing_seconds <= 0:
        return timestamps
    deduped: list[float] = []
    for timestamp in timestamps:
        rounded_timestamp = round(float(timestamp), 3)
        if not deduped or rounded_timestamp - deduped[-1] >= min_spacing_seconds:
            deduped.append(rounded_timestamp)
    return deduped or timestamps[:1]


def extract_frame_assets(source_uri: str) -> list[dict]:
    input_path = ffmpeg_input_path(source_uri)
    config = frame_extraction_config()
    metadata = ffprobe_video_metadata(input_path)
    timestamps = dedupe_frame_timestamps(
        frame_timestamps(metadata, config),
        float(config["min_spacing_seconds"]),
    )
    frame_format = config["format"].lower()
    if frame_format not in {"jpg", "jpeg", "png", "webp"}:
        raise ValueError("Frame format must be one of: jpg, jpeg, png, webp")

    frame_dir = volume_path(media_id, dispatch_id, "frames")
    frames: list[dict] = []
    extension = "jpg" if frame_format == "jpeg" else frame_format
    seen_hashes: set[str] = set()

    for index, timestamp_seconds in enumerate(timestamps):
        timestamp_ms = int(timestamp_seconds * 1000)
        frame_path = f"{frame_dir}/frame_{index:06d}_{timestamp_ms:012d}.{extension}"
        local_frame_path = local_artifact_path(
            media_id,
            dispatch_id,
            "frames",
            f"frame_{index:06d}_{timestamp_ms:012d}.{extension}",
        )
        os.makedirs(os.path.dirname(local_frame_path), exist_ok=True)
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{timestamp_seconds:.3f}",
            "-i",
            input_path,
            "-frames:v",
            "1",
        ]
        if extension in {"jpg", "webp"}:
            command.extend(["-q:v", str(config["quality"])])
        command.append(local_frame_path)
        run_command(command)
        frame_sha256 = file_sha256(local_frame_path)
        if config["dedupe_hashes"] and frame_sha256 in seen_hashes:
            try:
                os.remove(local_frame_path)
            except FileNotFoundError:
                pass
            continue
        seen_hashes.add(frame_sha256)
        copy_local_file_to_volume(local_frame_path, frame_path)
        frame_asset_id = f"{media_id}:frame:{index:06d}:{timestamp_ms}:{config_hash[:12]}"
        frames.append(
            {
                "frame_asset_id": frame_asset_id,
                "source_uri": source_uri,
                "frame_uri": frame_path,
                "frame_index": index,
                "timestamp_ms": timestamp_ms,
                "format": extension,
                "width": metadata["width"],
                "height": metadata["height"],
                "size_bytes": os.path.getsize(local_frame_path),
                "sha256": frame_sha256,
                "extraction_method": config["method"],
            }
        )
    return frames


def register_frame_assets(frame_assets: list[dict]) -> None:
    now = datetime.now(UTC)
    for frame_asset in frame_assets:
        merge_row(
            qualified_frame_assets_table,
            {
                **frame_asset,
                "media_id": media_id,
                "dispatch_id": dispatch_id,
                "created_at": now,
                "updated_at": now,
            },
            FRAME_ASSETS_SCHEMA,
            ["frame_asset_id"],
        )

