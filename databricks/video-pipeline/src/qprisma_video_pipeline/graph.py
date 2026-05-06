"""Graph upsert row construction and Neo4j projection helpers."""

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

def graph_upsert_row(
    *,
    operation_type: str,
    label_or_type: str,
    natural_key: str,
    source_table: str,
    source_id: str,
    properties: dict,
) -> dict:
    now = datetime.now(UTC)
    graph_version = str(pipeline_config.get("graph_version") or schema_version)
    upsert_fingerprint = stable_hash(
        {
            "graph_version": graph_version,
            "operation_type": operation_type,
            "label_or_type": label_or_type,
            "natural_key": natural_key,
            "source_table": source_table,
            "source_id": source_id,
        }
    )
    return {
        "upsert_id": f"{media_id}:graph:{upsert_fingerprint[:16]}",
        "media_id": media_id,
        "dispatch_id": dispatch_id,
        "graph_version": graph_version,
        "operation_type": operation_type,
        "label_or_type": label_or_type,
        "natural_key": natural_key,
        "source_table": source_table,
        "source_id": source_id,
        "properties_json": json_dumps(properties),
        "status": "pending",
        "created_at": now,
        "updated_at": now,
        "error": json_dumps({}),
    }


def normalized_entity_name(name: str) -> str:
    normalized = re.sub(r"\s+", " ", name.strip().lower())
    normalized = re.sub(r"[^a-z0-9áéíóúüñ _.-]+", "", normalized)
    return normalized.strip() or "unknown"


def config_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"Expected boolean-compatible config value, got {value!r}")


def graph_indexing_enabled() -> bool:
    return config_bool(pipeline_config.get("index_graph"), default=True)


def neo4j_projector_decision() -> dict:
    cfg = pipeline_config.get("neo4j") or {}
    if cfg and not isinstance(cfg, dict):
        raise ValueError("pipeline_config.neo4j must be an object when provided")
    if isinstance(cfg, dict) and cfg.get("enabled") is not None:
        enabled = config_bool(cfg.get("enabled"), default=False)
        return {
            "enabled": enabled,
            "required": enabled,
            "skipped_reason": None if enabled else "neo4j_disabled_by_config",
        }
    if not graph_indexing_enabled():
        return {
            "enabled": False,
            "required": False,
            "skipped_reason": "graph_indexing_disabled",
        }
    if not str(os.environ.get("NEO4J_URI") or "").strip():
        return {
            "enabled": False,
            "required": False,
            "skipped_reason": "neo4j_uri_missing",
        }
    if not neo4j_password_configured():
        return {
            "enabled": False,
            "required": False,
            "skipped_reason": "neo4j_password_missing",
        }
    return {"enabled": True, "required": False, "skipped_reason": None}


def neo4j_projector_enabled() -> bool:
    return bool(neo4j_projector_decision()["enabled"])


def neo4j_password_secret_reference() -> tuple[str, str]:
    cfg = pipeline_config.get("neo4j") or {}
    if cfg and not isinstance(cfg, dict):
        raise ValueError("pipeline_config.neo4j must be an object when provided")
    scope = str(os.environ.get("NEO4J_PASSWORD_SECRET_SCOPE") or "").strip()
    key = str(os.environ.get("NEO4J_PASSWORD_SECRET_KEY") or "").strip()
    return scope, key


def neo4j_password_configured() -> bool:
    if str(os.environ.get("NEO4J_PASSWORD") or "").strip():
        return True
    scope, key = neo4j_password_secret_reference()
    return bool(scope and key)


def resolve_neo4j_password() -> str:
    password = os.environ.get("NEO4J_PASSWORD", "")
    if password:
        return password
    scope, key = neo4j_password_secret_reference()
    if not scope or not key:
        return ""
    try:
        return dbutils.secrets.get(scope, key)
    except Exception as exc:
        raise RuntimeError(
            f"Neo4j password secret {scope}/{key} could not be resolved. "
            "Fix NEO4J_PASSWORD_SECRET_SCOPE/NEO4J_PASSWORD_SECRET_KEY or disable Neo4j projection."
        ) from exc


def build_graph_upsert_rows() -> list[dict]:
    if not graph_indexing_enabled():
        return []

    frames = load_frame_assets()
    transcript_segments = load_transcript_segments()
    asr_run = load_completed_asr_run()
    graph_version = str(pipeline_config.get("graph_version") or schema_version)
    source_quality = load_source_quality()
    source_metadata = source_quality.get("metadata") or {}
    gold_result = load_latest_gold_processing_result()
    gold_processing_result = (
        parse_json_dict(gold_result["processing_result_json"]) if gold_result else {}
    )
    gold_structure = parse_json_dict(gold_processing_result.get("structure"))
    frame_ai = frame_analysis_understanding_by_source(load_completed_frame_analysis_rows())
    entity_nodes_added: set[str] = set()
    rows: list[dict] = [
        graph_upsert_row(
            operation_type="node",
            label_or_type="Video",
            natural_key=media_id,
            source_table=MEDIA_MANIFEST_TABLE,
            source_id=media_id,
            properties={
                "id": media_id,
                "video_id": media_id,
                "media_id": media_id,
                "dispatch_id": dispatch_id,
                "blob_name": blob_name,
                "user_id": user_id,
                "processing_version": processing_version,
                "config_hash": config_hash,
                "graph_version": graph_version,
                "title": gold_structure.get("video_title"),
                "description": None,
                "summary": gold_structure.get("video_summary"),
                "topics": gold_structure.get("key_topics") or [],
                "duration_seconds": source_metadata.get("duration_seconds"),
                "fps": source_metadata.get("fps"),
                "resolution": [source_metadata.get("width"), source_metadata.get("height")],
                "file_size_bytes": source_metadata.get("size_bytes"),
                "format": source_metadata.get("format"),
                "total_frames": source_metadata.get("frame_count"),
                "extracted_frames": len(frames),
                "blob_url": None,
                "thumbnail_url": frames[0]["frame_uri"] if frames else None,
            },
        )
    ]

    if gold_result:
        for scene in gold_structure.get("scenes") or []:
            scene_id = int(scene.get("scene_id") or 0)
            scene_key = f"{media_id}:scene:{scene_id:06d}"
            rows.append(
                graph_upsert_row(
                    operation_type="node",
                    label_or_type="Scene",
                    natural_key=scene_key,
                    source_table=GOLD_PROCESSING_RESULTS_TABLE,
                    source_id=gold_result["result_id"],
                    properties={
                        "id": scene_key,
                        "video_id": media_id,
                        "user_id": user_id,
                        "scene_index": scene_id,
                        "title": scene.get("title"),
                        "description": scene.get("summary"),
                        "start_time": scene.get("start_time"),
                        "end_time": scene.get("end_time"),
                        "duration": scene.get("duration"),
                        "scene_type": scene.get("scene_type") or "general",
                        "dominant_colors": scene.get("dominant_colors") or [],
                        "transition_type": scene.get("transition_type"),
                        "visual_change_score": scene.get("visual_change_score") or 0.0,
                        "detected_objects": scene.get("detected_objects") or [],
                        "actions": scene.get("actions") or [],
                        "entities": scene.get("entities") or [],
                        "relations": scene.get("relations") or [],
                        "scene_visual_analysis_id": scene.get("scene_visual_analysis_id"),
                        "transcript_segment": scene.get("transcript_segment"),
                        "frame_asset_id": scene.get("frame_asset_id"),
                    },
                )
            )
            rows.append(
                graph_upsert_row(
                    operation_type="relationship",
                    label_or_type="CONTAINS",
                    natural_key=f"{media_id}->CONTAINS->{scene_key}",
                    source_table=GOLD_PROCESSING_RESULTS_TABLE,
                    source_id=gold_result["result_id"],
                    properties={
                        "from_label": "Video",
                        "from_key": media_id,
                        "to_label": "Scene",
                        "to_key": scene_key,
                        "scene_index": scene_id,
                    },
                )
            )
        for chapter in gold_structure.get("chapters") or []:
            chapter_id = int(chapter.get("chapter_id") or 0)
            chapter_key = f"{media_id}:chapter:{chapter_id:06d}"
            rows.append(
                graph_upsert_row(
                    operation_type="node",
                    label_or_type="Chapter",
                    natural_key=chapter_key,
                    source_table=GOLD_PROCESSING_RESULTS_TABLE,
                    source_id=gold_result["result_id"],
                    properties={
                        "id": chapter_key,
                        "video_id": media_id,
                        "user_id": user_id,
                        "chapter_index": chapter_id,
                        "title": chapter.get("title"),
                        "summary": chapter.get("summary"),
                        "start_time": chapter.get("start_time"),
                        "end_time": chapter.get("end_time"),
                        "duration": chapter.get("duration"),
                        "scene_ids": chapter.get("scene_ids") or [],
                        "topics": chapter.get("topics") or [],
                        "detection_method": chapter.get("detection_method") or "auto",
                    },
                )
            )
            rows.append(
                graph_upsert_row(
                    operation_type="relationship",
                    label_or_type="CONTAINS",
                    natural_key=f"{media_id}->CONTAINS->{chapter_key}",
                    source_table=GOLD_PROCESSING_RESULTS_TABLE,
                    source_id=gold_result["result_id"],
                    properties={
                        "from_label": "Video",
                        "from_key": media_id,
                        "to_label": "Chapter",
                        "to_key": chapter_key,
                        "chapter_index": chapter_id,
                    },
                )
            )

    for frame in frames:
        frame_understanding = frame_ai.get(frame["frame_asset_id"], {})
        rows.append(
            graph_upsert_row(
                operation_type="node",
                label_or_type="Frame",
                natural_key=frame["frame_asset_id"],
                source_table=FRAME_ASSETS_TABLE,
                source_id=frame["frame_asset_id"],
                properties={
                    "id": frame["frame_asset_id"],
                    "video_id": media_id,
                    "user_id": user_id,
                    "frame_asset_id": frame["frame_asset_id"],
                    "frame_uri": frame["frame_uri"],
                    "frame_index": frame["frame_index"],
                    "frame_number": frame["frame_index"],
                    "timestamp_ms": frame["timestamp_ms"],
                    "timestamp": round(float(frame["timestamp_ms"]) / 1000, 3),
                    "format": frame["format"],
                    "width": frame.get("width"),
                    "height": frame.get("height"),
                    "description": frame_understanding.get("description"),
                    "detected_objects": frame_understanding.get("detected_objects") or [],
                    "analysis_structured": frame_understanding.get("normalized") or {},
                    "perceptual_hash": None,
                    "content_hash": frame.get("sha256"),
                    "blur_score": 0.0,
                    "brightness": 0.0,
                    "is_keyframe": True,
                },
            )
        )
        for detected_object in frame_understanding.get("detected_objects") or []:
            entity_name = str(detected_object).strip()
            if not entity_name:
                continue
            normalized_name = normalized_entity_name(entity_name)
            entity_key = f"{media_id}:entity:object:{stable_hash({'name': normalized_name})[:16]}"
            if entity_key not in entity_nodes_added:
                rows.append(
                    graph_upsert_row(
                        operation_type="node",
                        label_or_type="Entity",
                        natural_key=entity_key,
                        source_table=FRAME_ANALYSIS_TABLE,
                        source_id=entity_key,
                        properties={
                            "id": entity_key,
                            "video_id": media_id,
                            "user_id": user_id,
                            "entity_type": "object",
                            "name": entity_name,
                            "normalized_name": normalized_name,
                            "aliases": [],
                            "description": None,
                            "attributes": {},
                            "confidence": 1.0,
                            "bounding_box": None,
                            "external_ids": {},
                            "occurrence_count": 1,
                            "first_seen_time": round(float(frame["timestamp_ms"]) / 1000, 3),
                            "last_seen_time": round(float(frame["timestamp_ms"]) / 1000, 3),
                        },
                    )
                )
                entity_nodes_added.add(entity_key)
            rows.append(
                graph_upsert_row(
                    operation_type="relationship",
                    label_or_type="CONTAINS",
                    natural_key=f"{frame['frame_asset_id']}->CONTAINS->{entity_key}",
                    source_table=FRAME_ANALYSIS_TABLE,
                    source_id=frame["frame_asset_id"],
                    properties={
                        "from_label": "Frame",
                        "from_key": frame["frame_asset_id"],
                        "to_label": "Entity",
                        "to_key": entity_key,
                        "confidence": 1.0,
                        "source": "florence_frame_analysis",
                    },
                )
            )
        rows.append(
            graph_upsert_row(
                operation_type="relationship",
                label_or_type="CONTAINS",
                natural_key=f"{media_id}->CONTAINS->{frame['frame_asset_id']}",
                source_table=FRAME_ASSETS_TABLE,
                source_id=frame["frame_asset_id"],
                properties={
                    "from_label": "Video",
                    "from_key": media_id,
                    "to_label": "Frame",
                    "to_key": frame["frame_asset_id"],
                    "timestamp_ms": frame["timestamp_ms"],
                },
            )
        )

    for segment in transcript_segments:
        rows.append(
            graph_upsert_row(
                operation_type="node",
                label_or_type="AudioSegment",
                natural_key=segment["segment_id"],
                source_table=TRANSCRIPT_SEGMENTS_TABLE,
                source_id=segment["segment_id"],
                properties={
                    "id": segment["segment_id"],
                    "video_id": media_id,
                    "user_id": user_id,
                    "asr_run_id": segment["asr_run_id"],
                    "audio_segment_id": segment["segment_id"],
                    "chunk_id": segment["chunk_id"],
                    "segment_index": segment["segment_index"],
                    "start_ms": segment["start_ms"],
                    "end_ms": segment["end_ms"],
                    "start_time": round(float(segment["start_ms"]) / 1000, 3),
                    "end_time": round(float(segment["end_ms"]) / 1000, 3),
                    "text": segment["text"],
                    "language": segment.get("language") or (asr_run or {}).get("language") or "unknown",
                    "confidence": segment.get("confidence") or 0.0,
                    "speaker_id": None,
                    "speaker_label": None,
                },
            )
        )
        rows.append(
            graph_upsert_row(
                operation_type="relationship",
                label_or_type="HAS_TRANSCRIPT",
                natural_key=f"{media_id}->HAS_TRANSCRIPT->{segment['segment_id']}",
                source_table=TRANSCRIPT_SEGMENTS_TABLE,
                source_id=segment["segment_id"],
                properties={
                    "from_label": "Video",
                    "from_key": media_id,
                    "to_label": "AudioSegment",
                    "to_key": segment["segment_id"],
                    "start_ms": segment["start_ms"],
                    "end_ms": segment["end_ms"],
                },
            )
        )

    return rows


def register_graph_upserts(upserts: list[dict]) -> None:
    existing = load_existing_graph_upsert_rows([upsert["upsert_id"] for upsert in upserts])
    for upsert in upserts:
        upsert_to_write = upsert
        existing_upsert = existing.get(upsert["upsert_id"])
        if (
            existing_upsert
            and existing_upsert.get("status") == "applied"
            and existing_upsert.get("properties_json") == upsert["properties_json"]
        ):
            upsert_to_write = {
                **upsert,
                "status": "applied",
                "error": existing_upsert.get("error") or json_dumps({}),
            }
        merge_row(
            qualified_graph_upserts_table,
            upsert_to_write,
            GRAPH_UPSERTS_SCHEMA,
            ["upsert_id"],
        )


def load_existing_graph_upsert_rows(upsert_ids: list[str]) -> dict[str, dict]:
    if not upsert_ids:
        return {}
    quoted_ids = ", ".join(sql_literal(upsert_id) for upsert_id in sorted(set(upsert_ids)))
    rows = spark.sql(
        f"""
        SELECT upsert_id, status, properties_json, error
        FROM {qualified_graph_upserts_table}
        WHERE media_id = {sql_literal(media_id)}
          AND dispatch_id = {sql_literal(dispatch_id)}
          AND upsert_id IN ({quoted_ids})
        """
    ).collect()
    return {row["upsert_id"]: row.asDict() for row in rows}


def load_graph_upserts_for_projection() -> list[dict]:
    rows = spark.sql(
        f"""
        SELECT
          upsert_id,
          media_id,
          dispatch_id,
          graph_version,
          operation_type,
          label_or_type,
          natural_key,
          source_table,
          source_id,
          properties_json,
          status,
          created_at,
          updated_at,
          error
        FROM {qualified_graph_upserts_table}
        WHERE media_id = {sql_literal(media_id)}
          AND dispatch_id = {sql_literal(dispatch_id)}
          AND status IN ('pending', 'failed')
        ORDER BY
          CASE operation_type WHEN 'node' THEN 0 ELSE 1 END,
          created_at ASC,
          upsert_id ASC
        """
    ).collect()
    return [row.asDict() for row in rows]


def update_graph_upsert_status(upsert: dict, status: str, error: dict | None = None) -> None:
    merge_row(
        qualified_graph_upserts_table,
        {
            **upsert,
            "status": status,
            "updated_at": datetime.now(UTC),
            "error": json_dumps(error or {}),
        },
        GRAPH_UPSERTS_SCHEMA,
        ["upsert_id"],
    )


def validate_neo4j_uri(uri: str) -> str:
    normalized = validate_no_uri_credentials(uri, "neo4j.uri")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"bolt", "bolt+s", "bolt+ssc", "neo4j", "neo4j+s", "neo4j+ssc"}:
        raise ValueError("NEO4J_URI must use a Neo4j Bolt URI scheme")
    if not parsed.hostname:
        raise ValueError("NEO4J_URI must include a host")
    allowed_suffixes = {
        suffix.strip().lower()
        for suffix in os.environ.get("NEO4J_ALLOWED_HOST_SUFFIXES", "").split(",")
        if suffix.strip()
    }
    hostname = parsed.hostname.lower()
    if allowed_suffixes and not any(
        hostname == suffix or hostname.endswith(f".{suffix}") for suffix in allowed_suffixes
    ):
        raise ValueError("Neo4j URI host is not in the deployment allowlist")
    return normalized


def neo4j_projector_config() -> dict:
    cfg = pipeline_config.get("neo4j") or {}
    if not isinstance(cfg, dict):
        raise ValueError("pipeline_config.neo4j must be an object when provided")

    uri = str(os.environ.get("NEO4J_URI") or "").strip()
    user = str(os.environ.get("NEO4J_USER") or "neo4j").strip()
    database = str(os.environ.get("NEO4J_DATABASE") or "neo4j").strip()
    password = resolve_neo4j_password()

    if not uri:
        raise ValueError("Neo4j URI is missing. Set NEO4J_URI in the Databricks cluster environment.")
    if not user:
        raise ValueError("Neo4j user is missing. Set NEO4J_USER in the Databricks cluster environment.")
    if not database:
        raise ValueError("Neo4j database is missing. Set NEO4J_DATABASE in the Databricks cluster environment.")
    if not password:
        raise ValueError(
            "Neo4j password is missing. Set NEO4J_PASSWORD or "
            "NEO4J_PASSWORD_SECRET_SCOPE/NEO4J_PASSWORD_SECRET_KEY from deployment configuration."
        )
    return {
        "uri": validate_neo4j_uri(uri),
        "user": user,
        "password": password,
        "database": database,
    }


def quote_neo4j_identifier(value: str, field_name: str) -> str:
    if not IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"Invalid Neo4j {field_name}: {value}")
    return f"`{value}`"


def neo4j_property_value(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list):
        normalized_items = []
        for item in value:
            if item is None or isinstance(item, str | int | float | bool):
                normalized_items.append(item)
            else:
                normalized_items.append(json.dumps(item, separators=(",", ":"), sort_keys=True))
        return normalized_items
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def neo4j_properties(properties: dict) -> dict:
    return {key: neo4j_property_value(value) for key, value in properties.items()}


def neo4j_node_match_property(label_or_type: str, properties: dict) -> str:
    if label_or_type == "Video" and properties.get("video_id"):
        return "video_id"
    if properties.get("id"):
        return "id"
    return "natural_key"


def apply_graph_upsert(session: Any, upsert: dict) -> None:
    operation_type = upsert["operation_type"]
    label_or_type = str(upsert["label_or_type"])
    properties = neo4j_properties(parse_json_dict(upsert["properties_json"]))
    now_iso = datetime.now(UTC).isoformat()

    if operation_type == "node":
        label = quote_neo4j_identifier(label_or_type, "label")
        match_property = neo4j_node_match_property(label_or_type, properties)
        match_key = properties.get(match_property) or upsert["natural_key"]
        quoted_match_property = quote_neo4j_identifier(match_property, "node match property")
        query = f"""
        MERGE (node:{label} {{{quoted_match_property}: $match_key}})
        SET node += $properties,
            node.natural_key = $natural_key,
            node.qprisma_source_table = $source_table,
            node.qprisma_source_id = $source_id,
            node.qprisma_graph_version = $graph_version,
            node.qprisma_updated_at = $updated_at
        """
        session.run(
            query,
            match_key=match_key,
            natural_key=upsert["natural_key"],
            properties=properties,
            source_table=upsert["source_table"],
            source_id=upsert["source_id"],
            graph_version=upsert["graph_version"],
            updated_at=now_iso,
        ).consume()
        return

    if operation_type == "relationship":
        rel_type = quote_neo4j_identifier(label_or_type, "relationship type")
        from_label = quote_neo4j_identifier(str(properties.get("from_label") or ""), "label")
        to_label = quote_neo4j_identifier(str(properties.get("to_label") or ""), "label")
        from_key = properties.get("from_key")
        to_key = properties.get("to_key")
        if not isinstance(from_key, str) or not isinstance(to_key, str):
            raise ValueError(f"Relationship upsert {upsert['upsert_id']} requires from_key and to_key")

        query = f"""
        MERGE (source:{from_label} {{natural_key: $from_key}})
        MERGE (target:{to_label} {{natural_key: $to_key}})
        MERGE (source)-[rel:{rel_type} {{natural_key: $natural_key}}]->(target)
        SET rel += $properties,
            rel.natural_key = $natural_key,
            rel.qprisma_source_table = $source_table,
            rel.qprisma_source_id = $source_id,
            rel.qprisma_graph_version = $graph_version,
            rel.qprisma_updated_at = $updated_at
        """
        session.run(
            query,
            from_key=from_key,
            to_key=to_key,
            natural_key=upsert["natural_key"],
            properties=properties,
            source_table=upsert["source_table"],
            source_id=upsert["source_id"],
            graph_version=upsert["graph_version"],
            updated_at=now_iso,
        ).consume()
        return

    raise ValueError(f"Unsupported graph upsert operation_type: {operation_type}")


def graph_upsert_projection_group(upsert: dict) -> tuple:
    operation_type = str(upsert["operation_type"])
    label_or_type = str(upsert["label_or_type"])
    properties = neo4j_properties(parse_json_dict(upsert["properties_json"]))
    if operation_type == "node":
        match_property = neo4j_node_match_property(label_or_type, properties)
        quote_neo4j_identifier(label_or_type, "label")
        quote_neo4j_identifier(match_property, "node match property")
        return ("node", label_or_type, match_property)
    if operation_type == "relationship":
        from_label = str(properties.get("from_label") or "")
        to_label = str(properties.get("to_label") or "")
        if not from_label or not properties.get("from_key") or not to_label or not properties.get("to_key"):
            raise ValueError("Relationship graph upsert requires from_label/from_key/to_label/to_key properties")
        quote_neo4j_identifier(label_or_type, "relationship type")
        quote_neo4j_identifier(from_label, "from_label")
        quote_neo4j_identifier(to_label, "to_label")
        return ("relationship", label_or_type, from_label, to_label)
    raise ValueError(f"Unsupported graph upsert operation_type: {operation_type}")


def grouped_graph_upserts(upserts: list[dict]) -> tuple[dict[tuple, list[dict]], list[dict]]:
    groups: dict[tuple, list[dict]] = {}
    failed: list[dict] = []
    for upsert in upserts:
        try:
            key = graph_upsert_projection_group(upsert)
            groups.setdefault(key, []).append(upsert)
        except Exception as exc:
            failure = {"upsert_id": upsert["upsert_id"], "message": str(exc)}
            failed.append(failure)
            update_graph_upsert_status(
                upsert,
                "failed",
                {"error_type": type(exc).__name__, "message": str(exc)},
            )
    return groups, failed


def apply_node_upsert_batch(
    session: Any,
    *,
    label_or_type: str,
    match_property: str,
    upserts: list[dict],
) -> int:
    label = quote_neo4j_identifier(label_or_type, "label")
    quoted_match_property = quote_neo4j_identifier(match_property, "node match property")
    now_iso = datetime.now(UTC).isoformat()
    rows = []
    for upsert in upserts:
        properties = neo4j_properties(parse_json_dict(upsert["properties_json"]))
        rows.append(
            {
                "match_key": properties.get(match_property) or upsert["natural_key"],
                "natural_key": upsert["natural_key"],
                "properties": properties,
                "source_table": upsert["source_table"],
                "source_id": upsert["source_id"],
                "graph_version": upsert["graph_version"],
            }
        )
    query = f"""
    UNWIND $rows AS row
    MERGE (node:{label} {{{quoted_match_property}: row.match_key}})
    SET node += row.properties,
        node.natural_key = row.natural_key,
        node.qprisma_source_table = row.source_table,
        node.qprisma_source_id = row.source_id,
        node.qprisma_graph_version = row.graph_version,
        node.qprisma_updated_at = $updated_at
    RETURN count(node) AS applied
    """
    record = session.run(query, rows=rows, updated_at=now_iso).single()
    return int(record["applied"] if record else 0)


def apply_relationship_upsert_batch(
    session: Any,
    *,
    rel_type: str,
    from_label: str,
    to_label: str,
    upserts: list[dict],
) -> int:
    quoted_rel_type = quote_neo4j_identifier(rel_type, "relationship type")
    quoted_from_label = quote_neo4j_identifier(from_label, "from_label")
    quoted_to_label = quote_neo4j_identifier(to_label, "to_label")
    now_iso = datetime.now(UTC).isoformat()
    rows = []
    for upsert in upserts:
        properties = neo4j_properties(parse_json_dict(upsert["properties_json"]))
        rows.append(
            {
                "from_key": properties["from_key"],
                "to_key": properties["to_key"],
                "natural_key": upsert["natural_key"],
                "properties": properties,
                "source_table": upsert["source_table"],
                "source_id": upsert["source_id"],
                "graph_version": upsert["graph_version"],
            }
        )
    query = f"""
    UNWIND $rows AS row
    MATCH (source:{quoted_from_label} {{natural_key: row.from_key}})
    MATCH (target:{quoted_to_label} {{natural_key: row.to_key}})
    MERGE (source)-[rel:{quoted_rel_type} {{natural_key: row.natural_key}}]->(target)
    SET rel += row.properties,
        rel.natural_key = row.natural_key,
        rel.qprisma_source_table = row.source_table,
        rel.qprisma_source_id = row.source_id,
        rel.qprisma_graph_version = row.graph_version,
        rel.qprisma_updated_at = $updated_at
    RETURN count(rel) AS applied
    """
    record = session.run(query, rows=rows, updated_at=now_iso).single()
    return int(record["applied"] if record else 0)


def apply_graph_upsert_group(session: Any, group_key: tuple, upserts: list[dict]) -> int:
    if group_key[0] == "node":
        _, label_or_type, match_property = group_key
        return apply_node_upsert_batch(
            session,
            label_or_type=label_or_type,
            match_property=match_property,
            upserts=upserts,
        )
    if group_key[0] == "relationship":
        _, rel_type, from_label, to_label = group_key
        return apply_relationship_upsert_batch(
            session,
            rel_type=rel_type,
            from_label=from_label,
            to_label=to_label,
            upserts=upserts,
        )
    raise ValueError(f"Unsupported graph upsert group: {group_key}")


def project_neo4j_graph() -> dict:
    projection_started = time.perf_counter()
    decision = neo4j_projector_decision()
    if not decision["enabled"]:
        return {
            "applied_count": 0,
            "failed_count": 0,
            "graph_upserts_table": GRAPH_UPSERTS_TABLE,
            "skipped": True,
            "skipped_reason": decision["skipped_reason"],
            "neo4j_required": decision["required"],
            "neo4j_uri_configured": bool(str(os.environ.get("NEO4J_URI") or "").strip()),
            "neo4j_password_configured": neo4j_password_configured(),
            "elapsed_seconds": rounded_metric(time.perf_counter() - projection_started),
        }

    config = neo4j_projector_config()
    upserts = load_graph_upserts_for_projection()
    if not upserts:
        return {
            "applied_count": 0,
            "failed_count": 0,
            "graph_upserts_table": GRAPH_UPSERTS_TABLE,
            "reused_completed": True,
            "neo4j_required": decision["required"],
            "neo4j_database": config["database"],
            "elapsed_seconds": rounded_metric(time.perf_counter() - projection_started),
        }

    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise RuntimeError(
            "neo4j Python driver is not installed on the Databricks job cluster. "
            "Install the task PyPI dependency before running project_neo4j_graph."
        ) from exc

    driver = GraphDatabase.driver(config["uri"], auth=(config["user"], config["password"]))
    applied_count = 0
    batch_group_count = 0
    fallback_row_count = 0
    failed: list[dict] = []
    try:
        driver.verify_connectivity()
        groups, failed = grouped_graph_upserts(upserts)
        with driver.session(database=config["database"]) as session:
            for group_key, group_upserts in groups.items():
                try:
                    applied_in_group = apply_graph_upsert_group(session, group_key, group_upserts)
                    if applied_in_group != len(group_upserts):
                        raise RuntimeError(
                            f"Neo4j batch group {group_key} applied {applied_in_group} "
                            f"of {len(group_upserts)} upserts"
                        )
                    for upsert in group_upserts:
                        update_graph_upsert_status(upsert, "applied")
                    applied_count += applied_in_group
                    batch_group_count += 1
                except Exception:
                    for upsert in group_upserts:
                        try:
                            apply_graph_upsert(session, upsert)
                            update_graph_upsert_status(upsert, "applied")
                            applied_count += 1
                            fallback_row_count += 1
                        except Exception as exc:
                            failure = {"upsert_id": upsert["upsert_id"], "message": str(exc)}
                            failed.append(failure)
                            update_graph_upsert_status(
                                upsert,
                                "failed",
                                {"error_type": type(exc).__name__, "message": str(exc)},
                            )
    finally:
        driver.close()

    if failed:
        raise RuntimeError(f"Failed to apply {len(failed)} Neo4j graph upserts")

    elapsed = time.perf_counter() - projection_started
    return {
        "applied_count": applied_count,
        "failed_count": 0,
        "pending_or_failed_count": len(upserts),
        "elapsed_seconds": rounded_metric(elapsed),
        "upserts_per_second": rate_metric(applied_count, elapsed),
        "batch_group_count": batch_group_count,
        "fallback_row_count": fallback_row_count,
        "graph_upserts_table": GRAPH_UPSERTS_TABLE,
        "neo4j_database": config["database"],
    }

