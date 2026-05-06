"""Operational event, outbox, run, and quarantine writers."""

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

def json_dumps(value: dict) -> str:
    return json.dumps(value or {}, separators=(",", ":"), sort_keys=True)


def rounded_metric(value: float | int | None, digits: int = 3) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def rate_metric(count: float | int | None, elapsed_seconds: float | int | None) -> float | None:
    elapsed = float(elapsed_seconds or 0)
    if elapsed <= 0:
        return None
    return rounded_metric(float(count or 0) / elapsed)


def is_delta_concurrency_error(exc: Exception) -> bool:
    message = str(exc)
    return any(
        marker in message
        for marker in (
            "DELTA_CONCURRENT_APPEND",
            "ConcurrentAppendException",
            "ConcurrentDeleteReadException",
            "ConcurrentWriteException",
        )
    )


def merge_row(table_name: str, row: dict, row_schema: StructType, key_columns: list[str]) -> None:
    on_clause = " AND ".join(f"target.{key} = source.{key}" for key in key_columns)
    update_fields = [
        field.name for field in row_schema if field.name not in {"created_at", "started_at"}
    ]
    update_clause = ", ".join(f"target.{field} = source.{field}" for field in update_fields)
    insert_columns = ", ".join(field.name for field in row_schema)
    insert_values = ", ".join(f"source.{field.name}" for field in row_schema)
    for attempt in range(5):
        temp_view = f"merge_{uuid4().hex}"
        spark.createDataFrame([row], schema=row_schema).createOrReplaceTempView(temp_view)
        try:
            spark.sql(
                f"""
                MERGE INTO {table_name} AS target
                USING {temp_view} AS source
                ON {on_clause}
                WHEN MATCHED THEN UPDATE SET {update_clause}
                WHEN NOT MATCHED THEN INSERT ({insert_columns})
                VALUES ({insert_values})
                """
            )
            return
        except Exception as exc:
            if not is_delta_concurrency_error(exc) or attempt == 4:
                raise
            time.sleep(0.5 * (2**attempt))


def write_event(
    *,
    status: str,
    message: str,
    source_uri: str = "",
    details: dict | None = None,
) -> None:
    event = {
        "event_id": str(uuid4()),
        "schema_version": schema_version,
        "media_id": media_id,
        "dispatch_id": dispatch_id,
        "user_id": user_id,
        "blob_name": blob_name,
        "queue_name": queue_name,
        "stage": stage,
        "status": status,
        "message": message,
        "source_uri": source_uri,
        "details": json.dumps(details or {}, separators=(",", ":"), sort_keys=True),
        "event_time": datetime.now(UTC),
    }
    spark.createDataFrame([event]).write.mode("append").saveAsTable(qualified_ops_table)


def write_outbox_event(
    *,
    status: str,
    progress: float,
    message: str,
    processing_result: dict | None = None,
    video_metadata: dict | None = None,
    error: dict | None = None,
) -> None:
    event = {
        "outbox_id": str(uuid4()),
        "schema_version": schema_version,
        "media_id": media_id,
        "dispatch_id": dispatch_id,
        "user_id": user_id,
        "status": status,
        "progress": float(progress),
        "message": message,
        "processing_result": json.dumps(
            processing_result or {}, separators=(",", ":"), sort_keys=True
        ),
        "video_metadata": json.dumps(video_metadata or {}, separators=(",", ":"), sort_keys=True),
        "error": json.dumps(error or {}, separators=(",", ":"), sort_keys=True),
        "emitted_at": datetime.now(UTC),
        "consumed_at": None,
    }
    spark.createDataFrame([event], schema=OUTBOX_SCHEMA).write.mode("append").saveAsTable(
        qualified_outbox_table
    )


def progress_for_stage(stage_name: str) -> float:
    return STAGE_PROGRESS.get(stage_name, 0.0)


def write_progress_outbox(stage_name: str, message: str, progress: float | None = None) -> None:
    write_outbox_event(
        status="running",
        progress=progress_for_stage(stage_name) if progress is None else progress,
        message=message,
        processing_result={
            "backend": "databricks",
            "pipeline": "lakehouse_pilot",
            "current_stage": stage_name,
            "dispatch_id": dispatch_id,
        },
    )


def upsert_processing_run(
    *,
    status: str,
    progress: float,
    current_stage: str,
    error: dict | None = None,
    completed: bool = False,
) -> None:
    now = datetime.now(UTC)
    merge_row(
        qualified_runs_table,
        {
            "run_id": run_id,
            "media_id": media_id,
            "dispatch_id": dispatch_id,
            "schema_version": schema_version,
            "processing_version": processing_version,
            "config_hash": config_hash,
            "status": status,
            "progress": float(progress),
            "current_stage": current_stage,
            "started_at": now,
            "updated_at": now,
            "completed_at": now if completed else None,
            "error": json_dumps(error or {}),
        },
        PROCESSING_RUNS_SCHEMA,
        ["run_id"],
    )


def write_stage_run(
    *,
    stage_name: str,
    status: str,
    message: str,
    progress: float | None = None,
    metrics: dict | None = None,
    error: dict | None = None,
    completed: bool = False,
) -> None:
    now = datetime.now(UTC)
    merge_row(
        qualified_stage_runs_table,
        {
            "stage_run_id": f"{run_id}:{stage_name}:1",
            "run_id": run_id,
            "media_id": media_id,
            "dispatch_id": dispatch_id,
            "stage": stage_name,
            "status": status,
            "progress": progress_for_stage(stage_name) if progress is None else float(progress),
            "message": message,
            "attempt": 1,
            "started_at": now,
            "completed_at": now if completed else None,
            "metrics": json_dumps(metrics or {}),
            "error": json_dumps(error or {}),
        },
        STAGE_RUNS_SCHEMA,
        ["stage_run_id"],
    )


def register_manifest(source_uri: str = "") -> None:
    now = datetime.now(UTC)
    merge_row(
        qualified_manifest_table,
        {
            "media_id": media_id,
            "dispatch_id": dispatch_id,
            "schema_version": schema_version,
            "user_id": user_id,
            "blob_name": blob_name,
            "source_uri": source_uri,
            "source_media": json_dumps(safe_source_media_for_persistence()),
            "pipeline_config": json_dumps(safe_pipeline_config_for_persistence()),
            "config_hash": config_hash,
            "created_at": now,
            "updated_at": now,
        },
        MEDIA_MANIFEST_SCHEMA,
        ["media_id", "dispatch_id"],
    )


def register_source_file(source_uri: str, probe: dict, quality: dict | None = None) -> None:
    quality = quality or {}
    metadata = quality.get("metadata") or {}
    merge_row(
        qualified_source_files_table,
        {
            "media_id": media_id,
            "dispatch_id": dispatch_id,
            "source_uri": source_uri,
            "path": probe["path"],
            "length": int(probe["length"]),
            "modification_time": probe.get("modification_time"),
            "format_name": metadata.get("format_name"),
            "duration_seconds": metadata.get("duration_seconds"),
            "video_codec": metadata.get("video_codec"),
            "audio_codec": metadata.get("audio_codec"),
            "width": metadata.get("width"),
            "height": metadata.get("height"),
            "fps": metadata.get("fps"),
            "has_audio": str(bool(metadata.get("has_audio"))).lower(),
            "quality_status": str(quality.get("status") or "unknown"),
            "quality_details": json_dumps(quality),
            "validated_at": datetime.now(UTC),
        },
        SOURCE_FILES_SCHEMA,
        ["media_id", "dispatch_id", "source_uri"],
    )


def write_quarantine(*, stage_name: str, reason: str, exc: Exception) -> None:
    spark.createDataFrame(
        [
            {
                "quarantine_id": str(uuid4()),
                "media_id": media_id,
                "dispatch_id": dispatch_id,
                "stage": stage_name,
                "reason": reason,
                "error_type": type(exc).__name__,
                "details": json_dumps({"message": str(exc)}),
                "created_at": datetime.now(UTC),
            }
        ],
        schema=QUARANTINE_SCHEMA,
    ).write.mode("append").saveAsTable(qualified_quarantine_table)

