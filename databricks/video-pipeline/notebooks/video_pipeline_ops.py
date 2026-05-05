# Databricks notebook source
"""Observable QPrisma video-processing lakehouse job.

This job validates the Service Bus -> Databricks contract, writes operational
Delta records per stage, and moves media understanding into governed
Databricks ETL tasks.
"""

# ruff: noqa: F821, S603, S608

# COMMAND ----------

import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from urllib.parse import urlparse
from uuid import uuid4

from pyspark.sql.types import (
    DoubleType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

# COMMAND ----------

WIDGET_DEFAULTS = {
    "catalog": "dbw_qprisma_dev",
    "schema": "video",
    "queue_name": "video-processing",
    "stage": "register_manifest",
    "schema_version": "2026-05-01",
    "dispatch_id": "",
    "media_id": "",
    "blob_name": "",
    "user_id": "",
    "source_media": "{}",
    "pipeline_config": "{}",
}

for widget_name, default_value in WIDGET_DEFAULTS.items():
    dbutils.widgets.text(widget_name, default_value)


def widget(name: str, *, required: bool = False) -> str:
    value = dbutils.widgets.get(name).strip()
    if required and not value:
        raise ValueError(f"Required Databricks job parameter '{name}' is missing")
    return value


catalog = widget("catalog", required=True)
schema = widget("schema", required=True)
queue_name = widget("queue_name", required=True)
stage = widget("stage", required=True)
schema_version = widget("schema_version", required=True)
dispatch_id = widget("dispatch_id", required=True)
media_id = widget("media_id", required=True)
blob_name = widget("blob_name", required=True)
user_id = widget("user_id")
source_media_raw = widget("source_media", required=True)
pipeline_config_raw = widget("pipeline_config")

# COMMAND ----------

IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
OPS_EVENTS_TABLE = "video_pipeline_events"
OPS_OUTBOX_TABLE = "video_pipeline_outbox"
MEDIA_MANIFEST_TABLE = "video_media_manifest"
SOURCE_FILES_TABLE = "video_source_files"
PROCESSING_RUNS_TABLE = "video_processing_runs"
STAGE_RUNS_TABLE = "video_job_stage_runs"
QUARANTINE_TABLE = "video_record_quarantine"
AUDIO_ASSETS_TABLE = "video_audio_assets"
AUDIO_CHUNKS_TABLE = "video_audio_chunks"
ASR_RUNS_TABLE = "video_asr_runs"
TRANSCRIPT_SEGMENTS_TABLE = "video_transcript_segments"
FRAME_ASSETS_TABLE = "video_frame_assets"
AI_REQUESTS_TABLE = "video_ai_requests"
AI_BATCHES_TABLE = "video_ai_batches"
AI_RESULTS_TABLE = "video_ai_results"
GRAPH_UPSERTS_TABLE = "video_graph_upserts"

STAGE_PROGRESS = {
    "register_manifest": 0.10,
    "validate_and_probe_media": 0.20,
    "extract_audio_assets": 0.30,
    "extract_frame_assets": 0.40,
    "run_faster_whisper_asr": 0.55,
    "build_multimodal_inference_requests": 0.68,
    "stage_ai_batch_payloads": 0.78,
    "build_graph_upserts": 0.88,
    "publish_outbox": 1.00,
}
STAGE_MESSAGES = {
    "register_manifest": "Registering video manifest in Databricks",
    "validate_and_probe_media": "Validating staged source media in Databricks",
    "extract_audio_assets": "Extracting audio assets with FFmpeg",
    "extract_frame_assets": "Preparing frame extraction assets",
    "run_faster_whisper_asr": "Preparing faster-whisper transcription",
    "build_multimodal_inference_requests": "Preparing multimodal inference requests",
    "stage_ai_batch_payloads": "Staging Azure OpenAI Batch payloads",
    "build_graph_upserts": "Preparing Neo4j graph upsert intents",
    "publish_outbox": "Publishing Databricks lakehouse result",
}
PIPELINE_STAGES = [
    "register_manifest",
    "validate_and_probe_media",
    "extract_audio_assets",
    "extract_frame_assets",
    "run_faster_whisper_asr",
    "build_multimodal_inference_requests",
    "stage_ai_batch_payloads",
    "build_graph_upserts",
    "publish_outbox",
]
OUTBOX_SCHEMA = StructType(
    [
        StructField("outbox_id", StringType(), nullable=False),
        StructField("schema_version", StringType(), nullable=False),
        StructField("media_id", StringType(), nullable=False),
        StructField("dispatch_id", StringType(), nullable=False),
        StructField("user_id", StringType(), nullable=True),
        StructField("status", StringType(), nullable=False),
        StructField("progress", DoubleType(), nullable=False),
        StructField("message", StringType(), nullable=False),
        StructField("processing_result", StringType(), nullable=False),
        StructField("video_metadata", StringType(), nullable=False),
        StructField("error", StringType(), nullable=False),
        StructField("emitted_at", TimestampType(), nullable=False),
        StructField("consumed_at", TimestampType(), nullable=True),
    ]
)
MEDIA_MANIFEST_SCHEMA = StructType(
    [
        StructField("media_id", StringType(), nullable=False),
        StructField("dispatch_id", StringType(), nullable=False),
        StructField("schema_version", StringType(), nullable=False),
        StructField("user_id", StringType(), nullable=True),
        StructField("blob_name", StringType(), nullable=False),
        StructField("source_uri", StringType(), nullable=True),
        StructField("source_media", StringType(), nullable=False),
        StructField("pipeline_config", StringType(), nullable=False),
        StructField("config_hash", StringType(), nullable=False),
        StructField("created_at", TimestampType(), nullable=False),
        StructField("updated_at", TimestampType(), nullable=False),
    ]
)
SOURCE_FILES_SCHEMA = StructType(
    [
        StructField("media_id", StringType(), nullable=False),
        StructField("dispatch_id", StringType(), nullable=False),
        StructField("source_uri", StringType(), nullable=False),
        StructField("path", StringType(), nullable=False),
        StructField("length", LongType(), nullable=False),
        StructField("modification_time", StringType(), nullable=True),
        StructField("validated_at", TimestampType(), nullable=False),
    ]
)
PROCESSING_RUNS_SCHEMA = StructType(
    [
        StructField("run_id", StringType(), nullable=False),
        StructField("media_id", StringType(), nullable=False),
        StructField("dispatch_id", StringType(), nullable=False),
        StructField("schema_version", StringType(), nullable=False),
        StructField("processing_version", StringType(), nullable=False),
        StructField("config_hash", StringType(), nullable=False),
        StructField("status", StringType(), nullable=False),
        StructField("progress", DoubleType(), nullable=False),
        StructField("current_stage", StringType(), nullable=False),
        StructField("started_at", TimestampType(), nullable=False),
        StructField("updated_at", TimestampType(), nullable=False),
        StructField("completed_at", TimestampType(), nullable=True),
        StructField("error", StringType(), nullable=False),
    ]
)
STAGE_RUNS_SCHEMA = StructType(
    [
        StructField("stage_run_id", StringType(), nullable=False),
        StructField("run_id", StringType(), nullable=False),
        StructField("media_id", StringType(), nullable=False),
        StructField("dispatch_id", StringType(), nullable=False),
        StructField("stage", StringType(), nullable=False),
        StructField("status", StringType(), nullable=False),
        StructField("progress", DoubleType(), nullable=False),
        StructField("message", StringType(), nullable=False),
        StructField("attempt", LongType(), nullable=False),
        StructField("started_at", TimestampType(), nullable=False),
        StructField("completed_at", TimestampType(), nullable=True),
        StructField("metrics", StringType(), nullable=False),
        StructField("error", StringType(), nullable=False),
    ]
)
QUARANTINE_SCHEMA = StructType(
    [
        StructField("quarantine_id", StringType(), nullable=False),
        StructField("media_id", StringType(), nullable=False),
        StructField("dispatch_id", StringType(), nullable=False),
        StructField("stage", StringType(), nullable=False),
        StructField("reason", StringType(), nullable=False),
        StructField("error_type", StringType(), nullable=False),
        StructField("details", StringType(), nullable=False),
        StructField("created_at", TimestampType(), nullable=False),
    ]
)
AUDIO_ASSETS_SCHEMA = StructType(
    [
        StructField("audio_asset_id", StringType(), nullable=False),
        StructField("media_id", StringType(), nullable=False),
        StructField("dispatch_id", StringType(), nullable=False),
        StructField("source_uri", StringType(), nullable=False),
        StructField("audio_uri", StringType(), nullable=False),
        StructField("format", StringType(), nullable=False),
        StructField("codec", StringType(), nullable=False),
        StructField("sample_rate_hz", LongType(), nullable=False),
        StructField("channels", LongType(), nullable=False),
        StructField("duration_seconds", DoubleType(), nullable=False),
        StructField("size_bytes", LongType(), nullable=False),
        StructField("sha256", StringType(), nullable=False),
        StructField("created_at", TimestampType(), nullable=False),
        StructField("updated_at", TimestampType(), nullable=False),
    ]
)
AUDIO_CHUNKS_SCHEMA = StructType(
    [
        StructField("chunk_id", StringType(), nullable=False),
        StructField("audio_asset_id", StringType(), nullable=False),
        StructField("media_id", StringType(), nullable=False),
        StructField("dispatch_id", StringType(), nullable=False),
        StructField("chunk_index", LongType(), nullable=False),
        StructField("start_ms", LongType(), nullable=False),
        StructField("end_ms", LongType(), nullable=False),
        StructField("audio_uri", StringType(), nullable=False),
        StructField("duration_seconds", DoubleType(), nullable=False),
        StructField("created_at", TimestampType(), nullable=False),
    ]
)
ASR_RUNS_SCHEMA = StructType(
    [
        StructField("asr_run_id", StringType(), nullable=False),
        StructField("media_id", StringType(), nullable=False),
        StructField("dispatch_id", StringType(), nullable=False),
        StructField("audio_asset_id", StringType(), nullable=False),
        StructField("model_name", StringType(), nullable=False),
        StructField("device", StringType(), nullable=False),
        StructField("compute_type", StringType(), nullable=False),
        StructField("batch_size", LongType(), nullable=False),
        StructField("language", StringType(), nullable=True),
        StructField("language_probability", DoubleType(), nullable=True),
        StructField("duration_seconds", DoubleType(), nullable=True),
        StructField("segment_count", LongType(), nullable=False),
        StructField("transcript_text", StringType(), nullable=False),
        StructField("status", StringType(), nullable=False),
        StructField("started_at", TimestampType(), nullable=False),
        StructField("completed_at", TimestampType(), nullable=True),
        StructField("metrics", StringType(), nullable=False),
        StructField("error", StringType(), nullable=False),
    ]
)
TRANSCRIPT_SEGMENTS_SCHEMA = StructType(
    [
        StructField("segment_id", StringType(), nullable=False),
        StructField("asr_run_id", StringType(), nullable=False),
        StructField("media_id", StringType(), nullable=False),
        StructField("dispatch_id", StringType(), nullable=False),
        StructField("audio_asset_id", StringType(), nullable=False),
        StructField("chunk_id", StringType(), nullable=False),
        StructField("segment_index", LongType(), nullable=False),
        StructField("start_ms", LongType(), nullable=False),
        StructField("end_ms", LongType(), nullable=False),
        StructField("text", StringType(), nullable=False),
        StructField("language", StringType(), nullable=True),
        StructField("confidence", DoubleType(), nullable=True),
        StructField("created_at", TimestampType(), nullable=False),
    ]
)
FRAME_ASSETS_SCHEMA = StructType(
    [
        StructField("frame_asset_id", StringType(), nullable=False),
        StructField("media_id", StringType(), nullable=False),
        StructField("dispatch_id", StringType(), nullable=False),
        StructField("source_uri", StringType(), nullable=False),
        StructField("frame_uri", StringType(), nullable=False),
        StructField("frame_index", LongType(), nullable=False),
        StructField("timestamp_ms", LongType(), nullable=False),
        StructField("format", StringType(), nullable=False),
        StructField("width", LongType(), nullable=True),
        StructField("height", LongType(), nullable=True),
        StructField("size_bytes", LongType(), nullable=False),
        StructField("sha256", StringType(), nullable=False),
        StructField("extraction_method", StringType(), nullable=False),
        StructField("created_at", TimestampType(), nullable=False),
        StructField("updated_at", TimestampType(), nullable=False),
    ]
)
AI_REQUESTS_SCHEMA = StructType(
    [
        StructField("request_id", StringType(), nullable=False),
        StructField("media_id", StringType(), nullable=False),
        StructField("dispatch_id", StringType(), nullable=False),
        StructField("source_type", StringType(), nullable=False),
        StructField("source_id", StringType(), nullable=False),
        StructField("model_name", StringType(), nullable=False),
        StructField("prompt_version", StringType(), nullable=False),
        StructField("input_uri", StringType(), nullable=True),
        StructField("input_hash", StringType(), nullable=False),
        StructField("request_payload", StringType(), nullable=False),
        StructField("status", StringType(), nullable=False),
        StructField("created_at", TimestampType(), nullable=False),
        StructField("updated_at", TimestampType(), nullable=False),
    ]
)
AI_BATCHES_SCHEMA = StructType(
    [
        StructField("batch_id", StringType(), nullable=False),
        StructField("media_id", StringType(), nullable=False),
        StructField("dispatch_id", StringType(), nullable=False),
        StructField("batch_uri", StringType(), nullable=False),
        StructField("request_count", LongType(), nullable=False),
        StructField("model_names", StringType(), nullable=False),
        StructField("status", StringType(), nullable=False),
        StructField("provider_batch_id", StringType(), nullable=True),
        StructField("created_at", TimestampType(), nullable=False),
        StructField("updated_at", TimestampType(), nullable=False),
        StructField("submitted_at", TimestampType(), nullable=True),
        StructField("completed_at", TimestampType(), nullable=True),
        StructField("error", StringType(), nullable=False),
    ]
)
AI_RESULTS_SCHEMA = StructType(
    [
        StructField("result_id", StringType(), nullable=False),
        StructField("request_id", StringType(), nullable=False),
        StructField("batch_id", StringType(), nullable=False),
        StructField("media_id", StringType(), nullable=False),
        StructField("dispatch_id", StringType(), nullable=False),
        StructField("source_type", StringType(), nullable=False),
        StructField("source_id", StringType(), nullable=False),
        StructField("model_name", StringType(), nullable=False),
        StructField("prompt_version", StringType(), nullable=False),
        StructField("status", StringType(), nullable=False),
        StructField("response_json", StringType(), nullable=False),
        StructField("normalized_json", StringType(), nullable=False),
        StructField("tokens_prompt", LongType(), nullable=True),
        StructField("tokens_completion", LongType(), nullable=True),
        StructField("created_at", TimestampType(), nullable=False),
        StructField("updated_at", TimestampType(), nullable=False),
        StructField("error", StringType(), nullable=False),
    ]
)
GRAPH_UPSERTS_SCHEMA = StructType(
    [
        StructField("upsert_id", StringType(), nullable=False),
        StructField("media_id", StringType(), nullable=False),
        StructField("dispatch_id", StringType(), nullable=False),
        StructField("graph_version", StringType(), nullable=False),
        StructField("operation_type", StringType(), nullable=False),
        StructField("label_or_type", StringType(), nullable=False),
        StructField("natural_key", StringType(), nullable=False),
        StructField("source_table", StringType(), nullable=False),
        StructField("source_id", StringType(), nullable=False),
        StructField("properties_json", StringType(), nullable=False),
        StructField("status", StringType(), nullable=False),
        StructField("created_at", TimestampType(), nullable=False),
        StructField("updated_at", TimestampType(), nullable=False),
        StructField("error", StringType(), nullable=False),
    ]
)


def quote_identifier(value: str) -> str:
    if not IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"Invalid Unity Catalog identifier: {value}")
    return f"`{value}`"


qualified_ops_table = (
    f"{quote_identifier(catalog)}.{quote_identifier(schema)}.{quote_identifier(OPS_EVENTS_TABLE)}"
)
qualified_outbox_table = (
    f"{quote_identifier(catalog)}.{quote_identifier(schema)}.{quote_identifier(OPS_OUTBOX_TABLE)}"
)
qualified_manifest_table = (
    f"{quote_identifier(catalog)}.{quote_identifier(schema)}.{quote_identifier(MEDIA_MANIFEST_TABLE)}"
)
qualified_source_files_table = (
    f"{quote_identifier(catalog)}.{quote_identifier(schema)}.{quote_identifier(SOURCE_FILES_TABLE)}"
)
qualified_runs_table = (
    f"{quote_identifier(catalog)}.{quote_identifier(schema)}.{quote_identifier(PROCESSING_RUNS_TABLE)}"
)
qualified_stage_runs_table = (
    f"{quote_identifier(catalog)}.{quote_identifier(schema)}.{quote_identifier(STAGE_RUNS_TABLE)}"
)
qualified_quarantine_table = (
    f"{quote_identifier(catalog)}.{quote_identifier(schema)}.{quote_identifier(QUARANTINE_TABLE)}"
)
qualified_audio_assets_table = (
    f"{quote_identifier(catalog)}.{quote_identifier(schema)}.{quote_identifier(AUDIO_ASSETS_TABLE)}"
)
qualified_audio_chunks_table = (
    f"{quote_identifier(catalog)}.{quote_identifier(schema)}.{quote_identifier(AUDIO_CHUNKS_TABLE)}"
)
qualified_asr_runs_table = (
    f"{quote_identifier(catalog)}.{quote_identifier(schema)}.{quote_identifier(ASR_RUNS_TABLE)}"
)
qualified_transcript_segments_table = (
    f"{quote_identifier(catalog)}.{quote_identifier(schema)}.{quote_identifier(TRANSCRIPT_SEGMENTS_TABLE)}"
)
qualified_frame_assets_table = (
    f"{quote_identifier(catalog)}.{quote_identifier(schema)}.{quote_identifier(FRAME_ASSETS_TABLE)}"
)
qualified_ai_requests_table = (
    f"{quote_identifier(catalog)}.{quote_identifier(schema)}.{quote_identifier(AI_REQUESTS_TABLE)}"
)
qualified_ai_batches_table = (
    f"{quote_identifier(catalog)}.{quote_identifier(schema)}.{quote_identifier(AI_BATCHES_TABLE)}"
)
qualified_ai_results_table = (
    f"{quote_identifier(catalog)}.{quote_identifier(schema)}.{quote_identifier(AI_RESULTS_TABLE)}"
)
qualified_graph_upserts_table = (
    f"{quote_identifier(catalog)}.{quote_identifier(schema)}.{quote_identifier(GRAPH_UPSERTS_TABLE)}"
)


def parse_json_object(raw_value: str, field_name: str) -> dict:
    try:
        parsed = json.loads(raw_value or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"Parameter '{field_name}' must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"Parameter '{field_name}' must be a JSON object")
    return parsed


source_media = parse_json_object(source_media_raw, "source_media")
pipeline_config = parse_json_object(pipeline_config_raw, "pipeline_config")
run_id = dispatch_id
processing_version = str(pipeline_config.get("processing_version") or schema_version)
config_hash = hashlib.sha256(
    json.dumps(pipeline_config, separators=(",", ":"), sort_keys=True).encode("utf-8")
).hexdigest()


def ensure_ops_table() -> None:
    spark.sql(f"USE CATALOG {quote_identifier(catalog)}")
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {quote_identifier(schema)}")
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {qualified_ops_table} (
          event_id STRING,
          schema_version STRING,
          media_id STRING,
          dispatch_id STRING,
          user_id STRING,
          blob_name STRING,
          queue_name STRING,
          stage STRING,
          status STRING,
          message STRING,
          source_uri STRING,
          details STRING,
          event_time TIMESTAMP
        )
        USING DELTA
        """
    )
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {qualified_outbox_table} (
          outbox_id STRING,
          schema_version STRING,
          media_id STRING,
          dispatch_id STRING,
          user_id STRING,
          status STRING,
          progress DOUBLE,
          message STRING,
          processing_result STRING,
          video_metadata STRING,
          error STRING,
          emitted_at TIMESTAMP,
          consumed_at TIMESTAMP
        )
        USING DELTA
        """
    )
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {qualified_manifest_table} (
          media_id STRING,
          dispatch_id STRING,
          schema_version STRING,
          user_id STRING,
          blob_name STRING,
          source_uri STRING,
          source_media STRING,
          pipeline_config STRING,
          config_hash STRING,
          created_at TIMESTAMP,
          updated_at TIMESTAMP
        )
        USING DELTA
        """
    )
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {qualified_source_files_table} (
          media_id STRING,
          dispatch_id STRING,
          source_uri STRING,
          path STRING,
          length BIGINT,
          modification_time STRING,
          validated_at TIMESTAMP
        )
        USING DELTA
        """
    )
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {qualified_runs_table} (
          run_id STRING,
          media_id STRING,
          dispatch_id STRING,
          schema_version STRING,
          processing_version STRING,
          config_hash STRING,
          status STRING,
          progress DOUBLE,
          current_stage STRING,
          started_at TIMESTAMP,
          updated_at TIMESTAMP,
          completed_at TIMESTAMP,
          error STRING
        )
        USING DELTA
        """
    )
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {qualified_stage_runs_table} (
          stage_run_id STRING,
          run_id STRING,
          media_id STRING,
          dispatch_id STRING,
          stage STRING,
          status STRING,
          progress DOUBLE,
          message STRING,
          attempt BIGINT,
          started_at TIMESTAMP,
          completed_at TIMESTAMP,
          metrics STRING,
          error STRING
        )
        USING DELTA
        """
    )
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {qualified_quarantine_table} (
          quarantine_id STRING,
          media_id STRING,
          dispatch_id STRING,
          stage STRING,
          reason STRING,
          error_type STRING,
          details STRING,
          created_at TIMESTAMP
        )
        USING DELTA
        """
    )
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {qualified_audio_assets_table} (
          audio_asset_id STRING,
          media_id STRING,
          dispatch_id STRING,
          source_uri STRING,
          audio_uri STRING,
          format STRING,
          codec STRING,
          sample_rate_hz BIGINT,
          channels BIGINT,
          duration_seconds DOUBLE,
          size_bytes BIGINT,
          sha256 STRING,
          created_at TIMESTAMP,
          updated_at TIMESTAMP
        )
        USING DELTA
        """
    )
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {qualified_audio_chunks_table} (
          chunk_id STRING,
          audio_asset_id STRING,
          media_id STRING,
          dispatch_id STRING,
          chunk_index BIGINT,
          start_ms BIGINT,
          end_ms BIGINT,
          audio_uri STRING,
          duration_seconds DOUBLE,
          created_at TIMESTAMP
        )
        USING DELTA
        """
    )
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {qualified_asr_runs_table} (
          asr_run_id STRING,
          media_id STRING,
          dispatch_id STRING,
          audio_asset_id STRING,
          model_name STRING,
          device STRING,
          compute_type STRING,
          batch_size BIGINT,
          language STRING,
          language_probability DOUBLE,
          duration_seconds DOUBLE,
          segment_count BIGINT,
          transcript_text STRING,
          status STRING,
          started_at TIMESTAMP,
          completed_at TIMESTAMP,
          metrics STRING,
          error STRING
        )
        USING DELTA
        """
    )
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {qualified_transcript_segments_table} (
          segment_id STRING,
          asr_run_id STRING,
          media_id STRING,
          dispatch_id STRING,
          audio_asset_id STRING,
          chunk_id STRING,
          segment_index BIGINT,
          start_ms BIGINT,
          end_ms BIGINT,
          text STRING,
          language STRING,
          confidence DOUBLE,
          created_at TIMESTAMP
        )
        USING DELTA
        """
    )
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {qualified_frame_assets_table} (
          frame_asset_id STRING,
          media_id STRING,
          dispatch_id STRING,
          source_uri STRING,
          frame_uri STRING,
          frame_index BIGINT,
          timestamp_ms BIGINT,
          format STRING,
          width BIGINT,
          height BIGINT,
          size_bytes BIGINT,
          sha256 STRING,
          extraction_method STRING,
          created_at TIMESTAMP,
          updated_at TIMESTAMP
        )
        USING DELTA
        """
    )
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {qualified_ai_requests_table} (
          request_id STRING,
          media_id STRING,
          dispatch_id STRING,
          source_type STRING,
          source_id STRING,
          model_name STRING,
          prompt_version STRING,
          input_uri STRING,
          input_hash STRING,
          request_payload STRING,
          status STRING,
          created_at TIMESTAMP,
          updated_at TIMESTAMP
        )
        USING DELTA
        """
    )
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {qualified_ai_batches_table} (
          batch_id STRING,
          media_id STRING,
          dispatch_id STRING,
          batch_uri STRING,
          request_count BIGINT,
          model_names STRING,
          status STRING,
          provider_batch_id STRING,
          created_at TIMESTAMP,
          updated_at TIMESTAMP,
          submitted_at TIMESTAMP,
          completed_at TIMESTAMP,
          error STRING
        )
        USING DELTA
        """
    )
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {qualified_ai_results_table} (
          result_id STRING,
          request_id STRING,
          batch_id STRING,
          media_id STRING,
          dispatch_id STRING,
          source_type STRING,
          source_id STRING,
          model_name STRING,
          prompt_version STRING,
          status STRING,
          response_json STRING,
          normalized_json STRING,
          tokens_prompt BIGINT,
          tokens_completion BIGINT,
          created_at TIMESTAMP,
          updated_at TIMESTAMP,
          error STRING
        )
        USING DELTA
        """
    )
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {qualified_graph_upserts_table} (
          upsert_id STRING,
          media_id STRING,
          dispatch_id STRING,
          graph_version STRING,
          operation_type STRING,
          label_or_type STRING,
          natural_key STRING,
          source_table STRING,
          source_id STRING,
          properties_json STRING,
          status STRING,
          created_at TIMESTAMP,
          updated_at TIMESTAMP,
          error STRING
        )
        USING DELTA
        """
    )


def json_dumps(value: dict) -> str:
    return json.dumps(value or {}, separators=(",", ":"), sort_keys=True)


def merge_row(table_name: str, row: dict, row_schema: StructType, key_columns: list[str]) -> None:
    temp_view = f"merge_{uuid4().hex}"
    spark.createDataFrame([row], schema=row_schema).createOrReplaceTempView(temp_view)
    on_clause = " AND ".join(f"target.{key} = source.{key}" for key in key_columns)
    update_fields = [
        field.name for field in row_schema if field.name not in {"created_at", "started_at"}
    ]
    update_clause = ", ".join(f"target.{field} = source.{field}" for field in update_fields)
    insert_columns = ", ".join(field.name for field in row_schema)
    insert_values = ", ".join(f"source.{field.name}" for field in row_schema)
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
            "source_media": json_dumps(source_media),
            "pipeline_config": json_dumps(pipeline_config),
            "config_hash": config_hash,
            "created_at": now,
            "updated_at": now,
        },
        MEDIA_MANIFEST_SCHEMA,
        ["media_id", "dispatch_id"],
    )


def register_source_file(source_uri: str, probe: dict) -> None:
    merge_row(
        qualified_source_files_table,
        {
            "media_id": media_id,
            "dispatch_id": dispatch_id,
            "source_uri": source_uri,
            "path": probe["path"],
            "length": int(probe["length"]),
            "modification_time": probe.get("modification_time"),
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


def safe_path_segment(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return normalized.strip("._") or "unknown"


def volume_path(*parts: str) -> str:
    safe_parts = [safe_path_segment(part) for part in parts if part]
    return "/".join([f"/Volumes/{catalog}/{schema}/video_artifacts", *safe_parts])


def ffmpeg_input_path(uri: str) -> str:
    if uri.startswith("/Volumes/"):
        return uri
    if uri.startswith("dbfs:/Volumes/"):
        return uri.replace("dbfs:", "", 1)

    suffix = os.path.splitext(blob_name)[1] or ".mp4"
    local_dir = tempfile.mkdtemp(prefix="qprisma_video_")
    local_path = os.path.join(local_dir, f"{safe_path_segment(media_id)}{suffix}")
    dbutils.fs.cp(uri, f"file:{local_path}")
    return local_path


def run_command(command: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(command, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise RuntimeError(f"Command failed: {' '.join(command)}\n{stderr}") from exc


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
    os.makedirs(audio_dir, exist_ok=True)
    audio_path = f"{audio_dir}/audio_16khz_mono.wav"

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
            audio_path,
        ]
    )

    duration = audio_duration_seconds(audio_path)
    size_bytes = os.path.getsize(audio_path)
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
        "sha256": file_sha256(audio_path),
    }


def register_audio_asset(audio_asset: dict) -> None:
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
    merge_row(
        qualified_audio_chunks_table,
        {
            "chunk_id": f"{audio_asset['audio_asset_id']}:chunk:000",
            "audio_asset_id": audio_asset["audio_asset_id"],
            "media_id": media_id,
            "dispatch_id": dispatch_id,
            "chunk_index": 0,
            "start_ms": 0,
            "end_ms": int(audio_asset["duration_seconds"] * 1000),
            "audio_uri": audio_asset["audio_uri"],
            "duration_seconds": audio_asset["duration_seconds"],
            "created_at": now,
        },
        AUDIO_CHUNKS_SCHEMA,
        ["chunk_id"],
    )


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def faster_whisper_config() -> dict:
    cfg = pipeline_config.get("faster_whisper") or pipeline_config.get("asr") or {}
    if not isinstance(cfg, dict):
        raise ValueError("pipeline_config.faster_whisper/asr must be an object when provided")
    return {
        "model_name": str(cfg.get("model_name") or cfg.get("model_size") or "large-v3"),
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
    inference_started = time.perf_counter()

    for chunk in chunks:
        chunk_offset_seconds = float(chunk["start_ms"]) / 1000
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
            result_segments.append(
                {
                    "segment_index": segment_index,
                    "chunk_id": chunk["chunk_id"],
                    "audio_asset_id": chunk["audio_asset_id"],
                    "start_ms": int(start_seconds * 1000),
                    "end_ms": int(end_seconds * 1000),
                    "text": text,
                    "language": detected_language,
                    "confidence": None,
                }
            )
            text_parts.append(text)
            segment_index += 1

    elapsed = time.perf_counter() - inference_started
    return {
        "text": " ".join(text_parts),
        "segments": result_segments,
        "language": detected_language,
        "language_probability": detected_language_probability,
        "duration_seconds": sum(float(chunk["duration_seconds"] or 0) for chunk in chunks),
        "elapsed_seconds": elapsed,
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


def frame_extraction_config() -> dict:
    cfg = pipeline_config.get("frames") or pipeline_config.get("frame_extraction") or {}
    if not isinstance(cfg, dict):
        raise ValueError("pipeline_config.frames/frame_extraction must be an object when provided")
    return {
        "method": str(cfg.get("method") or "uniform"),
        "max_frames": int(cfg.get("max_frames") or pipeline_config.get("max_frames") or 20),
        "interval_seconds": cfg.get("interval_seconds") or pipeline_config.get("frame_interval"),
        "format": str(cfg.get("format") or "jpg"),
        "quality": int(cfg.get("quality") or 2),
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


def extract_frame_assets(source_uri: str) -> list[dict]:
    input_path = ffmpeg_input_path(source_uri)
    config = frame_extraction_config()
    metadata = ffprobe_video_metadata(input_path)
    timestamps = frame_timestamps(metadata, config)
    frame_format = config["format"].lower()
    if frame_format not in {"jpg", "jpeg", "png", "webp"}:
        raise ValueError("Frame format must be one of: jpg, jpeg, png, webp")

    frame_dir = volume_path(media_id, dispatch_id, "frames")
    os.makedirs(frame_dir, exist_ok=True)
    frames: list[dict] = []
    extension = "jpg" if frame_format == "jpeg" else frame_format

    for index, timestamp_seconds in enumerate(timestamps):
        timestamp_ms = int(timestamp_seconds * 1000)
        frame_path = f"{frame_dir}/frame_{index:06d}_{timestamp_ms:012d}.{extension}"
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
        command.append(frame_path)
        run_command(command)
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
                "size_bytes": os.path.getsize(frame_path),
                "sha256": file_sha256(frame_path),
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


def pipeline_models_config() -> dict:
    models = pipeline_config.get("models") or {}
    if not isinstance(models, dict):
        raise ValueError("pipeline_config.models must be an object when provided")
    return {
        "vision": str(models.get("vision") or pipeline_config.get("vision_model") or "gpt-4o"),
        "summary": str(models.get("summary") or pipeline_config.get("summary_model") or "gpt-4o"),
        "prompt_version": str(pipeline_config.get("prompt_version") or schema_version),
    }


def stable_hash(value: dict) -> str:
    return hashlib.sha256(json_dumps(value).encode("utf-8")).hexdigest()


def load_frame_assets() -> list[dict]:
    rows = spark.sql(
        f"""
        SELECT
          frame_asset_id,
          frame_uri,
          frame_index,
          timestamp_ms,
          format,
          width,
          height,
          sha256
        FROM {qualified_frame_assets_table}
        WHERE media_id = {sql_literal(media_id)}
          AND dispatch_id = {sql_literal(dispatch_id)}
        ORDER BY frame_index
        """
    ).collect()
    if not rows:
        raise ValueError(
            f"No frame assets found for media_id={media_id}, dispatch_id={dispatch_id}. "
            "Run extract_frame_assets first."
        )
    return [row.asDict() for row in rows]


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


def build_inference_request_rows() -> list[dict]:
    frames = load_frame_assets()
    asr_run = load_completed_asr_run()
    models = pipeline_models_config()
    now = datetime.now(UTC)
    custom_prompt = pipeline_config.get("custom_prompt")
    requests: list[dict] = []

    for frame in frames:
        payload = {
            "request_type": "frame_understanding",
            "schema_version": "frame_understanding_v1",
            "media_id": media_id,
            "dispatch_id": dispatch_id,
            "frame_uri": frame["frame_uri"],
            "timestamp_ms": int(frame["timestamp_ms"]),
            "custom_prompt": custom_prompt,
        }
        input_hash = stable_hash(
            {
                "frame_sha256": frame["sha256"],
                "prompt_version": models["prompt_version"],
                "model_name": models["vision"],
                "custom_prompt": custom_prompt,
            }
        )
        requests.append(
            {
                "request_id": f"{media_id}:ai:frame:{frame['frame_index']:06d}:{input_hash[:12]}",
                "media_id": media_id,
                "dispatch_id": dispatch_id,
                "source_type": "frame",
                "source_id": frame["frame_asset_id"],
                "model_name": models["vision"],
                "prompt_version": models["prompt_version"],
                "input_uri": frame["frame_uri"],
                "input_hash": input_hash,
                "request_payload": json_dumps(payload),
                "status": "pending",
                "created_at": now,
                "updated_at": now,
            }
        )

    if asr_run and asr_run.get("transcript_text"):
        payload = {
            "request_type": "transcript_semantics",
            "schema_version": "transcript_semantics_v1",
            "media_id": media_id,
            "dispatch_id": dispatch_id,
            "asr_run_id": asr_run["asr_run_id"],
            "language": asr_run.get("language"),
            "segment_count": asr_run.get("segment_count"),
            "transcript_text": asr_run["transcript_text"],
            "custom_prompt": custom_prompt,
        }
        input_hash = stable_hash(
            {
                "asr_run_id": asr_run["asr_run_id"],
                "transcript_text": asr_run["transcript_text"],
                "prompt_version": models["prompt_version"],
                "model_name": models["summary"],
                "custom_prompt": custom_prompt,
            }
        )
        requests.append(
            {
                "request_id": f"{media_id}:ai:transcript:{input_hash[:12]}",
                "media_id": media_id,
                "dispatch_id": dispatch_id,
                "source_type": "transcript",
                "source_id": asr_run["asr_run_id"],
                "model_name": models["summary"],
                "prompt_version": models["prompt_version"],
                "input_uri": None,
                "input_hash": input_hash,
                "request_payload": json_dumps(payload),
                "status": "pending",
                "created_at": now,
                "updated_at": now,
            }
        )

    return requests


def register_ai_requests(requests: list[dict]) -> None:
    existing_by_id = {request["request_id"]: request for request in load_ai_requests()}
    for request in requests:
        existing = existing_by_id.get(request["request_id"])
        if existing and existing["status"] != "pending":
            continue
        merge_row(
            qualified_ai_requests_table,
            request,
            AI_REQUESTS_SCHEMA,
            ["request_id"],
        )


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


def load_ai_requests() -> list[dict]:
    rows = spark.sql(
        f"""
        SELECT
          request_id,
          media_id,
          dispatch_id,
          source_type,
          source_id,
          model_name,
          prompt_version,
          input_uri,
          input_hash,
          request_payload,
          status,
          created_at,
          updated_at
        FROM {qualified_ai_requests_table}
        WHERE media_id = {sql_literal(media_id)}
          AND dispatch_id = {sql_literal(dispatch_id)}
        ORDER BY source_type, source_id
        """
    ).collect()
    return [row.asDict() for row in rows]


def load_existing_ai_batches() -> list[dict]:
    rows = spark.sql(
        f"""
        SELECT
          batch_id,
          media_id,
          dispatch_id,
          batch_uri,
          request_count,
          model_names,
          status,
          provider_batch_id,
          created_at,
          updated_at,
          submitted_at,
          completed_at,
          error
        FROM {qualified_ai_batches_table}
        WHERE media_id = {sql_literal(media_id)}
          AND dispatch_id = {sql_literal(dispatch_id)}
          AND status IN ('ready_for_submission', 'submitted', 'completed')
        ORDER BY updated_at DESC
        """
    ).collect()
    return [row.asDict() for row in rows]


def image_media_type(uri: str) -> str:
    extension = uri.rsplit(".", 1)[-1].lower() if "." in uri else ""
    return {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
    }.get(extension, "image/jpeg")


def json_mode_prompt(prompt: str) -> str:
    return (
        f"{prompt}\n\n"
        "Return only a valid JSON object. Do not include markdown fences or explanatory text."
    )


def read_batch_request_ids(batch_uri: str) -> set[str]:
    request_ids: set[str] = set()
    with open(batch_uri, encoding="utf-8") as batch_file:
        for line in batch_file:
            if line.strip():
                request_ids.add(json.loads(line)["custom_id"])
    return request_ids


def mark_ai_requests_batched(requests: list[dict], now: datetime) -> None:
    for request in requests:
        updated_request = {
            **request,
            "status": "batched",
            "updated_at": now,
        }
        merge_row(
            qualified_ai_requests_table,
            updated_request,
            AI_REQUESTS_SCHEMA,
            ["request_id"],
        )


def batch_request_body(request: dict) -> dict:
    payload = json.loads(request["request_payload"] or "{}")
    request_type = payload.get("request_type")
    custom_prompt = payload.get("custom_prompt")
    if request_type == "frame_understanding":
        if not request.get("input_uri"):
            raise ValueError(f"Frame request {request['request_id']} is missing input_uri")
        with open(request["input_uri"], "rb") as frame_file:
            image_base64 = base64.b64encode(frame_file.read()).decode("ascii")
        media_type = image_media_type(payload.get("frame_uri") or request["input_uri"])
        text_prompt = json_mode_prompt(
            custom_prompt
            or (
                "Describe the visual content of this video frame as JSON. Include visible "
                "objects, people, text, actions, setting and any temporal cues useful for "
                "video search."
            )
        )
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text_prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{image_base64}"},
                    },
                ],
            }
        ]
    elif request_type == "transcript_semantics":
        text_prompt = json_mode_prompt(
            custom_prompt
            or (
                "Extract concise topics, entities, relationships and timeline cues from this "
                "video transcript. Return structured JSON."
            )
        )
        messages = [
            {
                "role": "user",
                "content": (
                    f"{text_prompt}\n\nTranscript:\n{payload.get('transcript_text', '')}"
                ),
            }
        ]
    else:
        raise ValueError(f"Unsupported AI request_type for {request['request_id']}: {request_type}")

    return {
        "model": request["model_name"],
        "messages": messages,
        "response_format": {"type": "json_object"},
    }


def openai_batch_line(request: dict) -> dict:
    return {
        "custom_id": request["request_id"],
        "method": "POST",
        "url": "/chat/completions",
        "body": batch_request_body(request),
    }


def stage_ai_batch_payloads() -> dict:
    all_requests = load_ai_requests()
    pending_requests = [request for request in all_requests if request["status"] == "pending"]
    existing_batches = load_existing_ai_batches()
    now = datetime.now(UTC)
    if not pending_requests and existing_batches:
        latest_batch = existing_batches[0]
        return {
            "batch_id": latest_batch["batch_id"],
            "batch_uri": latest_batch["batch_uri"],
            "request_count": latest_batch["request_count"],
            "model_names": json.loads(latest_batch["model_names"] or "{}").get("models", []),
            "status": latest_batch["status"],
            "reused": True,
            "reconciled_request_count": 0,
        }

    for existing_batch in existing_batches:
        batch_request_ids = read_batch_request_ids(existing_batch["batch_uri"])
        pending_in_batch = [
            request for request in pending_requests if request["request_id"] in batch_request_ids
        ]
        if not pending_requests or len(pending_in_batch) == len(pending_requests):
            mark_ai_requests_batched(pending_in_batch, now)
            return {
                "batch_id": existing_batch["batch_id"],
                "batch_uri": existing_batch["batch_uri"],
                "request_count": existing_batch["request_count"],
                "model_names": json.loads(existing_batch["model_names"] or "{}").get("models", []),
                "status": existing_batch["status"],
                "reused": True,
                "reconciled_request_count": len(pending_in_batch),
            }

    if not pending_requests:
        raise ValueError("No pending AI requests found. Run build_multimodal_inference_requests first.")

    batch_hash = stable_hash(
        {
            "request_ids": [request["request_id"] for request in pending_requests],
            "config_hash": config_hash,
            "schema_version": schema_version,
        }
    )
    batch_id = f"{media_id}:ai_batch:{batch_hash[:12]}"
    batch_dir = volume_path(media_id, dispatch_id, "ai_batches", batch_id)
    os.makedirs(batch_dir, exist_ok=True)
    batch_uri = f"{batch_dir}/requests.jsonl"
    with open(batch_uri, "w", encoding="utf-8") as batch_file:
        for request in pending_requests:
            batch_file.write(json.dumps(openai_batch_line(request), separators=(",", ":")) + "\n")

    model_names = sorted({request["model_name"] for request in pending_requests})
    merge_row(
        qualified_ai_batches_table,
        {
            "batch_id": batch_id,
            "media_id": media_id,
            "dispatch_id": dispatch_id,
            "batch_uri": batch_uri,
            "request_count": len(pending_requests),
            "model_names": json_dumps({"models": model_names}),
            "status": "ready_for_submission",
            "provider_batch_id": None,
            "created_at": now,
            "updated_at": now,
            "submitted_at": None,
            "completed_at": None,
            "error": json_dumps({}),
        },
        AI_BATCHES_SCHEMA,
        ["batch_id"],
    )
    mark_ai_requests_batched(pending_requests, now)
    return {
        "batch_id": batch_id,
        "batch_uri": batch_uri,
        "request_count": len(pending_requests),
        "model_names": model_names,
        "status": "ready_for_submission",
        "reused": False,
        "size_bytes": os.path.getsize(batch_uri),
    }


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


def build_graph_upsert_rows() -> list[dict]:
    frames = load_frame_assets()
    transcript_segments = load_transcript_segments()
    ai_requests = load_ai_requests()
    asr_run = load_completed_asr_run()
    graph_version = str(pipeline_config.get("graph_version") or schema_version)
    rows: list[dict] = [
        graph_upsert_row(
            operation_type="node",
            label_or_type="Video",
            natural_key=media_id,
            source_table=MEDIA_MANIFEST_TABLE,
            source_id=media_id,
            properties={
                "media_id": media_id,
                "dispatch_id": dispatch_id,
                "blob_name": blob_name,
                "user_id": user_id,
                "processing_version": processing_version,
                "config_hash": config_hash,
                "graph_version": graph_version,
            },
        )
    ]

    if asr_run:
        rows.append(
            graph_upsert_row(
                operation_type="node",
                label_or_type="AsrRun",
                natural_key=asr_run["asr_run_id"],
                source_table=ASR_RUNS_TABLE,
                source_id=asr_run["asr_run_id"],
                properties={
                    "asr_run_id": asr_run["asr_run_id"],
                    "audio_asset_id": asr_run["audio_asset_id"],
                    "model_name": asr_run["model_name"],
                    "language": asr_run.get("language"),
                    "duration_seconds": asr_run.get("duration_seconds"),
                    "segment_count": asr_run.get("segment_count"),
                },
            )
        )
        rows.append(
            graph_upsert_row(
                operation_type="relationship",
                label_or_type="HAS_ASR_RUN",
                natural_key=f"{media_id}->HAS_ASR_RUN->{asr_run['asr_run_id']}",
                source_table=ASR_RUNS_TABLE,
                source_id=asr_run["asr_run_id"],
                properties={
                    "from_label": "Video",
                    "from_key": media_id,
                    "to_label": "AsrRun",
                    "to_key": asr_run["asr_run_id"],
                },
            )
        )

    for frame in frames:
        rows.append(
            graph_upsert_row(
                operation_type="node",
                label_or_type="Frame",
                natural_key=frame["frame_asset_id"],
                source_table=FRAME_ASSETS_TABLE,
                source_id=frame["frame_asset_id"],
                properties={
                    "frame_asset_id": frame["frame_asset_id"],
                    "frame_uri": frame["frame_uri"],
                    "frame_index": frame["frame_index"],
                    "timestamp_ms": frame["timestamp_ms"],
                    "format": frame["format"],
                    "width": frame.get("width"),
                    "height": frame.get("height"),
                },
            )
        )
        rows.append(
            graph_upsert_row(
                operation_type="relationship",
                label_or_type="HAS_FRAME",
                natural_key=f"{media_id}->HAS_FRAME->{frame['frame_asset_id']}",
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
                label_or_type="TranscriptSegment",
                natural_key=segment["segment_id"],
                source_table=TRANSCRIPT_SEGMENTS_TABLE,
                source_id=segment["segment_id"],
                properties={
                    "segment_id": segment["segment_id"],
                    "asr_run_id": segment["asr_run_id"],
                    "chunk_id": segment["chunk_id"],
                    "segment_index": segment["segment_index"],
                    "start_ms": segment["start_ms"],
                    "end_ms": segment["end_ms"],
                    "text": segment["text"],
                    "language": segment.get("language"),
                },
            )
        )
        rows.append(
            graph_upsert_row(
                operation_type="relationship",
                label_or_type="HAS_TRANSCRIPT_SEGMENT",
                natural_key=f"{media_id}->HAS_TRANSCRIPT_SEGMENT->{segment['segment_id']}",
                source_table=TRANSCRIPT_SEGMENTS_TABLE,
                source_id=segment["segment_id"],
                properties={
                    "from_label": "Video",
                    "from_key": media_id,
                    "to_label": "TranscriptSegment",
                    "to_key": segment["segment_id"],
                    "start_ms": segment["start_ms"],
                    "end_ms": segment["end_ms"],
                },
            )
        )

    for request in ai_requests:
        rows.append(
            graph_upsert_row(
                operation_type="node",
                label_or_type="AiRequest",
                natural_key=request["request_id"],
                source_table=AI_REQUESTS_TABLE,
                source_id=request["request_id"],
                properties={
                    "request_id": request["request_id"],
                    "source_type": request["source_type"],
                    "source_id": request["source_id"],
                    "model_name": request["model_name"],
                    "prompt_version": request["prompt_version"],
                    "status": request["status"],
                },
            )
        )

    return rows


def register_graph_upserts(upserts: list[dict]) -> None:
    for upsert in upserts:
        merge_row(
            qualified_graph_upserts_table,
            upsert,
            GRAPH_UPSERTS_SCHEMA,
            ["upsert_id"],
        )


def complete_observable_stage(
    *,
    stage_name: str,
    message: str,
    metrics: dict | None = None,
    event_status: str = "completed",
) -> None:
    upsert_processing_run(
        status="running",
        progress=progress_for_stage(stage_name),
        current_stage=stage_name,
    )
    write_stage_run(stage_name=stage_name, status="running", message=STAGE_MESSAGES[stage_name])
    write_progress_outbox(stage_name, STAGE_MESSAGES[stage_name])
    write_event(status=event_status, message=message, details=metrics or {})
    write_stage_run(
        stage_name=stage_name,
        status="completed",
        message=message,
        metrics=metrics or {},
        completed=True,
    )


def validate_volume_path(path: str, field_name: str) -> str:
    normalized = path.strip()
    if normalized.startswith(("dbfs:/Volumes/", "/Volumes/")):
        return normalized
    raise ValueError(f"source_media.{field_name} must be a Unity Catalog volume path")


def validate_cloud_uri(uri: str, field_name: str) -> str:
    normalized = uri.strip()
    if normalized.startswith(("abfss://", "wasbs://")):
        return normalized
    if normalized.startswith(("dbfs:/Volumes/", "/Volumes/")):
        return normalized
    raise ValueError(
        f"source_media.{field_name} must be an abfss:// URI, wasbs:// URI, or Unity Catalog volume path"
    )


def source_media_uri() -> str:
    volume_path = source_media.get("volume_path")
    if volume_path:
        return validate_volume_path(str(volume_path), "volume_path")

    explicit_uri = source_media.get("uri")
    if explicit_uri:
        return validate_cloud_uri(str(explicit_uri), "uri")

    for field_name in ("abfss_uri", "wasbs_uri"):
        explicit_storage_uri = source_media.get(field_name)
        if explicit_storage_uri:
            return validate_cloud_uri(str(explicit_storage_uri), field_name)

    container = str(source_media.get("container_name") or source_media.get("container") or "")
    blob = str(source_media.get("blob_name") or blob_name)
    storage_account_url = str(source_media.get("storage_account_url") or "")
    if not container or not blob or not storage_account_url:
        raise ValueError(
            "source_media must include volume_path, uri, or container_name, blob_name and storage_account_url"
        )

    host = urlparse(storage_account_url).hostname or ""
    account_name = host.split(".")[0]
    if not account_name:
        raise ValueError("source_media.storage_account_url must include a storage account host")

    normalized_blob = blob.lstrip("/")
    if ".dfs." in host:
        return f"abfss://{container}@{account_name}.dfs.core.windows.net/{normalized_blob}"
    return f"wasbs://{container}@{account_name}.blob.core.windows.net/{normalized_blob}"


def validate_source_contract() -> None:
    auth = source_media.get("auth")
    if not isinstance(auth, dict) or auth.get("mode") != "managed_identity":
        raise ValueError("source_media.auth.mode must be 'managed_identity'")


def probe_source_media(uri: str) -> dict:
    rows = (
        spark.read.format("binaryFile")
        .load(uri)
        .select("path", "length", "modificationTime")
        .limit(1)
        .collect()
    )
    if not rows:
        raise FileNotFoundError(f"No readable source media found at {uri}")
    row = rows[0].asDict()
    return {
        "path": row["path"],
        "length": int(row["length"]),
        "modification_time": row["modificationTime"].isoformat(),
    }

# COMMAND ----------

ensure_ops_table()

try:
    if stage == "register_manifest":
        stage_message = STAGE_MESSAGES[stage]
        upsert_processing_run(
            status="running",
            progress=progress_for_stage(stage),
            current_stage=stage,
        )
        write_stage_run(stage_name=stage, status="running", message=stage_message)
        write_progress_outbox(stage, stage_message)
        validate_source_contract()
        register_manifest()
        write_event(
            status="running",
            message="Manifest registered",
            details={
                "pipeline_config": pipeline_config,
                "source_media": source_media,
                "config_hash": config_hash,
                "processing_version": processing_version,
            },
        )
        write_stage_run(
            stage_name=stage,
            status="completed",
            message="Manifest registered",
            completed=True,
        )
    elif stage == "validate_and_probe_media":
        stage_message = STAGE_MESSAGES[stage]
        upsert_processing_run(
            status="running",
            progress=progress_for_stage(stage),
            current_stage=stage,
        )
        write_stage_run(stage_name=stage, status="running", message=stage_message)
        write_progress_outbox(stage, stage_message)
        validate_source_contract()
        uri = source_media_uri()
        probe = probe_source_media(uri)
        register_manifest(source_uri=uri)
        register_source_file(uri, probe)
        write_event(
            status="source_validated",
            message="Source media is readable by Databricks",
            source_uri=uri,
            details={"probe": probe},
        )
        write_stage_run(
            stage_name=stage,
            status="completed",
            message="Source media is readable by Databricks",
            metrics={"bytes": probe["length"], "path": probe["path"]},
            completed=True,
        )
    elif stage == "extract_audio_assets":
        stage_message = "Extracting 16kHz mono audio asset with FFmpeg"
        upsert_processing_run(
            status="running",
            progress=progress_for_stage(stage),
            current_stage=stage,
        )
        write_stage_run(stage_name=stage, status="running", message=stage_message)
        write_progress_outbox(stage, stage_message)
        validate_source_contract()
        uri = source_media_uri()
        audio_asset = extract_audio_asset(uri)
        register_audio_asset(audio_asset)
        write_event(
            status="audio_extracted",
            message="Audio asset extracted for faster-whisper",
            source_uri=uri,
            details={
                "audio_asset_id": audio_asset["audio_asset_id"],
                "audio_uri": audio_asset["audio_uri"],
                "duration_seconds": audio_asset["duration_seconds"],
                "size_bytes": audio_asset["size_bytes"],
                "sample_rate_hz": audio_asset["sample_rate_hz"],
                "channels": audio_asset["channels"],
            },
        )
        write_stage_run(
            stage_name=stage,
            status="completed",
            message="Audio asset extracted for faster-whisper",
            metrics={
                "audio_asset_id": audio_asset["audio_asset_id"],
                "duration_seconds": audio_asset["duration_seconds"],
                "size_bytes": audio_asset["size_bytes"],
                "audio_uri": audio_asset["audio_uri"],
            },
            completed=True,
        )
    elif stage == "extract_frame_assets":
        stage_message = "Extracting representative frames with FFmpeg"
        upsert_processing_run(
            status="running",
            progress=progress_for_stage(stage),
            current_stage=stage,
        )
        write_stage_run(stage_name=stage, status="running", message=stage_message)
        write_progress_outbox(stage, stage_message)
        validate_source_contract()
        uri = source_media_uri()
        frame_assets = extract_frame_assets(uri)
        register_frame_assets(frame_assets)
        write_event(
            status="frames_extracted",
            message="Frame assets extracted for multimodal inference",
            source_uri=uri,
            details={
                "frame_count": len(frame_assets),
                "first_timestamp_ms": frame_assets[0]["timestamp_ms"] if frame_assets else None,
                "last_timestamp_ms": frame_assets[-1]["timestamp_ms"] if frame_assets else None,
                "frame_table": FRAME_ASSETS_TABLE,
            },
        )
        write_stage_run(
            stage_name=stage,
            status="completed",
            message="Frame assets extracted for multimodal inference",
            metrics={
                "frame_count": len(frame_assets),
                "frame_table": FRAME_ASSETS_TABLE,
                "total_size_bytes": sum(frame["size_bytes"] for frame in frame_assets),
            },
            completed=True,
        )
    elif stage == "run_faster_whisper_asr":
        stage_message = "Transcribing audio chunks with faster-whisper"
        upsert_processing_run(
            status="running",
            progress=progress_for_stage(stage),
            current_stage=stage,
        )
        write_stage_run(stage_name=stage, status="running", message=stage_message)
        write_progress_outbox(stage, stage_message)
        chunks = load_audio_chunks()
        model_config = faster_whisper_config()
        audio_asset_id = chunks[0]["audio_asset_id"]
        asr_run_id = f"{media_id}:asr:{model_config['model_name']}:{config_hash[:12]}"
        asr_started_at = datetime.now(UTC)
        write_asr_run(
            asr_run_id=asr_run_id,
            audio_asset_id=audio_asset_id,
            model_config=model_config,
            status="running",
            started_at=asr_started_at,
            metrics={"chunk_count": len(chunks)},
        )
        transcript = transcribe_audio_chunks(chunks, model_config)
        write_transcript_segments(asr_run_id, transcript["segments"])
        write_asr_run(
            asr_run_id=asr_run_id,
            audio_asset_id=audio_asset_id,
            model_config=model_config,
            status="completed",
            transcript_text=transcript["text"],
            language=transcript["language"],
            language_probability=transcript["language_probability"],
            duration_seconds=transcript["duration_seconds"],
            segment_count=len(transcript["segments"]),
            started_at=asr_started_at,
            completed=True,
            metrics={
                "chunk_count": len(chunks),
                "elapsed_seconds": transcript["elapsed_seconds"],
                "azure_openai_whisper": "disabled_for_primary_path",
            },
        )
        write_event(
            status="asr_completed",
            message="faster-whisper ASR completed",
            details={
                "asr_run_id": asr_run_id,
                "audio_asset_id": audio_asset_id,
                "model_name": model_config["model_name"],
                "segment_count": len(transcript["segments"]),
                "language": transcript["language"],
                "duration_seconds": transcript["duration_seconds"],
            },
        )
        write_stage_run(
            stage_name=stage,
            status="completed",
            message="faster-whisper ASR completed",
            metrics={
                "asr_run_id": asr_run_id,
                "audio_asset_id": audio_asset_id,
                "model_name": model_config["model_name"],
                "segment_count": len(transcript["segments"]),
                "elapsed_seconds": transcript["elapsed_seconds"],
            },
            completed=True,
        )
    elif stage == "build_multimodal_inference_requests":
        stage_message = "Building table-driven multimodal inference requests"
        upsert_processing_run(
            status="running",
            progress=progress_for_stage(stage),
            current_stage=stage,
        )
        write_stage_run(stage_name=stage, status="running", message=stage_message)
        write_progress_outbox(stage, stage_message)
        ai_requests = build_inference_request_rows()
        register_ai_requests(ai_requests)
        request_counts: dict[str, int] = {}
        for request in ai_requests:
            request_counts[request["source_type"]] = request_counts.get(request["source_type"], 0) + 1
        write_event(
            status="inference_requests_built",
            message="Multimodal inference requests registered",
            details={
                "request_count": len(ai_requests),
                "request_counts": request_counts,
                "request_table": AI_REQUESTS_TABLE,
            },
        )
        write_stage_run(
            stage_name=stage,
            status="completed",
            message="Multimodal inference requests registered",
            metrics={
                "request_count": len(ai_requests),
                "request_counts": request_counts,
                "request_table": AI_REQUESTS_TABLE,
                "implementation_status": "request_generation_only",
                "next": "Submit pending requests through Azure OpenAI Batch and persist responses",
            },
            completed=True,
        )
    elif stage == "stage_ai_batch_payloads":
        stage_message = "Staging Azure OpenAI Batch JSONL payloads"
        upsert_processing_run(
            status="running",
            progress=progress_for_stage(stage),
            current_stage=stage,
        )
        write_stage_run(stage_name=stage, status="running", message=stage_message)
        write_progress_outbox(stage, stage_message)
        batch = stage_ai_batch_payloads()
        write_event(
            status="ai_batch_payloads_staged",
            message="Azure OpenAI Batch payloads staged",
            details=batch,
        )
        write_stage_run(
            stage_name=stage,
            status="completed",
            message="Azure OpenAI Batch payloads staged",
            metrics={
                **batch,
                "ai_batches_table": AI_BATCHES_TABLE,
                "ai_results_table": AI_RESULTS_TABLE,
                "next": "Submit ready_for_submission batches to Azure OpenAI Batch",
            },
            completed=True,
        )
    elif stage == "build_graph_upserts":
        stage_message = "Building Neo4j graph upsert intents from Delta records"
        upsert_processing_run(
            status="running",
            progress=progress_for_stage(stage),
            current_stage=stage,
        )
        write_stage_run(stage_name=stage, status="running", message=stage_message)
        write_progress_outbox(stage, stage_message)
        graph_upserts = build_graph_upsert_rows()
        register_graph_upserts(graph_upserts)
        operation_counts: dict[str, int] = {}
        label_counts: dict[str, int] = {}
        for upsert in graph_upserts:
            operation_counts[upsert["operation_type"]] = (
                operation_counts.get(upsert["operation_type"], 0) + 1
            )
            label_counts[upsert["label_or_type"]] = label_counts.get(upsert["label_or_type"], 0) + 1
        write_event(
            status="graph_upserts_built",
            message="Neo4j graph upsert intents registered",
            details={
                "upsert_count": len(graph_upserts),
                "operation_counts": operation_counts,
                "label_counts": label_counts,
                "graph_upserts_table": GRAPH_UPSERTS_TABLE,
            },
        )
        write_stage_run(
            stage_name=stage,
            status="completed",
            message="Neo4j graph upsert intents registered",
            metrics={
                "upsert_count": len(graph_upserts),
                "operation_counts": operation_counts,
                "label_counts": label_counts,
                "graph_upserts_table": GRAPH_UPSERTS_TABLE,
                "next": "Apply pending graph upserts with a dedicated Neo4j projector",
            },
            completed=True,
        )
    elif stage == "publish_outbox":
        stage_message = STAGE_MESSAGES[stage]
        upsert_processing_run(
            status="running",
            progress=progress_for_stage(stage),
            current_stage=stage,
        )
        write_stage_run(stage_name=stage, status="running", message=stage_message)
        processing_result = {
            "backend": "databricks",
            "pipeline": "lakehouse_pilot",
            "dispatch_id": dispatch_id,
            "processing_version": processing_version,
            "config_hash": config_hash,
            "stages": PIPELINE_STAGES,
            "delta_tables": {
                "manifest": MEDIA_MANIFEST_TABLE,
                "source_files": SOURCE_FILES_TABLE,
                "processing_runs": PROCESSING_RUNS_TABLE,
                "stage_runs": STAGE_RUNS_TABLE,
                "audio_assets": AUDIO_ASSETS_TABLE,
                "audio_chunks": AUDIO_CHUNKS_TABLE,
                "asr_runs": ASR_RUNS_TABLE,
                "transcript_segments": TRANSCRIPT_SEGMENTS_TABLE,
                "frame_assets": FRAME_ASSETS_TABLE,
                "ai_requests": AI_REQUESTS_TABLE,
                "ai_batches": AI_BATCHES_TABLE,
                "ai_results": AI_RESULTS_TABLE,
                "graph_upserts": GRAPH_UPSERTS_TABLE,
                "events": OPS_EVENTS_TABLE,
                "outbox": OPS_OUTBOX_TABLE,
                "quarantine": QUARANTINE_TABLE,
            },
            "next": [
                "implement_audio_chunking",
                "implement_multimodal_batch_submission",
                "implement_ai_result_normalization",
                "implement_neo4j_graph_projector",
            ],
        }
        write_event(
            status="completed",
            message="Databricks lakehouse pilot job completed",
            details={
                "processing_result": processing_result,
            },
        )
        write_stage_run(
            stage_name=stage,
            status="completed",
            message="Databricks lakehouse pilot job completed",
            completed=True,
        )
        upsert_processing_run(
            status="completed",
            progress=1.0,
            current_stage=stage,
            completed=True,
        )
        write_outbox_event(
            status="completed",
            progress=1.0,
            message="Databricks lakehouse pilot job completed",
            processing_result=processing_result,
        )
    else:
        raise ValueError(f"Unsupported pipeline stage: {stage}")
except Exception as exc:
    write_quarantine(stage_name=stage, reason="stage_failed", exc=exc)
    write_stage_run(
        stage_name=stage,
        status="failed",
        message=str(exc),
        error={"error_type": type(exc).__name__, "message": str(exc)},
        completed=True,
    )
    upsert_processing_run(
        status="failed",
        progress=progress_for_stage(stage),
        current_stage=stage,
        error={"error_type": type(exc).__name__, "message": str(exc)},
        completed=True,
    )
    write_event(
        status="failed",
        message=str(exc),
        details={"error_type": type(exc).__name__},
    )
    write_outbox_event(
        status="failed",
        progress=0.0,
        message="Databricks video pipeline failed",
        error={"error_type": type(exc).__name__, "message": str(exc)},
    )
    raise

print(
    json.dumps(
        {
            "event": "qprisma_video_pipeline_stage_completed",
            "catalog": catalog,
            "schema": schema,
            "ops_table": qualified_ops_table,
            "stage": stage,
            "media_id": media_id,
            "dispatch_id": dispatch_id,
            "timestamp": datetime.now(UTC).isoformat(),
        },
        sort_keys=True,
    )
)
