"""Frontend-compatible Gold processing result construction."""

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

def load_completed_ai_results() -> list[dict]:
    rows = spark.sql(
        f"""
        SELECT
          result_id,
          request_id,
          batch_id,
          source_type,
          source_id,
          model_name,
          prompt_version,
          status,
          normalized_json,
          tokens_prompt,
          tokens_completion,
          updated_at
        FROM {qualified_ai_results_table}
        WHERE media_id = {sql_literal(media_id)}
          AND dispatch_id = {sql_literal(dispatch_id)}
          AND status = 'completed'
        ORDER BY source_type, source_id, updated_at DESC
        """
    ).collect()
    return [row.asDict() for row in rows]


def parse_json_dict(raw_value: str | dict | None) -> dict:
    if isinstance(raw_value, dict):
        return raw_value
    if not raw_value:
        return {}
    parsed = json.loads(raw_value)
    return parsed if isinstance(parsed, dict) else {}


def truncate_text(value: str | None, limit: int) -> str | None:
    if not value:
        return None
    normalized = " ".join(str(value).split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def first_sentence(value: str | None, fallback: str) -> str:
    text = truncate_text(value, 100)
    if not text:
        return fallback
    sentence = text.split(".")[0].strip()
    return sentence or fallback


def string_field(payload: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def list_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        candidates = []
        for key in ("name", "label", "text", "value", "entity"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                candidates.append(item.strip())
        return candidates
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            items.extend(list_strings(item))
        return items
    return []


def unique_strings(values: list[str], limit: int) -> list[str]:
    seen = set()
    unique = []
    for value in values:
        normalized = value.strip()
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            unique.append(normalized)
        if len(unique) >= limit:
            break
    return unique


def extract_objects(payload: dict) -> list[str]:
    objects: list[str] = []
    for key in (
        "detected_objects",
        "objects",
        "visible_objects",
        "people",
        "entities",
        "text",
        "actions",
        "setting",
    ):
        objects.extend(list_strings(payload.get(key)))
    return unique_strings(objects, 25)


def frame_understanding_by_source(ai_results: list[dict]) -> dict[str, dict]:
    by_source: dict[str, dict] = {}
    for result in ai_results:
        if result["source_type"] != "frame" or result["source_id"] in by_source:
            continue
        normalized = parse_json_dict(result["normalized_json"])
        description = string_field(
            normalized,
            ("description", "summary", "analysis", "caption", "content", "text"),
        )
        if not description and normalized:
            description = truncate_text(json.dumps(normalized, sort_keys=True), 500)
        by_source[result["source_id"]] = {
            "result_id": result["result_id"],
            "description": description,
            "detected_objects": extract_objects(normalized),
            "normalized": normalized,
            "tokens_prompt": int(result["tokens_prompt"] or 0),
            "tokens_completion": int(result["tokens_completion"] or 0),
        }
    return by_source


def transcript_semantics(ai_results: list[dict]) -> dict:
    for result in ai_results:
        if result["source_type"] == "transcript":
            return parse_json_dict(result["normalized_json"])
    return {}


def transcript_segments_for_range(segments: list[dict], start_seconds: float, end_seconds: float) -> str | None:
    texts = [
        segment["text"]
        for segment in segments
        if (float(segment["start_ms"]) / 1000) < end_seconds
        and (float(segment["end_ms"]) / 1000) > start_seconds
        and segment.get("text")
    ]
    return truncate_text(" ".join(texts), 500)


def parse_json_list(raw_value: str | list | None) -> list:
    if isinstance(raw_value, list):
        return raw_value
    if not raw_value:
        return []
    parsed = json.loads(raw_value)
    return parsed if isinstance(parsed, list) else []


def nearest_frame(frames: list[dict], target_ms: int) -> dict | None:
    if not frames:
        return None
    return min(frames, key=lambda frame: abs(int(frame["timestamp_ms"]) - target_ms))


def scene_boundaries(frames: list[dict], duration_seconds: float) -> list[tuple[float, float]]:
    if not frames:
        return []
    timestamps = [float(frame["timestamp_ms"]) / 1000 for frame in frames]
    boundaries = []
    for index, timestamp in enumerate(timestamps):
        start = 0.0 if index == 0 else (timestamps[index - 1] + timestamp) / 2
        if index + 1 < len(timestamps):
            end = (timestamp + timestamps[index + 1]) / 2
        else:
            end = max(duration_seconds, timestamp + 1.0)
        boundaries.append((round(start, 3), round(max(end, start), 3)))
    return boundaries


def build_scenes_from_candidates(
    candidates: list[dict],
    frames: list[dict],
    segments: list[dict],
    frame_ai: dict[str, dict],
    scene_visual: dict[str, dict] | None = None,
) -> list[dict]:
    frames_by_id = {frame["frame_asset_id"]: frame for frame in frames}
    scene_visual = scene_visual or {}
    scenes = []
    for candidate in candidates:
        start_seconds = round(float(candidate["start_ms"]) / 1000, 3)
        end_seconds = round(float(candidate["end_ms"]) / 1000, 3)
        frame_ids = [str(item) for item in parse_json_list(candidate.get("frame_asset_ids"))]
        candidate_frames = [frames_by_id[frame_id] for frame_id in frame_ids if frame_id in frames_by_id]
        representative_frame = (
            candidate_frames[0]
            if candidate_frames
            else nearest_frame(frames, int((int(candidate["start_ms"]) + int(candidate["end_ms"])) / 2))
        )
        understandings = [frame_ai.get(frame["frame_asset_id"], {}) for frame in candidate_frames]
        detected_objects = unique_strings(
            [
                detected_object
                for understanding in understandings
                for detected_object in understanding.get("detected_objects", [])
            ],
            20,
        )
        visual_analysis = scene_visual.get(candidate["scene_candidate_id"], {})
        visual_entities = unique_strings(list_strings(visual_analysis.get("entities")), 25)
        visual_actions = unique_strings(list_strings(visual_analysis.get("actions")), 25)
        visual_summary = truncate_text(
            " ".join(
                understanding.get("description", "")
                for understanding in understandings[:3]
                if understanding.get("description")
            ),
            500,
        )
        transcript_summary = transcript_segments_for_range(segments, start_seconds, end_seconds)
        summary = visual_analysis.get("summary") or visual_summary or transcript_summary
        scene_id = int(candidate["scene_index"])
        scenes.append(
            {
                "scene_id": scene_id,
                "scene_candidate_id": candidate["scene_candidate_id"],
                "start_time": start_seconds,
                "end_time": end_seconds,
                "duration": round(max(0.0, end_seconds - start_seconds), 3),
                "title": first_sentence(summary, f"Scene {scene_id + 1}"),
                "summary": summary,
                "detected_objects": unique_strings(detected_objects + visual_entities + visual_actions, 35),
                "actions": visual_actions,
                "entities": visual_analysis.get("entities") or [],
                "relations": visual_analysis.get("relations") or [],
                "scene_visual_analysis_id": visual_analysis.get("analysis_id"),
                "transcript_segment": transcript_summary,
                "frame_asset_id": representative_frame["frame_asset_id"] if representative_frame else None,
                "frame_uri": representative_frame["frame_uri"] if representative_frame else None,
                "confidence": float(candidate["confidence"]),
                "boundary_reasons": parse_json_list(candidate.get("boundary_reasons")),
                "evidence": {
                    "frame_asset_ids": frame_ids,
                    "transcript_segment_ids": parse_json_list(candidate.get("transcript_segment_ids")),
                },
            }
        )
    return scenes


def build_scenes(
    frames: list[dict],
    segments: list[dict],
    frame_ai: dict[str, dict],
    duration: float,
    candidates: list[dict] | None = None,
    scene_visual: dict[str, dict] | None = None,
) -> list[dict]:
    if candidates:
        return build_scenes_from_candidates(candidates, frames, segments, frame_ai, scene_visual)

    scenes = []
    for index, (frame, boundary) in enumerate(zip(frames, scene_boundaries(frames, duration), strict=True)):
        start_seconds, end_seconds = boundary
        understanding = frame_ai.get(frame["frame_asset_id"], {})
        summary = truncate_text(understanding.get("description"), 500)
        scenes.append(
            {
                "scene_id": index,
                "start_time": start_seconds,
                "end_time": end_seconds,
                "duration": round(max(0.0, end_seconds - start_seconds), 3),
                "title": first_sentence(summary, f"Scene {index + 1}"),
                "summary": summary,
                "detected_objects": understanding.get("detected_objects", []),
                "transcript_segment": transcript_segments_for_range(
                    segments,
                    start_seconds,
                    end_seconds,
                ),
                "frame_asset_id": frame["frame_asset_id"],
                "frame_uri": frame["frame_uri"],
            }
        )
    return scenes


def build_chapters_from_scenes(scenes: list[dict], max_scenes_per_chapter: int = 5) -> list[dict]:
    chapters = []
    for start_index in range(0, len(scenes), max_scenes_per_chapter):
        chunk = scenes[start_index : start_index + max_scenes_per_chapter]
        if not chunk:
            continue
        chapter_id = len(chapters)
        summaries = [scene["summary"] for scene in chunk if scene.get("summary")]
        chapters.append(
            {
                "chapter_id": chapter_id,
                "title": chunk[0].get("title") or f"Part {chapter_id + 1}",
                "summary": truncate_text(" ".join(summaries), 500),
                "start_time": chunk[0]["start_time"],
                "end_time": chunk[-1]["end_time"],
                "duration": round(max(0.0, chunk[-1]["end_time"] - chunk[0]["start_time"]), 3),
                "scene_ids": [scene["scene_id"] for scene in chunk],
                "scene_count": len(chunk),
            }
        )
    return chapters


def build_audio_data(asr_run: dict | None, segments: list[dict]) -> dict:
    transcript_text = asr_run.get("transcript_text") if asr_run else " ".join(
        segment["text"] for segment in segments if segment.get("text")
    )
    transcript_segments = [
        {
            "id": int(segment["segment_index"]),
            "start": round(float(segment["start_ms"]) / 1000, 3),
            "end": round(float(segment["end_ms"]) / 1000, 3),
            "text": segment["text"],
        }
        for segment in segments
    ]
    return {
        "transcription": {
            "text": transcript_text or "",
            "segments": transcript_segments,
        },
        "stats": {
            "has_audio": bool(asr_run or segments),
            "total_words": len((transcript_text or "").split()),
            "segment_count": len(transcript_segments),
            "language": asr_run.get("language") if asr_run else None,
            "duration_seconds": asr_run.get("duration_seconds") if asr_run else None,
        },
    }


def build_frames_data(frames: list[dict], frame_ai: dict[str, dict]) -> list[dict]:
    frames_data = []
    for frame in frames:
        understanding = frame_ai.get(frame["frame_asset_id"], {})
        frames_data.append(
            {
                "frame_number": int(frame["frame_index"]),
                "timestamp": round(float(frame["timestamp_ms"]) / 1000, 3),
                "analysis": understanding.get("description"),
                "analysis_structured": understanding.get("normalized"),
                "tokens_used": int(understanding.get("tokens_prompt") or 0)
                + int(understanding.get("tokens_completion") or 0),
                "frame_uri": frame["frame_uri"],
            }
        )
    return frames_data


def build_video_metadata(frames: list[dict], asr_run: dict | None, segments: list[dict]) -> dict:
    quality = load_source_quality()
    source_metadata = quality.get("metadata") or {}
    duration_seconds = float(source_metadata.get("duration_seconds") or 0.0)
    if asr_run:
        duration_seconds = max(duration_seconds, float(asr_run.get("duration_seconds") or 0))
    if frames:
        duration_seconds = max(duration_seconds, float(frames[-1]["timestamp_ms"]) / 1000)
    if segments:
        duration_seconds = max(duration_seconds, float(segments[-1]["end_ms"]) / 1000)
    first_frame = frames[0] if frames else {}
    return {
        "duration": duration_seconds or None,
        "duration_seconds": duration_seconds or None,
        "width": source_metadata.get("width") or first_frame.get("width"),
        "height": source_metadata.get("height") or first_frame.get("height"),
        "fps": source_metadata.get("fps"),
        "video_codec": source_metadata.get("video_codec"),
        "audio_codec": source_metadata.get("audio_codec"),
        "frames_extracted": len(frames),
        "transcript_segments": len(segments),
        "processing_backend": "databricks",
    }


def extract_key_topics(semantics: dict, frame_ai: dict[str, dict]) -> list[str]:
    topics = []
    for key in ("key_topics", "topics", "themes"):
        topics.extend(list_strings(semantics.get(key)))
    for understanding in frame_ai.values():
        topics.extend(understanding.get("detected_objects", [])[:5])
    return unique_strings(topics, 15)


def build_gold_processing_result() -> dict:
    frames = load_frame_assets()
    segments = load_transcript_segments()
    asr_run = load_completed_asr_run()
    ai_results = load_completed_ai_results()
    frame_analysis_rows = load_completed_frame_analysis_rows()
    scene_visual_rows = load_completed_scene_visual_analysis_rows()
    frame_ai = frame_understanding_by_source(ai_results)
    frame_ai.update(frame_analysis_understanding_by_source(frame_analysis_rows))
    scene_visual = scene_visual_analysis_by_candidate(scene_visual_rows)
    semantics = transcript_semantics(ai_results)
    scene_candidates = load_scene_candidates()
    video_metadata = build_video_metadata(frames, asr_run, segments)
    duration = float(video_metadata.get("duration_seconds") or 0.0)
    scenes = build_scenes(frames, segments, frame_ai, duration, scene_candidates, scene_visual)
    chapters = build_chapters_from_scenes(scenes)
    key_topics = extract_key_topics(semantics, frame_ai)
    video_summary = string_field(semantics, ("video_summary", "summary", "abstract"))
    if not video_summary:
        video_summary = truncate_text(
            " ".join(scene["summary"] for scene in scenes[:5] if scene.get("summary")),
            900,
        )
    video_title = string_field(semantics, ("video_title", "title"))
    structure = {
        "scenes": scenes,
        "chapters": chapters,
        "video_summary": video_summary,
        "video_title": video_title,
        "key_topics": key_topics,
        "total_scenes": len(scenes),
    }
    audio_data = build_audio_data(asr_run, segments)
    frames_data = build_frames_data(frames, frame_ai)
    completed_ai_results = len(ai_results)
    completed_frame_analysis = len(frame_analysis_rows)
    completed_scene_visual_analysis = len(scene_visual_rows)
    frames_analyzed = len([frame for frame in frames_data if frame.get("analysis")])
    model_results_completed = (
        completed_ai_results + completed_frame_analysis + completed_scene_visual_analysis
    )
    processing_stats = {
        "frames_extracted": len(frames),
        "frames_analyzed": frames_analyzed,
        "frame_analysis_completed": completed_frame_analysis,
        "scene_visual_analysis_completed": completed_scene_visual_analysis,
        "tokens_total": sum(int(frame.get("tokens_used") or 0) for frame in frames_data),
        "ai_results_completed": completed_ai_results,
        "audio_processed": audio_data["stats"]["has_audio"],
        "processing_mode": f"databricks_lakehouse_{inference_mode_config()['mode']}",
        "processing_version": processing_version,
    }
    processing_result = {
        "backend": "databricks",
        "pipeline": "lakehouse_gold",
        "dispatch_id": dispatch_id,
        "processing_version": processing_version,
        "config_hash": config_hash,
        "video_metadata": video_metadata,
        "frames_data": frames_data,
        "audio_data": audio_data,
        "structure": structure,
        "processing_stats": processing_stats,
        "frames_analyzed": frames_analyzed,
        "status": "completed" if model_results_completed else "completed_with_warnings",
        "delta_tables": {
            "processing_results": GOLD_PROCESSING_RESULTS_TABLE,
            "transcript_segments": TRANSCRIPT_SEGMENTS_TABLE,
            "frame_assets": FRAME_ASSETS_TABLE,
            "frame_analysis": FRAME_ANALYSIS_TABLE,
            "scene_visual_analysis": SCENE_VISUAL_ANALYSIS_TABLE,
            "model_inference_runs": MODEL_INFERENCE_RUNS_TABLE,
            "ai_results": AI_RESULTS_TABLE,
            "graph_upserts": GRAPH_UPSERTS_TABLE,
        },
    }
    now = datetime.now(UTC)
    result_row = {
        "result_id": f"{media_id}:{dispatch_id}:gold:{processing_version}:{config_hash[:12]}",
        "media_id": media_id,
        "dispatch_id": dispatch_id,
        "schema_version": schema_version,
        "processing_version": processing_version,
        "config_hash": config_hash,
        "status": processing_result["status"],
        "video_title": video_title,
        "video_summary": video_summary,
        "key_topics": json_dumps({"items": key_topics}),
        "structure_json": json_dumps(structure),
        "audio_data_json": json_dumps(audio_data),
        "frames_data_json": json.dumps(frames_data, separators=(",", ":"), sort_keys=True),
        "video_metadata_json": json_dumps(video_metadata),
        "processing_result_json": json_dumps(processing_result),
        "metrics_json": json_dumps(processing_stats),
        "created_at": now,
        "updated_at": now,
    }
    merge_row(
        qualified_gold_processing_results_table,
        result_row,
        GOLD_PROCESSING_RESULTS_SCHEMA,
        ["result_id"],
    )
    return result_row


def load_latest_gold_processing_result() -> dict | None:
    rows = spark.sql(
        f"""
        SELECT
          result_id,
          status,
          video_title,
          video_summary,
          structure_json,
          video_metadata_json,
          processing_result_json,
          updated_at
        FROM {qualified_gold_processing_results_table}
        WHERE media_id = {sql_literal(media_id)}
          AND dispatch_id = {sql_literal(dispatch_id)}
        ORDER BY updated_at DESC
        LIMIT 1
        """
    ).collect()
    return rows[0].asDict() if rows else None

