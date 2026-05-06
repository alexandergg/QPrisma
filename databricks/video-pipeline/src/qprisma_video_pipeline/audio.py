"""FFmpeg audio extraction, ASR chunking, and faster-whisper persistence."""

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

def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audio_duration_seconds(path: str) -> float:
    result = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
        ]
    )
    return float(result.stdout.strip() or 0.0)


def extract_audio_asset(source_uri: str) -> dict:
    input_path = ffmpeg_input_path(source_uri)
    audio_dir = volume_path(media_id, dispatch_id, "audio")
    audio_path = f"{audio_dir}/audio_16khz_mono.wav"
    local_audio_path = local_artifact_path(media_id, dispatch_id, "audio", "audio_16khz_mono.wav")
    os.makedirs(os.path.dirname(local_audio_path), exist_ok=True)

    run_command(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            input_path,
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            local_audio_path,
        ]
    )
    copy_local_file_to_volume(local_audio_path, audio_path)

    duration = audio_duration_seconds(local_audio_path)
    size_bytes = os.path.getsize(local_audio_path)
    asset_id = f"{media_id}:audio:16khz_mono:{config_hash[:12]}"
    return {
        "audio_asset_id": asset_id,
        "source_uri": source_uri,
        "audio_uri": audio_path,
        "format": "wav",
        "codec": "pcm_s16le",
        "sample_rate_hz": 16000,
        "channels": 1,
        "duration_seconds": duration,
        "size_bytes": size_bytes,
        "sha256": file_sha256(local_audio_path),
    }


def asr_chunk_config() -> dict:
    cfg = pipeline_config.get("faster_whisper") or pipeline_config.get("asr") or {}
    if not isinstance(cfg, dict):
        raise ValueError("pipeline_config.faster_whisper/asr must be an object when provided")
    target_seconds = bounded_float(
        "chunk_target_seconds",
        cfg.get("chunk_target_seconds"),
        default=300.0,
        minimum=30.0,
        maximum=1800.0,
    )
    overlap_seconds = bounded_float(
        "chunk_overlap_seconds",
        cfg.get("chunk_overlap_seconds"),
        default=5.0,
        minimum=0.0,
        maximum=60.0,
    )
    min_chunk_seconds = bounded_float(
        "min_chunk_seconds",
        cfg.get("min_chunk_seconds"),
        default=2.0,
        minimum=0.1,
        maximum=60.0,
    )
    if overlap_seconds >= target_seconds:
        raise ValueError("ASR chunk overlap must be smaller than target chunk duration")
    return {
        "target_seconds": target_seconds,
        "overlap_seconds": overlap_seconds,
        "min_chunk_seconds": min_chunk_seconds,
        "max_chunks": bounded_int("max_chunks", cfg.get("max_chunks"), default=200, minimum=1, maximum=2000),
    }


def audio_chunk_ranges(duration_seconds: float, config: dict) -> list[tuple[int, float, float]]:
    if duration_seconds <= 0:
        return []
    ranges = []
    start = 0.0
    target = float(config["target_seconds"])
    overlap = float(config["overlap_seconds"])
    min_chunk = float(config["min_chunk_seconds"])
    while start < duration_seconds and len(ranges) < int(config["max_chunks"]):
        end = min(duration_seconds, start + target)
        if end - start >= min_chunk or not ranges:
            ranges.append((len(ranges), round(start, 3), round(end, 3)))
        if end >= duration_seconds:
            break
        start = max(0.0, end - overlap)
    if not ranges:
        ranges.append((0, 0.0, round(duration_seconds, 3)))
    if ranges[-1][2] + 0.001 < duration_seconds:
        raise ValueError(
            "Audio duration exceeds configured ASR chunk coverage. Increase asr.max_chunks "
            "or asr.chunk_target_seconds within bounded limits."
        )
    return ranges


def build_audio_chunk_rows(audio_asset: dict) -> list[dict]:
    config = asr_chunk_config()
    ranges = audio_chunk_ranges(float(audio_asset["duration_seconds"]), config)
    chunk_dir = volume_path(media_id, dispatch_id, "audio", "chunks")
    now = datetime.now(UTC)
    rows = []
    for chunk_index, start_seconds, end_seconds in ranges:
        duration_seconds = round(max(0.0, end_seconds - start_seconds), 3)
        chunk_path = f"{chunk_dir}/chunk_{chunk_index:06d}_{int(start_seconds * 1000):012d}.wav"
        local_chunk_path = local_artifact_path(
            media_id,
            dispatch_id,
            "audio",
            "chunks",
            f"chunk_{chunk_index:06d}_{int(start_seconds * 1000):012d}.wav",
        )
        os.makedirs(os.path.dirname(local_chunk_path), exist_ok=True)
        run_command(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{start_seconds:.3f}",
                "-i",
                audio_asset["audio_uri"],
                "-t",
                f"{duration_seconds:.3f}",
                "-acodec",
                "pcm_s16le",
                "-ar",
                "16000",
                "-ac",
                "1",
                local_chunk_path,
            ]
        )
        copy_local_file_to_volume(local_chunk_path, chunk_path)
        rows.append(
            {
                "chunk_id": f"{audio_asset['audio_asset_id']}:chunk:{chunk_index:06d}",
                "audio_asset_id": audio_asset["audio_asset_id"],
                "media_id": media_id,
                "dispatch_id": dispatch_id,
                "chunk_index": chunk_index,
                "start_ms": int(start_seconds * 1000),
                "end_ms": int(end_seconds * 1000),
                "audio_uri": chunk_path,
                "duration_seconds": duration_seconds,
                "created_at": now,
            }
        )
    return rows


def register_audio_asset(audio_asset: dict, chunks: list[dict]) -> None:
    now = datetime.now(UTC)
    merge_row(
        qualified_audio_assets_table,
        {
            **audio_asset,
            "media_id": media_id,
            "dispatch_id": dispatch_id,
            "created_at": now,
            "updated_at": now,
        },
        AUDIO_ASSETS_SCHEMA,
        ["audio_asset_id"],
    )
    for chunk in chunks:
        merge_row(qualified_audio_chunks_table, chunk, AUDIO_CHUNKS_SCHEMA, ["chunk_id"])


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def faster_whisper_config() -> dict:
    cfg = pipeline_config.get("faster_whisper") or pipeline_config.get("asr") or {}
    if not isinstance(cfg, dict):
        raise ValueError("pipeline_config.faster_whisper/asr must be an object when provided")
    explicit_model = cfg.get("model_name") or cfg.get("model_size")
    preset = str(cfg.get("preset") or ("custom" if explicit_model else "quality")).strip().lower()
    preset_models = {
        "fast": str(cfg.get("fast_model_name") or "turbo"),
        "balanced": str(cfg.get("balanced_model_name") or "distil-large-v3"),
        "quality": str(cfg.get("quality_model_name") or "large-v3"),
        "custom": str(explicit_model or "large-v3"),
    }
    if preset not in preset_models:
        raise ValueError("ASR preset must be one of: fast, balanced, quality, custom")
    return {
        "preset": preset,
        "model_name": str(explicit_model or preset_models[preset]),
        "device": str(cfg.get("device") or "auto"),
        "compute_type": str(cfg.get("compute_type") or "int8"),
        "batch_size": int(cfg.get("batch_size") or 16),
        "language": cfg.get("language") or pipeline_config.get("language"),
    }


def load_audio_chunks() -> list[dict]:
    rows = spark.sql(
        f"""
        SELECT
          chunk_id,
          audio_asset_id,
          chunk_index,
          start_ms,
          end_ms,
          audio_uri,
          duration_seconds
        FROM {qualified_audio_chunks_table}
        WHERE media_id = {sql_literal(media_id)}
          AND dispatch_id = {sql_literal(dispatch_id)}
        ORDER BY chunk_index
        """
    ).collect()
    if not rows:
        raise ValueError(
            f"No audio chunks found for media_id={media_id}, dispatch_id={dispatch_id}. "
            "Run extract_audio_assets first."
        )
    return [row.asDict() for row in rows]


def load_source_quality() -> dict:
    rows = spark.sql(
        f"""
        SELECT quality_status, quality_details, has_audio
        FROM {qualified_source_files_table}
        WHERE media_id = {sql_literal(media_id)}
          AND dispatch_id = {sql_literal(dispatch_id)}
        ORDER BY validated_at DESC
        LIMIT 1
        """
    ).collect()
    if not rows:
        raise ValueError(
            f"No validated source file found for media_id={media_id}, dispatch_id={dispatch_id}. "
            "Run validate_and_probe_media first."
        )
    row = rows[0].asDict()
    quality = parse_json_dict(row.get("quality_details"))
    if not quality:
        quality = {
            "status": row.get("quality_status") or "unknown",
            "metadata": {"has_audio": str(row.get("has_audio")).lower() == "true"},
        }
    return quality


def source_has_audio() -> bool:
    quality = load_source_quality()
    metadata = quality.get("metadata") or {}
    return bool(metadata.get("has_audio"))


def write_asr_run(
    *,
    asr_run_id: str,
    audio_asset_id: str,
    model_config: dict,
    status: str,
    transcript_text: str = "",
    language: str | None = None,
    language_probability: float | None = None,
    duration_seconds: float | None = None,
    segment_count: int = 0,
    metrics: dict | None = None,
    error: dict | None = None,
    started_at: datetime | None = None,
    completed: bool = False,
) -> None:
    now = datetime.now(UTC)
    merge_row(
        qualified_asr_runs_table,
        {
            "asr_run_id": asr_run_id,
            "media_id": media_id,
            "dispatch_id": dispatch_id,
            "audio_asset_id": audio_asset_id,
            "model_name": model_config["model_name"],
            "device": model_config["device"],
            "compute_type": model_config["compute_type"],
            "batch_size": int(model_config["batch_size"]),
            "language": language,
            "language_probability": language_probability,
            "duration_seconds": duration_seconds,
            "segment_count": int(segment_count),
            "transcript_text": transcript_text,
            "status": status,
            "started_at": started_at or now,
            "completed_at": now if completed else None,
            "metrics": json_dumps(metrics or {}),
            "error": json_dumps(error or {}),
        },
        ASR_RUNS_SCHEMA,
        ["asr_run_id"],
    )


def transcribe_audio_chunks(chunks: list[dict], model_config: dict) -> dict:
    try:
        from faster_whisper import BatchedInferencePipeline, WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed on the Databricks job cluster. "
            "Install the task PyPI dependency before running run_faster_whisper_asr."
        ) from exc

    model = WhisperModel(
        model_config["model_name"],
        device=model_config["device"],
        compute_type=model_config["compute_type"],
    )
    pipeline = BatchedInferencePipeline(model=model)
    result_segments: list[dict] = []
    text_parts: list[str] = []
    detected_language = None
    detected_language_probability = None
    segment_index = 0
    emitted_until_ms = 0
    inference_started = time.perf_counter()

    chunk_metrics = []
    for chunk in chunks:
        chunk_offset_seconds = float(chunk["start_ms"]) / 1000
        chunk_started = time.perf_counter()
        emitted_before = segment_index
        segments_iter, info = pipeline.transcribe(
            chunk["audio_uri"],
            language=model_config.get("language"),
            batch_size=int(model_config["batch_size"]),
            vad_filter=True,
            vad_parameters={
                "min_silence_duration_ms": 500,
                "speech_pad_ms": 200,
            },
        )
        detected_language = detected_language or info.language
        detected_language_probability = detected_language_probability or info.language_probability

        for segment in segments_iter:
            text = segment.text.strip()
            if not text:
                continue
            start_seconds = chunk_offset_seconds + float(segment.start)
            end_seconds = chunk_offset_seconds + float(segment.end)
            start_ms = int(start_seconds * 1000)
            end_ms = int(end_seconds * 1000)
            if start_ms < emitted_until_ms:
                continue
            result_segments.append(
                {
                    "segment_index": segment_index,
                    "chunk_id": chunk["chunk_id"],
                    "audio_asset_id": chunk["audio_asset_id"],
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "text": text,
                    "language": detected_language,
                    "confidence": None,
                }
            )
            text_parts.append(text)
            segment_index += 1
        emitted_until_ms = max(emitted_until_ms, int(chunk["end_ms"]))
        chunk_elapsed = time.perf_counter() - chunk_started
        chunk_audio_seconds = float(chunk["duration_seconds"] or 0)
        chunk_metrics.append(
            {
                "chunk_id": chunk["chunk_id"],
                "duration_seconds": rounded_metric(chunk_audio_seconds),
                "elapsed_seconds": rounded_metric(chunk_elapsed),
                "audio_seconds_per_second": rate_metric(chunk_audio_seconds, chunk_elapsed),
                "segment_count": segment_index - emitted_before,
            }
        )

    elapsed = time.perf_counter() - inference_started
    audio_seconds = sum(float(chunk["duration_seconds"] or 0) for chunk in chunks)
    return {
        "text": " ".join(text_parts),
        "segments": result_segments,
        "language": detected_language,
        "language_probability": detected_language_probability,
        "duration_seconds": audio_seconds,
        "elapsed_seconds": elapsed,
        "real_time_factor": (elapsed / audio_seconds) if audio_seconds > 0 else None,
        "audio_seconds_per_second": rate_metric(audio_seconds, elapsed),
        "seconds_per_chunk": (elapsed / len(chunks)) if chunks else None,
        "chunk_metrics": chunk_metrics,
    }


def write_transcript_segments(asr_run_id: str, segments: list[dict]) -> None:
    now = datetime.now(UTC)
    for segment in segments:
        merge_row(
            qualified_transcript_segments_table,
            {
                "segment_id": f"{asr_run_id}:segment:{segment['segment_index']:06d}",
                "asr_run_id": asr_run_id,
                "media_id": media_id,
                "dispatch_id": dispatch_id,
                "audio_asset_id": segment["audio_asset_id"],
                "chunk_id": segment["chunk_id"],
                "segment_index": int(segment["segment_index"]),
                "start_ms": int(segment["start_ms"]),
                "end_ms": int(segment["end_ms"]),
                "text": segment["text"],
                "language": segment["language"],
                "confidence": segment["confidence"],
                "created_at": now,
            },
            TRANSCRIPT_SEGMENTS_SCHEMA,
            ["segment_id"],
        )

