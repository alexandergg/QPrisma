"""Scene detection, Databricks scene reasoning, and scene analysis persistence."""

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

def load_completed_asr_run() -> dict | None:
    rows = spark.sql(
        f"""
        SELECT
          asr_run_id,
          audio_asset_id,
          model_name,
          language,
          duration_seconds,
          segment_count,
          transcript_text
        FROM {qualified_asr_runs_table}
        WHERE media_id = {sql_literal(media_id)}
          AND dispatch_id = {sql_literal(dispatch_id)}
          AND status = 'completed'
        ORDER BY completed_at DESC
        LIMIT 1
        """
    ).collect()
    return rows[0].asDict() if rows else None


def load_transcript_segments() -> list[dict]:
    rows = spark.sql(
        f"""
        SELECT
          segment_id,
          asr_run_id,
          audio_asset_id,
          chunk_id,
          segment_index,
          start_ms,
          end_ms,
          text,
          language
        FROM {qualified_transcript_segments_table}
        WHERE media_id = {sql_literal(media_id)}
          AND dispatch_id = {sql_literal(dispatch_id)}
        ORDER BY segment_index
        """
    ).collect()
    return [row.asDict() for row in rows]


def scene_detection_config() -> dict:
    cfg = pipeline_config.get("scene_detection") or {}
    if not isinstance(cfg, dict):
        raise ValueError("pipeline_config.scene_detection must be an object when provided")
    target_window_seconds = bounded_float(
        "target_window_seconds",
        cfg.get("target_window_seconds"),
        default=60.0,
        minimum=10.0,
        maximum=300.0,
    )
    window_overlap_seconds = bounded_float(
        "window_overlap_seconds",
        cfg.get("window_overlap_seconds"),
        default=5.0,
        minimum=0.0,
        maximum=60.0,
    )
    if window_overlap_seconds >= target_window_seconds:
        raise ValueError("scene_detection.window_overlap_seconds must be smaller than target_window_seconds")
    return {
        "target_window_seconds": target_window_seconds,
        "window_overlap_seconds": window_overlap_seconds,
        "transcript_gap_seconds": bounded_float(
            "transcript_gap_seconds",
            cfg.get("transcript_gap_seconds"),
            default=2.5,
            minimum=0.5,
            maximum=30.0,
        ),
        "min_scene_seconds": bounded_float(
            "min_scene_seconds",
            cfg.get("min_scene_seconds"),
            default=8.0,
            minimum=1.0,
            maximum=120.0,
        ),
        "max_scene_seconds": bounded_float(
            "max_scene_seconds",
            cfg.get("max_scene_seconds"),
            default=120.0,
            minimum=15.0,
            maximum=600.0,
        ),
    }


def media_duration_seconds(frames: list[dict], segments: list[dict]) -> float:
    quality = load_source_quality()
    metadata = quality.get("metadata") or {}
    duration = float(metadata.get("duration_seconds") or 0.0)
    if frames:
        duration = max(duration, float(frames[-1]["timestamp_ms"]) / 1000)
    if segments:
        duration = max(duration, float(segments[-1]["end_ms"]) / 1000)
    return duration


def frame_ids_for_range(frames: list[dict], start_ms: int, end_ms: int) -> list[str]:
    return [
        frame["frame_asset_id"]
        for frame in frames
        if int(frame["timestamp_ms"]) >= start_ms and int(frame["timestamp_ms"]) < end_ms
    ]


def segment_ids_for_range(segments: list[dict], start_ms: int, end_ms: int) -> list[str]:
    return [
        segment["segment_id"]
        for segment in segments
        if int(segment["start_ms"]) < end_ms and int(segment["end_ms"]) > start_ms
    ]


def build_temporal_window_rows(frames: list[dict], segments: list[dict], duration: float) -> list[dict]:
    config = scene_detection_config()
    if duration <= 0:
        return []
    rows = []
    start = 0.0
    target = float(config["target_window_seconds"])
    overlap = float(config["window_overlap_seconds"])
    now = datetime.now(UTC)
    while start < duration:
        end = min(duration, start + target)
        start_ms = int(start * 1000)
        end_ms = int(end * 1000)
        rows.append(
            {
                "window_id": f"{media_id}:{dispatch_id}:window:{config_hash[:12]}:{len(rows):06d}",
                "media_id": media_id,
                "dispatch_id": dispatch_id,
                "window_index": len(rows),
                "start_ms": start_ms,
                "end_ms": end_ms,
                "duration_seconds": round(max(0.0, end - start), 3),
                "strategy": "fixed_window_with_overlap",
                "frame_asset_ids": json.dumps(frame_ids_for_range(frames, start_ms, end_ms)),
                "transcript_segment_ids": json.dumps(segment_ids_for_range(segments, start_ms, end_ms)),
                "created_at": now,
            }
        )
        if end >= duration:
            break
        start = max(0.0, end - overlap)
    return rows


def scene_boundary_points(frames: list[dict], segments: list[dict], duration: float, config: dict) -> dict[int, set[str]]:
    boundaries: dict[int, set[str]] = {0: {"start"}, int(duration * 1000): {"end"}}
    gap_ms = int(float(config["transcript_gap_seconds"]) * 1000)
    max_scene_ms = int(float(config["max_scene_seconds"]) * 1000)

    previous_end = None
    for segment in segments:
        start_ms = int(segment["start_ms"])
        if previous_end is not None and start_ms - previous_end >= gap_ms:
            boundaries.setdefault(start_ms, set()).add("transcript_gap")
        previous_end = int(segment["end_ms"])

    for frame in frames:
        timestamp_ms = int(frame["timestamp_ms"])
        if 0 < timestamp_ms < int(duration * 1000):
            boundaries.setdefault(timestamp_ms, set()).add("frame_anchor")

    next_forced = max_scene_ms
    while next_forced < int(duration * 1000):
        boundaries.setdefault(next_forced, set()).add("max_scene_duration")
        next_forced += max_scene_ms

    return boundaries


def build_scene_candidate_rows(frames: list[dict], segments: list[dict], duration: float) -> list[dict]:
    config = scene_detection_config()
    if duration <= 0:
        return []
    raw_boundaries = scene_boundary_points(frames, segments, duration, config)
    min_scene_ms = int(float(config["min_scene_seconds"]) * 1000)
    points = sorted(raw_boundaries)
    rows = []
    now = datetime.now(UTC)
    current_start = points[0]
    current_reasons = set(raw_boundaries[current_start])
    for point in points[1:]:
        if point - current_start < min_scene_ms and point != points[-1]:
            current_reasons.update(raw_boundaries[point])
            continue
        start_ms = current_start
        end_ms = max(point, start_ms)
        frame_ids = frame_ids_for_range(frames, start_ms, end_ms)
        segment_ids = segment_ids_for_range(segments, start_ms, end_ms)
        reasons = sorted(current_reasons.union(raw_boundaries[point]))
        confidence = min(
            0.95,
            0.45
            + (0.2 if segment_ids else 0.0)
            + (0.15 if frame_ids else 0.0)
            + (0.1 if "transcript_gap" in reasons else 0.0),
        )
        rows.append(
            {
                "scene_candidate_id": (
                    f"{media_id}:{dispatch_id}:scene_candidate:{config_hash[:12]}:{len(rows):06d}"
                ),
                "media_id": media_id,
                "dispatch_id": dispatch_id,
                "scene_index": len(rows),
                "start_ms": start_ms,
                "end_ms": end_ms,
                "duration_seconds": round((end_ms - start_ms) / 1000, 3),
                "strategy": "hybrid_ffmpeg_asr_frame_boundaries",
                "boundary_reasons": json.dumps(reasons),
                "confidence": round(confidence, 3),
                "frame_asset_ids": json.dumps(frame_ids),
                "transcript_segment_ids": json.dumps(segment_ids),
                "status": "candidate",
                "created_at": now,
            }
        )
        current_start = point
        current_reasons = set(raw_boundaries[point])
    return rows


def register_temporal_windows(windows: list[dict]) -> None:
    for window in windows:
        merge_row(qualified_temporal_windows_table, window, TEMPORAL_WINDOWS_SCHEMA, ["window_id"])


def register_scene_candidates(candidates: list[dict]) -> None:
    for candidate in candidates:
        merge_row(
            qualified_scene_candidates_table,
            candidate,
            SCENE_CANDIDATES_SCHEMA,
            ["scene_candidate_id"],
        )


def clear_scene_detection_rows() -> None:
    spark.sql(
        f"""
        DELETE FROM {qualified_temporal_windows_table}
        WHERE media_id = {sql_literal(media_id)}
          AND dispatch_id = {sql_literal(dispatch_id)}
        """
    )
    spark.sql(
        f"""
        DELETE FROM {qualified_scene_candidates_table}
        WHERE media_id = {sql_literal(media_id)}
          AND dispatch_id = {sql_literal(dispatch_id)}
        """
    )


def detect_scenes_and_windows() -> dict:
    frames = load_frame_assets()
    segments = load_transcript_segments()
    duration = media_duration_seconds(frames, segments)
    windows = build_temporal_window_rows(frames, segments, duration)
    candidates = build_scene_candidate_rows(frames, segments, duration)
    clear_scene_detection_rows()
    register_temporal_windows(windows)
    register_scene_candidates(candidates)
    return {
        "window_count": len(windows),
        "scene_candidate_count": len(candidates),
        "duration_seconds": duration,
        "temporal_windows_table": TEMPORAL_WINDOWS_TABLE,
        "scene_candidates_table": SCENE_CANDIDATES_TABLE,
    }


def load_scene_candidates() -> list[dict]:
    rows = spark.sql(
        f"""
        SELECT
          scene_candidate_id,
          scene_index,
          start_ms,
          end_ms,
          duration_seconds,
          strategy,
          boundary_reasons,
          confidence,
          frame_asset_ids,
          transcript_segment_ids
        FROM {qualified_scene_candidates_table}
        WHERE media_id = {sql_literal(media_id)}
          AND dispatch_id = {sql_literal(dispatch_id)}
          AND status = 'candidate'
        ORDER BY scene_index
        """
    ).collect()
    return [row.asDict() for row in rows]


def load_completed_frame_analysis_rows() -> list[dict]:
    rows = spark.sql(
        f"""
        SELECT
          analysis_id,
          frame_asset_id,
          frame_index,
          timestamp_ms,
          model_name,
          model_version,
          provider,
          task,
          caption,
          ocr_text,
          objects_json,
          regions_json,
          grounding_json,
          raw_output_json,
          latency_ms,
          status,
          updated_at
        FROM {qualified_frame_analysis_table}
        WHERE media_id = {sql_literal(media_id)}
          AND dispatch_id = {sql_literal(dispatch_id)}
          AND status = 'completed'
        ORDER BY frame_index, task, updated_at DESC
        """
    ).collect()
    return [row.asDict() for row in rows]


def labels_from_structured_payload(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        labels = payload.get("labels")
        if isinstance(labels, list):
            return unique_strings([str(label) for label in labels], 50)
        values = []
        for key in ("objects", "entities", "items", "detections"):
            values.extend(list_strings(payload.get(key)))
        return unique_strings(values, 50)
    if isinstance(payload, list):
        return unique_strings(list_strings(payload), 50)
    return []


def parse_json_value(raw_value: str | dict | list | None) -> Any:
    if isinstance(raw_value, dict | list):
        return raw_value
    if not raw_value:
        return None
    return json.loads(raw_value)


def frame_analysis_understanding_by_source(rows: list[dict]) -> dict[str, dict]:
    by_frame: dict[str, dict] = {}
    for row in rows:
        frame_id = row["frame_asset_id"]
        understanding = by_frame.setdefault(
            frame_id,
            {
                "result_id": row["analysis_id"],
                "description_parts": [],
                "ocr_texts": [],
                "detected_objects": [],
                "normalized": {"provider": row["provider"], "model_name": row["model_name"], "tasks": {}},
                "tokens_prompt": 0,
                "tokens_completion": 0,
            },
        )
        task = row["task"]
        task_payload = parse_json_value(row.get("raw_output_json")) or {}
        understanding["normalized"]["tasks"][task] = task_payload
        if row.get("caption"):
            understanding["description_parts"].append(row["caption"])
        if row.get("ocr_text"):
            understanding["ocr_texts"].append(row["ocr_text"])
        objects = parse_json_value(row.get("objects_json"))
        regions = parse_json_value(row.get("regions_json"))
        understanding["detected_objects"].extend(labels_from_structured_payload(objects))
        understanding["detected_objects"].extend(labels_from_structured_payload(regions))

    result = {}
    for frame_id, understanding in by_frame.items():
        description_parts = understanding.pop("description_parts")
        ocr_texts = understanding.pop("ocr_texts")
        description = truncate_text(" ".join(description_parts), 700)
        if ocr_texts:
            understanding["normalized"]["ocr_text"] = " ".join(ocr_texts)
        result[frame_id] = {
            **understanding,
            "description": description,
            "detected_objects": unique_strings(understanding["detected_objects"], 50),
        }
    return result


def scene_visual_reasoning_config() -> dict:
    cfg = inference_section("scene_visual_reasoning")
    enabled_default = inference_mode_config()["mode"] == "local_databricks"
    endpoint = str(cfg.get("endpoint") or "databricks-gemma-3-12b").strip()
    if not SERVING_ENDPOINT_RE.fullmatch(endpoint):
        raise ValueError("Databricks Foundation Model endpoint must be a simple serving endpoint name")
    return {
        "enabled": config_bool(cfg.get("enabled"), default=enabled_default),
        "provider": str(cfg.get("provider") or "databricks_foundation_model"),
        "endpoint": endpoint,
        "model_version": cfg.get("model_version"),
        "output_schema": str(cfg.get("output_schema") or "qprisma_scene_visual_v1"),
        "max_scenes": bounded_int("max_scenes", cfg.get("max_scenes"), default=1, minimum=1, maximum=500),
        "max_frames_per_scene": bounded_int(
            "max_frames_per_scene",
            cfg.get("max_frames_per_scene"),
            default=2,
            minimum=1,
            maximum=8,
        ),
        "max_tokens": bounded_int("max_tokens", cfg.get("max_tokens"), default=800, minimum=128, maximum=4096),
        "temperature": bounded_float(
            "temperature",
            cfg.get("temperature"),
            default=0.1,
            minimum=0.0,
            maximum=2.0,
        ),
        "request_timeout_seconds": bounded_float(
            "request_timeout_seconds",
            cfg.get("request_timeout_seconds"),
            default=120.0,
            minimum=5.0,
            maximum=600.0,
        ),
        "max_retries": bounded_int("max_retries", cfg.get("max_retries"), default=2, minimum=0, maximum=8),
        "retry_delay_seconds": bounded_float(
            "retry_delay_seconds",
            cfg.get("retry_delay_seconds"),
            default=2.0,
            minimum=0.1,
            maximum=60.0,
        ),
    }


def normalized_https_host(value: str) -> str:
    parsed = urlparse(str(value).rstrip("/"))
    if parsed.scheme != "https" or not parsed.netloc or parsed.path not in {"", "/"}:
        raise ValueError("Databricks workspace host must be an HTTPS origin")
    return f"{parsed.scheme}://{parsed.netloc}"


def databricks_api_host(config: dict) -> str:
    context = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
    api_url = context.apiUrl().get()
    context_host = normalized_https_host(api_url) if api_url else ""
    env_host_value = os.environ.get("DATABRICKS_HOST")
    if env_host_value:
        env_host = normalized_https_host(env_host_value)
        if context_host and urlparse(env_host).netloc != urlparse(context_host).netloc:
            raise ValueError("DATABRICKS_HOST does not match the current Databricks workspace host")
        return env_host
    if not api_url:
        raise ValueError("Databricks workspace host is missing. Set deployment-owned DATABRICKS_HOST.")
    return context_host


def databricks_api_token(config: dict) -> str:
    token = os.environ.get("DATABRICKS_TOKEN")
    if token:
        return token
    context = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
    api_token = context.apiToken().get()
    if not api_token:
        raise ValueError(
            "Databricks API token is missing. Set deployment-owned DATABRICKS_TOKEN "
            "or run in a notebook context that exposes apiToken."
        )
    return str(api_token)


def databricks_serving_endpoint_invocation(config: dict, payload: dict) -> dict:
    host = databricks_api_host(config)
    token = databricks_api_token(config)
    url = f"{host}/serving-endpoints/{config['endpoint']}/invocations"
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    max_retries = int(config["max_retries"])
    retry_delay = float(config["retry_delay_seconds"])
    for attempt in range(max_retries + 1):
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=float(config["request_timeout_seconds"])) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            retryable = exc.code in {408, 429, 500, 502, 503, 504}
            error_body = exc.read().decode("utf-8", errors="replace")
            if not retryable or attempt >= max_retries:
                raise RuntimeError(
                    f"Databricks Foundation Model endpoint {config['endpoint']} failed "
                    f"with HTTP {exc.code}: {error_body}"
                ) from exc
            time.sleep(retry_delay * (2**attempt))
        except urllib.error.URLError as exc:
            if attempt >= max_retries:
                raise RuntimeError(
                    f"Databricks Foundation Model endpoint {config['endpoint']} is unreachable: {exc}"
                ) from exc
            time.sleep(retry_delay * (2**attempt))
    raise RuntimeError(f"Databricks Foundation Model endpoint {config['endpoint']} did not return a response")


def strip_json_markdown(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def parse_model_json_content(content: str) -> dict:
    parsed = json.loads(strip_json_markdown(content))
    if not isinstance(parsed, dict):
        raise ValueError("Model response must be a JSON object")
    return parsed


def extract_chat_content(response: dict) -> str:
    choices = response.get("choices") or []
    if not choices:
        raise ValueError("Databricks Foundation Model response has no choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                text_parts.append(item["text"])
        if text_parts:
            return "\n".join(text_parts)
    raise ValueError("Databricks Foundation Model response content is empty or unsupported")


def scene_prompt(candidate: dict, frames: list[dict], segments: list[dict], frame_ai: dict[str, dict], config: dict) -> str:
    start_seconds = round(float(candidate["start_ms"]) / 1000, 3)
    end_seconds = round(float(candidate["end_ms"]) / 1000, 3)
    frame_ids = [str(item) for item in parse_json_list(candidate.get("frame_asset_ids"))]
    frame_summaries = []
    for frame_id in frame_ids:
        understanding = frame_ai.get(frame_id, {})
        if understanding.get("description") or understanding.get("detected_objects"):
            frame_summaries.append(
                {
                    "frame_id": frame_id,
                    "description": understanding.get("description"),
                    "objects": understanding.get("detected_objects", [])[:20],
                    "ocr_text": (understanding.get("normalized") or {}).get("ocr_text"),
                }
            )
    transcript = transcript_segments_for_range(segments, start_seconds, end_seconds)
    prompt_payload = {
        "output_schema": config["output_schema"],
        "media_id": media_id,
        "scene_candidate_id": candidate["scene_candidate_id"],
        "time_range_seconds": {"start": start_seconds, "end": end_seconds},
        "transcript": transcript,
        "florence_frame_signals": frame_summaries,
    }
    return json_mode_prompt(
        "Analyze this video scene/window for QPrisma. Return JSON with keys: "
        "summary, actions, entities, relations, confidence, evidence. "
        "Use the Florence frame signals and transcript as grounded evidence.\n\n"
        f"Input:\n{json.dumps(prompt_payload, separators=(',', ':'), sort_keys=True)}"
    )


def selected_scene_frames(candidate: dict, frames_by_id: dict[str, dict], max_frames: int) -> list[dict]:
    frame_ids = [str(item) for item in parse_json_list(candidate.get("frame_asset_ids"))]
    selected = [frames_by_id[frame_id] for frame_id in frame_ids if frame_id in frames_by_id]
    if len(selected) <= max_frames:
        return selected
    if max_frames == 1:
        return [selected[len(selected) // 2]]
    step = (len(selected) - 1) / (max_frames - 1)
    indexes = sorted({round(index * step) for index in range(max_frames)})
    return [selected[index] for index in indexes]


def scene_reasoning_payload(
    candidate: dict,
    frames: list[dict],
    segments: list[dict],
    frame_ai: dict[str, dict],
    config: dict,
) -> tuple[dict, list[str]]:
    frames_by_id = {frame["frame_asset_id"]: frame for frame in frames}
    selected_frames = selected_scene_frames(candidate, frames_by_id, int(config["max_frames_per_scene"]))
    content: list[dict] = [{"type": "text", "text": scene_prompt(candidate, frames, segments, frame_ai, config)}]
    for frame in selected_frames:
        content.append({"type": "image_url", "image_url": {"url": read_image_as_data_url(frame["frame_uri"])}})
    return (
        {
            "messages": [{"role": "user", "content": content}],
            "temperature": float(config["temperature"]),
            "max_tokens": int(config["max_tokens"]),
        },
        [frame["frame_asset_id"] for frame in selected_frames],
    )


def scene_visual_analysis_row(
    candidate: dict,
    config: dict,
    *,
    status: str,
    evidence_frame_ids: list[str],
    request_payload: dict,
    response: dict | None = None,
    normalized: dict | None = None,
    latency_ms: float | None = None,
    error: dict | None = None,
) -> dict:
    normalized = normalized or {}
    usage = (response or {}).get("usage") or {}
    now = datetime.now(UTC)
    analysis_hash = stable_hash(
        {
            "scene_candidate_id": candidate["scene_candidate_id"],
            "endpoint": config["endpoint"],
            "model_version": config.get("model_version"),
            "config_hash": config_hash,
        }
    )
    return {
        "analysis_id": f"{media_id}:scene_visual:{analysis_hash[:16]}",
        "media_id": media_id,
        "dispatch_id": dispatch_id,
        "scene_candidate_id": candidate["scene_candidate_id"],
        "window_id": None,
        "scene_index": int(candidate["scene_index"]),
        "start_ms": int(candidate["start_ms"]),
        "end_ms": int(candidate["end_ms"]),
        "model_name": config["endpoint"],
        "model_version": config.get("model_version"),
        "provider": config["provider"],
        "summary": string_field(normalized, ("summary", "description", "visual_summary")),
        "actions_json": json.dumps(normalized.get("actions") or [], separators=(",", ":"), sort_keys=True),
        "entities_json": json.dumps(normalized.get("entities") or [], separators=(",", ":"), sort_keys=True),
        "relations_json": json.dumps(normalized.get("relations") or [], separators=(",", ":"), sort_keys=True),
        "evidence_frame_ids": json.dumps(evidence_frame_ids, separators=(",", ":"), sort_keys=True),
        "request_payload_json": json.dumps(request_payload, separators=(",", ":"), sort_keys=True),
        "response_json": json.dumps(response or {}, separators=(",", ":"), sort_keys=True),
        "latency_ms": latency_ms,
        "tokens_prompt": usage.get("prompt_tokens"),
        "tokens_completion": usage.get("completion_tokens"),
        "status": status,
        "error": json_dumps(error or {}),
        "created_at": now,
        "updated_at": now,
    }


def register_scene_visual_analysis_rows(rows: list[dict]) -> None:
    for row in rows:
        merge_row(
            qualified_scene_visual_analysis_table,
            row,
            SCENE_VISUAL_ANALYSIS_SCHEMA,
            ["analysis_id"],
        )


def load_completed_scene_visual_analysis_rows() -> list[dict]:
    rows = spark.sql(
        f"""
        SELECT
          analysis_id,
          scene_candidate_id,
          scene_index,
          start_ms,
          end_ms,
          model_name,
          model_version,
          provider,
          summary,
          actions_json,
          entities_json,
          relations_json,
          evidence_frame_ids,
          response_json,
          latency_ms,
          tokens_prompt,
          tokens_completion,
          status,
          updated_at
        FROM {qualified_scene_visual_analysis_table}
        WHERE media_id = {sql_literal(media_id)}
          AND dispatch_id = {sql_literal(dispatch_id)}
          AND status = 'completed'
        ORDER BY scene_index, updated_at DESC
        """
    ).collect()
    return [row.asDict() for row in rows]


def scene_visual_analysis_by_candidate(rows: list[dict]) -> dict[str, dict]:
    by_candidate: dict[str, dict] = {}
    for row in rows:
        candidate_id = row["scene_candidate_id"]
        if candidate_id in by_candidate:
            continue
        by_candidate[candidate_id] = {
            **row,
            "actions": parse_json_list(row.get("actions_json")),
            "entities": parse_json_list(row.get("entities_json")),
            "relations": parse_json_list(row.get("relations_json")),
            "evidence_frame_ids": parse_json_list(row.get("evidence_frame_ids")),
            "response": parse_json_dict(row.get("response_json")),
        }
    return by_candidate


def run_databricks_scene_reasoning() -> dict:
    stage_started_at = datetime.now(UTC)
    stage_started = time.perf_counter()
    config = scene_visual_reasoning_config()
    if not config["enabled"]:
        metrics = {
            "skipped": True,
            "skipped_reason": "scene_visual_reasoning_disabled",
            "scene_visual_analysis_table": SCENE_VISUAL_ANALYSIS_TABLE,
            "model_inference_runs_table": MODEL_INFERENCE_RUNS_TABLE,
        }
        write_model_inference_run(
            stage_name="run_databricks_scene_reasoning",
            provider=config["provider"],
            model_name=config["endpoint"],
            model_version=config.get("model_version"),
            input_count=0,
            success_count=0,
            failed_count=0,
            duration_seconds=time.perf_counter() - stage_started,
            metrics=metrics,
            status="skipped",
            started_at=stage_started_at,
        )
        return metrics

    frames = load_frame_assets()
    segments = load_transcript_segments()
    frame_ai = frame_analysis_understanding_by_source(load_completed_frame_analysis_rows())
    candidates = load_scene_candidates()[: int(config["max_scenes"])]
    rows: list[dict] = []
    success_count = 0
    failed_count = 0
    for candidate in candidates:
        request_payload, evidence_frame_ids = scene_reasoning_payload(
            candidate,
            frames,
            segments,
            frame_ai,
            config,
        )
        request_started = time.perf_counter()
        try:
            response = databricks_serving_endpoint_invocation(config, request_payload)
            content = extract_chat_content(response)
            normalized = parse_model_json_content(content)
            latency_ms = (time.perf_counter() - request_started) * 1000
            rows.append(
                scene_visual_analysis_row(
                    candidate,
                    config,
                    status="completed",
                    evidence_frame_ids=evidence_frame_ids,
                    request_payload=request_payload,
                    response=response,
                    normalized=normalized,
                    latency_ms=rounded_metric(latency_ms),
                )
            )
            success_count += 1
        except (RuntimeError, ValueError, json.JSONDecodeError, OSError) as exc:
            latency_ms = (time.perf_counter() - request_started) * 1000
            rows.append(
                scene_visual_analysis_row(
                    candidate,
                    config,
                    status="failed",
                    evidence_frame_ids=evidence_frame_ids,
                    request_payload=request_payload,
                    latency_ms=rounded_metric(latency_ms),
                    error={"type": type(exc).__name__, "message": str(exc)},
                )
            )
            failed_count += 1
    register_scene_visual_analysis_rows(rows)
    elapsed = time.perf_counter() - stage_started
    metrics = {
        "scene_candidate_count": len(candidates),
        "success_count": success_count,
        "failed_count": failed_count,
        "elapsed_seconds": rounded_metric(elapsed),
        "scenes_per_second": rate_metric(success_count, elapsed),
        "model_name": config["endpoint"],
        "model_version": config.get("model_version"),
        "provider": config["provider"],
        "max_frames_per_scene": config["max_frames_per_scene"],
        "output_schema": config["output_schema"],
        "scene_visual_analysis_table": SCENE_VISUAL_ANALYSIS_TABLE,
        "model_inference_runs_table": MODEL_INFERENCE_RUNS_TABLE,
        "smoke_ready": success_count > 0,
    }
    write_model_inference_run(
        stage_name="run_databricks_scene_reasoning",
        provider=config["provider"],
        model_name=config["endpoint"],
        model_version=config.get("model_version"),
        input_count=len(candidates),
        success_count=success_count,
        failed_count=failed_count,
        duration_seconds=elapsed,
        metrics=metrics,
        status="completed" if failed_count == 0 else "completed_with_failures",
        started_at=stage_started_at,
    )
    if candidates and success_count == 0:
        raise RuntimeError("Databricks Gemma 3 scene reasoning produced no successful outputs")
    return metrics

