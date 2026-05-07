"""Configuration parsing, sanitization, and safe persistence helpers."""

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

def parse_json_object(raw_value: str, field_name: str) -> dict:
    try:
        parsed = json.loads(raw_value or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"Parameter '{field_name}' must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"Parameter '{field_name}' must be a JSON object")
    return parsed


def validate_no_raw_secrets(value: object, path: str = "pipeline_config") -> None:
    if isinstance(value, list):
        for index, item in enumerate(value):
            validate_no_raw_secrets(item, f"{path}[{index}]")
        return
    if not isinstance(value, dict):
        return
    for key, nested_value in value.items():
        key_text = str(key)
        key_lower = key_text.lower()
        normalized_key = re.sub(r"[^a-z0-9]", "", key_lower)
        allowed_key = key_lower.replace("-", "_")
        if allowed_key not in ALLOWED_SECRET_REFERENCE_KEYS and (
            normalized_key in {re.sub(r"[^a-z0-9]", "", item) for item in SENSITIVE_CONFIG_KEYS}
            or normalized_key.endswith("apikey")
            or normalized_key.endswith("token")
            or "password" in normalized_key
            or "connectionstring" in normalized_key
            or normalized_key.endswith("accountkey")
            or "clientsecret" in normalized_key
        ):
            raise ValueError(
                f"{path}.{key_text} looks like a raw secret. Use a Databricks secret reference "
                "or environment variable reference instead."
            )
        validate_no_raw_secrets(nested_value, f"{path}.{key_text}")


def filtered_dict(value: dict, allowed_keys: set[str], nested_allowed: dict[str, set[str]]) -> dict:
    filtered = {}
    for key in allowed_keys:
        if key not in value:
            continue
        nested_value = value[key]
        if isinstance(nested_value, dict) and key in nested_allowed:
            filtered[key] = filtered_dict(nested_value, nested_allowed[key], {})
        elif isinstance(nested_value, str | int | float | bool) or nested_value is None:
            filtered[key] = nested_value
        elif isinstance(nested_value, list) and all(
            isinstance(item, str | int | float | bool) or item is None for item in nested_value
        ):
            filtered[key] = nested_value
    return filtered


def safe_source_media_for_persistence() -> dict:
    safe = filtered_dict(
        source_media,
        {"auth", "blob_name", "container", "container_name"},
        {"auth": {"mode"}},
    )
    for field_name in ("abfss_uri", "uri", "wasbs_uri"):
        if source_media.get(field_name):
            safe[field_name] = validate_no_uri_credentials(str(source_media[field_name]), field_name)
    if source_media.get("storage_account_url"):
        safe["storage_account_url"] = validate_no_uri_credentials(
            str(source_media["storage_account_url"]),
            "storage_account_url",
        )
    if source_media.get("volume_path"):
        safe["volume_path"] = validate_volume_path(str(source_media["volume_path"]), "volume_path")
    staging = source_media.get("staging")
    if isinstance(staging, dict):
        safe_staging = {}
        if staging.get("volume_path"):
            safe_staging["volume_path"] = validate_volume_path(
                str(staging["volume_path"]),
                "staging.volume_path",
            )
        if isinstance(staging.get("original"), dict):
            safe_staging["original"] = filtered_dict(
                staging["original"],
                {"blob_name", "container_name"},
                {},
            )
            if staging["original"].get("storage_account_url"):
                safe_staging["original"]["storage_account_url"] = validate_no_uri_credentials(
                    str(staging["original"]["storage_account_url"]),
                    "staging.original.storage_account_url",
                )
        if safe_staging:
            safe["staging"] = safe_staging
    return safe


def safe_pipeline_config_for_persistence() -> dict:
    nested_allowed = {
        "faster_whisper": {
            "chunk_overlap_seconds",
            "chunk_target_seconds",
            "beam_size",
            "compute_type",
            "device",
            "language",
            "max_chunks",
            "min_chunk_seconds",
            "model_name",
            "vad_filter",
            "preset",
            "fast_model_name",
            "balanced_model_name",
            "quality_model_name",
        },
        "asr": {
            "beam_size",
            "chunk_overlap_seconds",
            "chunk_target_seconds",
            "compute_type",
            "device",
            "language",
            "max_chunks",
            "min_chunk_seconds",
            "model_name",
            "model_size",
            "vad_filter",
            "preset",
            "fast_model_name",
            "balanced_model_name",
            "quality_model_name",
        },
        "frame_extraction": {
            "dedupe_hashes",
            "format",
            "height",
            "interval_seconds",
            "max_frames",
            "min_spacing_seconds",
            "quality",
            "width",
        },
        "frames": {
            "dedupe_hashes",
            "format",
            "height",
            "interval_seconds",
            "max_frames",
            "min_spacing_seconds",
            "quality",
            "width",
        },
        "inference": {"mode"},
        "models": {"direct", "embedding", "prompt_version", "summary", "vision"},
        "neo4j": {"enabled"},
        "scene_detection": {
            "max_scene_seconds",
            "min_scene_seconds",
            "target_window_seconds",
            "transcript_gap_seconds",
            "window_overlap_seconds",
        },
        "quality": {
            "allowed_video_codecs",
            "max_duration_seconds",
            "max_fps",
            "max_height",
            "max_size_bytes",
            "max_width",
            "min_duration_seconds",
            "min_size_bytes",
            "require_audio",
            "sample_decode_seconds",
        },
        "quality_gates": {
            "allowed_video_codecs",
            "max_duration_seconds",
            "max_fps",
            "max_height",
            "max_size_bytes",
            "max_width",
            "min_duration_seconds",
            "min_size_bytes",
            "require_audio",
            "sample_decode_seconds",
        },
    }
    safe = filtered_dict(
        pipeline_config,
        {
            "asr",
            "custom_prompt",
            "faster_whisper",
            "frame_extraction",
            "frame_interval",
            "frames",
            "graph_version",
            "index_graph",
            "inference",
            "inference_mode",
            "language",
            "max_frames",
            "models",
            "neo4j",
            "processing_version",
            "prompt_version",
            "quality",
            "quality_gates",
            "scene_detection",
            "direct_model",
            "summary_model",
            "vision_model",
        },
        nested_allowed,
    )
    inference = pipeline_config.get("inference")
    if isinstance(inference, dict):
        safe_inference = filtered_dict(inference, {"mode"}, {})
        frame_analysis = inference.get("frame_analysis")
        if isinstance(frame_analysis, dict):
            safe_inference["frame_analysis"] = filtered_dict(
                frame_analysis,
                {
                    "batch_size",
                    "device",
                    "enabled",
                    "max_frames",
                    "max_new_tokens",
                    "model",
                    "model_revision",
                    "provider",
                    "tasks",
                    "torch_dtype",
                },
                {},
            )
        scene_visual_reasoning = inference.get("scene_visual_reasoning")
        if isinstance(scene_visual_reasoning, dict):
            safe_inference["scene_visual_reasoning"] = filtered_dict(
                scene_visual_reasoning,
                {
                    "endpoint",
                    "enabled",
                    "max_frames_per_scene",
                    "max_retries",
                    "max_scenes",
                    "max_tokens",
                    "model_version",
                    "output_schema",
                    "provider",
                    "request_timeout_seconds",
                    "retry_delay_seconds",
                    "temperature",
                },
                {},
            )
        smoke_validation = inference.get("smoke_validation")
        if isinstance(smoke_validation, dict):
            safe_inference["smoke_validation"] = filtered_dict(
                smoke_validation,
                {"enabled", "max_frames", "max_scenes"},
                {},
            )
        safe["inference"] = safe_inference
    return safe

