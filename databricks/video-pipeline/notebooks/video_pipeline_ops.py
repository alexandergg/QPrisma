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
import urllib.error
import urllib.request
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
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
SERVING_ENDPOINT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
ALLOWED_FLORENCE_MODELS = {"microsoft/Florence-2-large-ft"}
ALLOWED_SECRET_REFERENCE_KEYS = {
    "api_key_env",
    "api_key_secret_key",
    "api_key_secret_scope",
}
SENSITIVE_CONFIG_KEYS = {
    "access_token",
    "accesskey",
    "account_key",
    "api_key",
    "apikey",
    "client_secret",
    "clientsecret",
    "connection_string",
    "connectionstring",
    "id_token",
    "password",
    "refresh_token",
    "sas_token",
    "secret",
    "storage_account_key",
    "token",
}
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
FRAME_ANALYSIS_TABLE = "video_frame_analysis"
TEMPORAL_WINDOWS_TABLE = "video_temporal_windows"
SCENE_CANDIDATES_TABLE = "video_scene_candidates"
SCENE_VISUAL_ANALYSIS_TABLE = "video_scene_visual_analysis"
MODEL_INFERENCE_RUNS_TABLE = "video_model_inference_runs"
AI_REQUESTS_TABLE = "video_ai_requests"
AI_BATCHES_TABLE = "video_ai_batches"
AI_RESULTS_TABLE = "video_ai_results"
GOLD_PROCESSING_RESULTS_TABLE = "video_processing_results"
GRAPH_UPSERTS_TABLE = "video_graph_upserts"

STAGE_PROGRESS = {
    "register_manifest": 0.10,
    "validate_and_probe_media": 0.20,
    "extract_audio_assets": 0.30,
    "extract_frame_assets": 0.40,
    "run_florence_frame_analysis": 0.50,
    "run_faster_whisper_asr": 0.55,
    "detect_scenes_and_windows": 0.62,
    "run_databricks_scene_reasoning": 0.76,
    "build_gold_processing_result": 0.86,
    "build_graph_upserts": 0.92,
    "project_neo4j_graph": 0.96,
    "publish_outbox": 1.00,
}
STAGE_MESSAGES = {
    "register_manifest": "Registering video manifest in Databricks",
    "validate_and_probe_media": "Validating staged source media in Databricks",
    "extract_audio_assets": "Extracting audio assets with FFmpeg",
    "extract_frame_assets": "Preparing frame extraction assets",
    "run_florence_frame_analysis": "Analyzing frames with Florence-2 in Databricks",
    "run_faster_whisper_asr": "Preparing faster-whisper transcription",
    "detect_scenes_and_windows": "Detecting temporal windows and scene candidates",
    "run_databricks_scene_reasoning": "Reasoning over scenes with Databricks Gemma 3",
    "build_gold_processing_result": "Building frontend-compatible Gold result",
    "build_graph_upserts": "Preparing Neo4j graph upsert intents",
    "project_neo4j_graph": "Applying graph upserts to Neo4j",
    "publish_outbox": "Publishing Databricks lakehouse result",
}
PIPELINE_STAGES = [
    "register_manifest",
    "validate_and_probe_media",
    "extract_audio_assets",
    "extract_frame_assets",
    "run_florence_frame_analysis",
    "run_faster_whisper_asr",
    "detect_scenes_and_windows",
    "run_databricks_scene_reasoning",
    "build_gold_processing_result",
    "build_graph_upserts",
    "project_neo4j_graph",
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
        StructField("format_name", StringType(), nullable=True),
        StructField("duration_seconds", DoubleType(), nullable=True),
        StructField("video_codec", StringType(), nullable=True),
        StructField("audio_codec", StringType(), nullable=True),
        StructField("width", LongType(), nullable=True),
        StructField("height", LongType(), nullable=True),
        StructField("fps", DoubleType(), nullable=True),
        StructField("has_audio", StringType(), nullable=False),
        StructField("quality_status", StringType(), nullable=False),
        StructField("quality_details", StringType(), nullable=False),
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
FRAME_ANALYSIS_SCHEMA = StructType(
    [
        StructField("analysis_id", StringType(), nullable=False),
        StructField("media_id", StringType(), nullable=False),
        StructField("dispatch_id", StringType(), nullable=False),
        StructField("frame_asset_id", StringType(), nullable=False),
        StructField("frame_index", LongType(), nullable=False),
        StructField("timestamp_ms", LongType(), nullable=False),
        StructField("model_name", StringType(), nullable=False),
        StructField("model_version", StringType(), nullable=True),
        StructField("provider", StringType(), nullable=False),
        StructField("task", StringType(), nullable=False),
        StructField("caption", StringType(), nullable=True),
        StructField("ocr_text", StringType(), nullable=True),
        StructField("objects_json", StringType(), nullable=False),
        StructField("regions_json", StringType(), nullable=False),
        StructField("grounding_json", StringType(), nullable=False),
        StructField("raw_output_json", StringType(), nullable=False),
        StructField("latency_ms", DoubleType(), nullable=True),
        StructField("status", StringType(), nullable=False),
        StructField("error", StringType(), nullable=False),
        StructField("created_at", TimestampType(), nullable=False),
        StructField("updated_at", TimestampType(), nullable=False),
    ]
)
TEMPORAL_WINDOWS_SCHEMA = StructType(
    [
        StructField("window_id", StringType(), nullable=False),
        StructField("media_id", StringType(), nullable=False),
        StructField("dispatch_id", StringType(), nullable=False),
        StructField("window_index", LongType(), nullable=False),
        StructField("start_ms", LongType(), nullable=False),
        StructField("end_ms", LongType(), nullable=False),
        StructField("duration_seconds", DoubleType(), nullable=False),
        StructField("strategy", StringType(), nullable=False),
        StructField("frame_asset_ids", StringType(), nullable=False),
        StructField("transcript_segment_ids", StringType(), nullable=False),
        StructField("created_at", TimestampType(), nullable=False),
    ]
)
SCENE_CANDIDATES_SCHEMA = StructType(
    [
        StructField("scene_candidate_id", StringType(), nullable=False),
        StructField("media_id", StringType(), nullable=False),
        StructField("dispatch_id", StringType(), nullable=False),
        StructField("scene_index", LongType(), nullable=False),
        StructField("start_ms", LongType(), nullable=False),
        StructField("end_ms", LongType(), nullable=False),
        StructField("duration_seconds", DoubleType(), nullable=False),
        StructField("strategy", StringType(), nullable=False),
        StructField("boundary_reasons", StringType(), nullable=False),
        StructField("confidence", DoubleType(), nullable=False),
        StructField("frame_asset_ids", StringType(), nullable=False),
        StructField("transcript_segment_ids", StringType(), nullable=False),
        StructField("status", StringType(), nullable=False),
        StructField("created_at", TimestampType(), nullable=False),
    ]
)
SCENE_VISUAL_ANALYSIS_SCHEMA = StructType(
    [
        StructField("analysis_id", StringType(), nullable=False),
        StructField("media_id", StringType(), nullable=False),
        StructField("dispatch_id", StringType(), nullable=False),
        StructField("scene_candidate_id", StringType(), nullable=False),
        StructField("window_id", StringType(), nullable=True),
        StructField("scene_index", LongType(), nullable=False),
        StructField("start_ms", LongType(), nullable=False),
        StructField("end_ms", LongType(), nullable=False),
        StructField("model_name", StringType(), nullable=False),
        StructField("model_version", StringType(), nullable=True),
        StructField("provider", StringType(), nullable=False),
        StructField("summary", StringType(), nullable=True),
        StructField("actions_json", StringType(), nullable=False),
        StructField("entities_json", StringType(), nullable=False),
        StructField("relations_json", StringType(), nullable=False),
        StructField("evidence_frame_ids", StringType(), nullable=False),
        StructField("request_payload_json", StringType(), nullable=False),
        StructField("response_json", StringType(), nullable=False),
        StructField("latency_ms", DoubleType(), nullable=True),
        StructField("tokens_prompt", LongType(), nullable=True),
        StructField("tokens_completion", LongType(), nullable=True),
        StructField("status", StringType(), nullable=False),
        StructField("error", StringType(), nullable=False),
        StructField("created_at", TimestampType(), nullable=False),
        StructField("updated_at", TimestampType(), nullable=False),
    ]
)
MODEL_INFERENCE_RUNS_SCHEMA = StructType(
    [
        StructField("inference_run_id", StringType(), nullable=False),
        StructField("media_id", StringType(), nullable=False),
        StructField("dispatch_id", StringType(), nullable=False),
        StructField("stage", StringType(), nullable=False),
        StructField("provider", StringType(), nullable=False),
        StructField("model_name", StringType(), nullable=False),
        StructField("model_version", StringType(), nullable=True),
        StructField("input_count", LongType(), nullable=False),
        StructField("success_count", LongType(), nullable=False),
        StructField("failed_count", LongType(), nullable=False),
        StructField("duration_seconds", DoubleType(), nullable=True),
        StructField("gpu_type", StringType(), nullable=True),
        StructField("metrics_json", StringType(), nullable=False),
        StructField("status", StringType(), nullable=False),
        StructField("error", StringType(), nullable=False),
        StructField("started_at", TimestampType(), nullable=False),
        StructField("completed_at", TimestampType(), nullable=True),
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
        StructField("provider_file_id", StringType(), nullable=True),
        StructField("provider_batch_id", StringType(), nullable=True),
        StructField("provider_output_file_id", StringType(), nullable=True),
        StructField("provider_error_file_id", StringType(), nullable=True),
        StructField("provider_status", StringType(), nullable=True),
        StructField("provider_metadata", StringType(), nullable=False),
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
GOLD_PROCESSING_RESULTS_SCHEMA = StructType(
    [
        StructField("result_id", StringType(), nullable=False),
        StructField("media_id", StringType(), nullable=False),
        StructField("dispatch_id", StringType(), nullable=False),
        StructField("schema_version", StringType(), nullable=False),
        StructField("processing_version", StringType(), nullable=False),
        StructField("config_hash", StringType(), nullable=False),
        StructField("status", StringType(), nullable=False),
        StructField("video_title", StringType(), nullable=True),
        StructField("video_summary", StringType(), nullable=True),
        StructField("key_topics", StringType(), nullable=False),
        StructField("structure_json", StringType(), nullable=False),
        StructField("audio_data_json", StringType(), nullable=False),
        StructField("frames_data_json", StringType(), nullable=False),
        StructField("video_metadata_json", StringType(), nullable=False),
        StructField("processing_result_json", StringType(), nullable=False),
        StructField("metrics_json", StringType(), nullable=False),
        StructField("created_at", TimestampType(), nullable=False),
        StructField("updated_at", TimestampType(), nullable=False),
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
qualified_frame_analysis_table = (
    f"{quote_identifier(catalog)}.{quote_identifier(schema)}.{quote_identifier(FRAME_ANALYSIS_TABLE)}"
)
qualified_temporal_windows_table = (
    f"{quote_identifier(catalog)}."
    f"{quote_identifier(schema)}."
    f"{quote_identifier(TEMPORAL_WINDOWS_TABLE)}"
)
qualified_scene_candidates_table = (
    f"{quote_identifier(catalog)}."
    f"{quote_identifier(schema)}."
    f"{quote_identifier(SCENE_CANDIDATES_TABLE)}"
)
qualified_scene_visual_analysis_table = (
    f"{quote_identifier(catalog)}."
    f"{quote_identifier(schema)}."
    f"{quote_identifier(SCENE_VISUAL_ANALYSIS_TABLE)}"
)
qualified_model_inference_runs_table = (
    f"{quote_identifier(catalog)}."
    f"{quote_identifier(schema)}."
    f"{quote_identifier(MODEL_INFERENCE_RUNS_TABLE)}"
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
qualified_gold_processing_results_table = (
    f"{quote_identifier(catalog)}."
    f"{quote_identifier(schema)}."
    f"{quote_identifier(GOLD_PROCESSING_RESULTS_TABLE)}"
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
        "azure_openai": {
            "api_key_env",
            "api_key_secret_key",
            "api_key_secret_scope",
            "api_version",
            "completion_window",
            "endpoint",
            "max_wait_seconds",
            "poll_interval_seconds",
            "request_timeout_seconds",
        },
        "azure_openai_batch": {
            "api_key_env",
            "api_key_secret_key",
            "api_key_secret_scope",
            "api_version",
            "completion_window",
            "endpoint",
            "max_wait_seconds",
            "poll_interval_seconds",
            "request_timeout_seconds",
        },
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
            "azure_openai",
            "azure_openai_batch",
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


def ensure_table_columns(table_name: str, columns: dict[str, str]) -> None:
    existing_columns = set(spark.table(table_name).columns)
    for column_name, column_type in columns.items():
        if column_name not in existing_columns:
            spark.sql(f"ALTER TABLE {table_name} ADD COLUMNS ({column_name} {column_type})")


source_media = parse_json_object(source_media_raw, "source_media")
pipeline_config = parse_json_object(pipeline_config_raw, "pipeline_config")
validate_no_raw_secrets(source_media, "source_media")
validate_no_raw_secrets(pipeline_config)
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
          format_name STRING,
          duration_seconds DOUBLE,
          video_codec STRING,
          audio_codec STRING,
          width BIGINT,
          height BIGINT,
          fps DOUBLE,
          has_audio STRING,
          quality_status STRING,
          quality_details STRING,
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
        CREATE TABLE IF NOT EXISTS {qualified_frame_analysis_table} (
          analysis_id STRING,
          media_id STRING,
          dispatch_id STRING,
          frame_asset_id STRING,
          frame_index BIGINT,
          timestamp_ms BIGINT,
          model_name STRING,
          model_version STRING,
          provider STRING,
          task STRING,
          caption STRING,
          ocr_text STRING,
          objects_json STRING,
          regions_json STRING,
          grounding_json STRING,
          raw_output_json STRING,
          latency_ms DOUBLE,
          status STRING,
          error STRING,
          created_at TIMESTAMP,
          updated_at TIMESTAMP
        )
        USING DELTA
        """
    )
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {qualified_temporal_windows_table} (
          window_id STRING,
          media_id STRING,
          dispatch_id STRING,
          window_index BIGINT,
          start_ms BIGINT,
          end_ms BIGINT,
          duration_seconds DOUBLE,
          strategy STRING,
          frame_asset_ids STRING,
          transcript_segment_ids STRING,
          created_at TIMESTAMP
        )
        USING DELTA
        """
    )
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {qualified_scene_candidates_table} (
          scene_candidate_id STRING,
          media_id STRING,
          dispatch_id STRING,
          scene_index BIGINT,
          start_ms BIGINT,
          end_ms BIGINT,
          duration_seconds DOUBLE,
          strategy STRING,
          boundary_reasons STRING,
          confidence DOUBLE,
          frame_asset_ids STRING,
          transcript_segment_ids STRING,
          status STRING,
          created_at TIMESTAMP
        )
        USING DELTA
        """
    )
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {qualified_scene_visual_analysis_table} (
          analysis_id STRING,
          media_id STRING,
          dispatch_id STRING,
          scene_candidate_id STRING,
          window_id STRING,
          scene_index BIGINT,
          start_ms BIGINT,
          end_ms BIGINT,
          model_name STRING,
          model_version STRING,
          provider STRING,
          summary STRING,
          actions_json STRING,
          entities_json STRING,
          relations_json STRING,
          evidence_frame_ids STRING,
          request_payload_json STRING,
          response_json STRING,
          latency_ms DOUBLE,
          tokens_prompt BIGINT,
          tokens_completion BIGINT,
          status STRING,
          error STRING,
          created_at TIMESTAMP,
          updated_at TIMESTAMP
        )
        USING DELTA
        """
    )
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {qualified_model_inference_runs_table} (
          inference_run_id STRING,
          media_id STRING,
          dispatch_id STRING,
          stage STRING,
          provider STRING,
          model_name STRING,
          model_version STRING,
          input_count BIGINT,
          success_count BIGINT,
          failed_count BIGINT,
          duration_seconds DOUBLE,
          gpu_type STRING,
          metrics_json STRING,
          status STRING,
          error STRING,
          started_at TIMESTAMP,
          completed_at TIMESTAMP
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
          provider_file_id STRING,
          provider_batch_id STRING,
          provider_output_file_id STRING,
          provider_error_file_id STRING,
          provider_status STRING,
          provider_metadata STRING,
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
        CREATE TABLE IF NOT EXISTS {qualified_gold_processing_results_table} (
          result_id STRING,
          media_id STRING,
          dispatch_id STRING,
          schema_version STRING,
          processing_version STRING,
          config_hash STRING,
          status STRING,
          video_title STRING,
          video_summary STRING,
          key_topics STRING,
          structure_json STRING,
          audio_data_json STRING,
          frames_data_json STRING,
          video_metadata_json STRING,
          processing_result_json STRING,
          metrics_json STRING,
          created_at TIMESTAMP,
          updated_at TIMESTAMP
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
    ensure_table_columns(
        qualified_source_files_table,
        {
            "format_name": "STRING",
            "duration_seconds": "DOUBLE",
            "video_codec": "STRING",
            "audio_codec": "STRING",
            "width": "BIGINT",
            "height": "BIGINT",
            "fps": "DOUBLE",
            "has_audio": "STRING",
            "quality_status": "STRING",
            "quality_details": "STRING",
        },
    )
    ensure_table_columns(
        qualified_ai_batches_table,
        {
            "provider_file_id": "STRING",
            "provider_output_file_id": "STRING",
            "provider_error_file_id": "STRING",
            "provider_status": "STRING",
            "provider_metadata": "STRING",
        },
    )


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


def safe_path_segment(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return normalized.strip("._") or "unknown"


def volume_path(*parts: str) -> str:
    safe_parts = [safe_path_segment(part) for part in parts if part]
    return "/".join([f"/Volumes/{catalog}/{schema}/video_artifacts", *safe_parts])


def local_artifact_path(*parts: str) -> str:
    safe_parts = [safe_path_segment(part) for part in parts if part]
    return os.path.join(tempfile.gettempdir(), "qprisma-video-pipeline", *safe_parts)


def copy_local_file_to_volume(local_path: str, destination: str) -> None:
    dbutils.fs.mkdirs(os.path.dirname(destination))
    try:
        dbutils.fs.rm(destination)
    except Exception as exc:
        if "FileNotFound" not in str(exc) and "does not exist" not in str(exc):
            raise
    dbutils.fs.cp(f"file:{local_path}", destination)


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


def pipeline_models_config() -> dict:
    """Return model routing config for the pipeline.

    Model routing rules:
    - ``vision`` / ``summary``: used for Azure OpenAI Batch API requests. Defaults to
      ``gpt-5.1-batch`` which is the only batch-capable deployment available.
    - ``direct``: used for synchronous / non-batch LLM calls. Defaults to ``gpt-5.5``.

    Callers should use ``models["vision"]`` and ``models["summary"]`` for batch
    inference requests and ``models["direct"]`` for any real-time / conversational
    calls so that the correct deployment endpoint is always targeted.
    """
    models = pipeline_config.get("models") or {}
    if not isinstance(models, dict):
        raise ValueError("pipeline_config.models must be an object when provided")
    return {
        "vision": str(models.get("vision") or pipeline_config.get("vision_model") or "gpt-5.1-batch"),
        "summary": str(models.get("summary") or pipeline_config.get("summary_model") or "gpt-5.1-batch"),
        "direct": str(models.get("direct") or pipeline_config.get("direct_model") or "gpt-5.5"),
        "prompt_version": str(pipeline_config.get("prompt_version") or schema_version),
    }


def inference_mode_config() -> dict:
    cfg = pipeline_config.get("inference") or {}
    if cfg and not isinstance(cfg, dict):
        raise ValueError("pipeline_config.inference must be an object when provided")
    mode = str(cfg.get("mode") or pipeline_config.get("inference_mode") or "local_databricks").strip().lower()
    supported_modes = {"local_databricks"}
    if mode not in supported_modes:
        raise ValueError("pipeline_config.inference.mode must be local_databricks for this Databricks DAG")
    return {"mode": mode}


def azure_openai_batch_enabled() -> bool:
    return inference_mode_config()["mode"] == "batch_cost"


def batch_inference_skip_metrics() -> dict:
    mode = inference_mode_config()["mode"]
    return {
        "skipped": True,
        "skipped_reason": f"inference_mode_{mode}_does_not_use_azure_openai_batch",
        "inference_mode": mode,
        "ai_batches_table": AI_BATCHES_TABLE,
        "ai_results_table": AI_RESULTS_TABLE,
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


def local_read_path(uri: str) -> str:
    if uri.startswith("dbfs:/Volumes/"):
        return uri.replace("dbfs:", "", 1)
    return uri


def read_image_as_data_url(uri: str) -> str:
    path = local_read_path(uri)
    with open(path, "rb") as image_file:
        encoded = base64.b64encode(image_file.read()).decode("ascii")
    return f"data:{image_media_type(path)};base64,{encoded}"


def inference_section(name: str) -> dict:
    inference = pipeline_config.get("inference") or {}
    if inference and not isinstance(inference, dict):
        raise ValueError("pipeline_config.inference must be an object when provided")
    section = inference.get(name) or pipeline_config.get(name) or {}
    if section and not isinstance(section, dict):
        raise ValueError(f"pipeline_config.inference.{name} must be an object when provided")
    return section


def frame_analysis_config() -> dict:
    cfg = inference_section("frame_analysis")
    enabled_default = inference_mode_config()["mode"] == "local_databricks"
    enabled = config_bool(cfg.get("enabled"), default=enabled_default)
    model_name = str(cfg.get("model") or "microsoft/Florence-2-large-ft")
    if model_name not in ALLOWED_FLORENCE_MODELS:
        raise ValueError(
            "Florence frame analysis only supports microsoft/Florence-2-large-ft in this MVP. "
            "Do not pass arbitrary Hugging Face models because Florence requires trust_remote_code."
        )
    configured_revision = str(cfg.get("model_revision") or "").strip()
    deployed_revision = str(os.environ.get("QPRISMA_FLORENCE_MODEL_REVISION") or "").strip()
    if configured_revision and configured_revision != deployed_revision:
        raise ValueError(
            "pipeline_config.inference.frame_analysis.model_revision cannot override the "
            "deployment-owned QPRISMA_FLORENCE_MODEL_REVISION value."
        )
    if enabled and not deployed_revision:
        raise ValueError(
            "QPRISMA_FLORENCE_MODEL_REVISION must pin the vetted Florence-2 commit because "
            "microsoft/Florence-2-large-ft requires trust_remote_code."
        )
    tasks = cfg.get("tasks") or ["caption", "ocr"]
    if isinstance(tasks, str):
        tasks = [item.strip() for item in tasks.split(",") if item.strip()]
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("pipeline_config.inference.frame_analysis.tasks must be a non-empty list")
    supported_tasks = {"caption", "ocr", "object_detection", "dense_region_caption"}
    normalized_tasks = [str(task).strip().lower() for task in tasks]
    unsupported = sorted(set(normalized_tasks) - supported_tasks)
    if unsupported:
        raise ValueError(f"Unsupported Florence frame analysis tasks: {unsupported}")
    return {
        "enabled": enabled,
        "provider": str(cfg.get("provider") or "databricks_job"),
        "model_name": model_name,
        "model_revision": deployed_revision or configured_revision or None,
        "tasks": normalized_tasks,
        "batch_size": bounded_int("batch_size", cfg.get("batch_size"), default=2, minimum=1, maximum=64),
        "max_frames": bounded_int("max_frames", cfg.get("max_frames"), default=5, minimum=1, maximum=1000),
        "max_new_tokens": bounded_int(
            "max_new_tokens",
            cfg.get("max_new_tokens"),
            default=512,
            minimum=32,
            maximum=4096,
        ),
        "device": str(cfg.get("device") or "auto"),
        "torch_dtype": str(cfg.get("torch_dtype") or "auto"),
    }


FLORENCE_TASK_PROMPTS = {
    "caption": "<CAPTION>",
    "ocr": "<OCR>",
    "object_detection": "<OD>",
    "dense_region_caption": "<DENSE_REGION_CAPTION>",
}


def torch_runtime_device(config: dict) -> tuple[Any, str]:
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError(
            "PyTorch is required for Florence-2 frame analysis. Use a Databricks ML GPU runtime "
            "or install torch on the run_florence_frame_analysis task."
        ) from exc

    requested_device = str(config.get("device") or "auto").lower()
    if requested_device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    else:
        device = requested_device
    return torch, device


def torch_dtype_for_device(torch_module: Any, config: dict, device: str) -> Any:
    dtype_name = str(config.get("torch_dtype") or "auto").lower()
    if dtype_name == "auto":
        return torch_module.float16 if device.startswith("cuda") else torch_module.float32
    allowed = {
        "float16": torch_module.float16,
        "fp16": torch_module.float16,
        "bfloat16": torch_module.bfloat16,
        "bf16": torch_module.bfloat16,
        "float32": torch_module.float32,
        "fp32": torch_module.float32,
    }
    if dtype_name not in allowed:
        raise ValueError("Florence torch_dtype must be one of auto, float16, bfloat16, float32")
    return allowed[dtype_name]


def load_florence_components(config: dict) -> dict:
    try:
        from transformers import AutoModelForCausalLM, AutoProcessor
    except ImportError as exc:
        raise RuntimeError(
            "transformers is required for Florence-2 frame analysis. Install transformers, "
            "timm, einops and Pillow on the run_florence_frame_analysis task."
        ) from exc

    torch_module, device = torch_runtime_device(config)
    torch_dtype = torch_dtype_for_device(torch_module, config, device)
    model_kwargs = {
        "trust_remote_code": True,
        "torch_dtype": torch_dtype,
    }
    if config.get("model_revision"):
        model_kwargs["revision"] = config["model_revision"]
    model = AutoModelForCausalLM.from_pretrained(config["model_name"], **model_kwargs).to(device)
    processor_kwargs = {"trust_remote_code": True}
    if config.get("model_revision"):
        processor_kwargs["revision"] = config["model_revision"]
    processor = AutoProcessor.from_pretrained(config["model_name"], **processor_kwargs)
    model.eval()
    return {"model": model, "processor": processor, "torch": torch_module, "device": device}


def normalize_florence_task_payload(raw_output: dict, task_prompt: str) -> dict | str:
    if task_prompt in raw_output:
        return raw_output[task_prompt]
    return raw_output


def text_from_model_payload(payload: Any) -> str | None:
    if isinstance(payload, str):
        return payload.strip() or None
    if isinstance(payload, dict):
        for key in ("caption", "text", "ocr", "description", "summary"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        labels = payload.get("labels")
        if isinstance(labels, list):
            joined = ", ".join(str(label).strip() for label in labels if str(label).strip())
            return joined or None
    return None


def florence_result_fields(task: str, parsed_payload: Any) -> dict:
    caption = text_from_model_payload(parsed_payload) if task == "caption" else None
    ocr_text = text_from_model_payload(parsed_payload) if task == "ocr" else None
    objects = parsed_payload if task == "object_detection" else {}
    regions = parsed_payload if task == "dense_region_caption" else {}
    grounding = parsed_payload if task in {"object_detection", "dense_region_caption"} else {}
    return {
        "caption": caption,
        "ocr_text": ocr_text,
        "objects_json": json.dumps(objects or {}, separators=(",", ":"), sort_keys=True),
        "regions_json": json.dumps(regions or {}, separators=(",", ":"), sort_keys=True),
        "grounding_json": json.dumps(grounding or {}, separators=(",", ":"), sort_keys=True),
    }


def run_florence_task(components: dict, frame: dict, task: str, config: dict) -> dict:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required for Florence-2 frame analysis.") from exc

    task_prompt = FLORENCE_TASK_PROMPTS[task]
    image_path = local_read_path(frame["frame_uri"])
    image = Image.open(image_path).convert("RGB")
    processor = components["processor"]
    model = components["model"]
    torch_module = components["torch"]
    device = components["device"]
    inputs = processor(text=task_prompt, images=image, return_tensors="pt")
    inputs = {key: value.to(device) for key, value in inputs.items()}
    with torch_module.inference_mode():
        generated_ids = model.generate(
            input_ids=inputs["input_ids"],
            pixel_values=inputs["pixel_values"],
            max_new_tokens=int(config["max_new_tokens"]),
            num_beams=3,
        )
    generated_text = processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
    raw_output = processor.post_process_generation(
        generated_text,
        task=task_prompt,
        image_size=(image.width, image.height),
    )
    return {
        "raw_output": raw_output,
        "parsed_payload": normalize_florence_task_payload(raw_output, task_prompt),
    }


def frame_analysis_row(
    frame: dict,
    config: dict,
    *,
    task: str,
    status: str,
    latency_ms: float | None,
    raw_output: dict | None = None,
    parsed_payload: Any = None,
    error: dict | None = None,
) -> dict:
    now = datetime.now(UTC)
    fields = florence_result_fields(task, parsed_payload or {})
    analysis_hash = stable_hash(
        {
            "frame_asset_id": frame["frame_asset_id"],
            "model_name": config["model_name"],
            "model_revision": config.get("model_revision"),
            "task": task,
            "config_hash": config_hash,
        }
    )
    return {
        "analysis_id": f"{media_id}:frame_analysis:{analysis_hash[:16]}",
        "media_id": media_id,
        "dispatch_id": dispatch_id,
        "frame_asset_id": frame["frame_asset_id"],
        "frame_index": int(frame["frame_index"]),
        "timestamp_ms": int(frame["timestamp_ms"]),
        "model_name": config["model_name"],
        "model_version": config.get("model_revision"),
        "provider": config["provider"],
        "task": task,
        **fields,
        "raw_output_json": json.dumps(raw_output or {}, separators=(",", ":"), sort_keys=True),
        "latency_ms": latency_ms,
        "status": status,
        "error": json_dumps(error or {}),
        "created_at": now,
        "updated_at": now,
    }


def write_model_inference_run(
    *,
    stage_name: str,
    provider: str,
    model_name: str,
    model_version: str | None,
    input_count: int,
    success_count: int,
    failed_count: int,
    duration_seconds: float,
    metrics: dict,
    status: str,
    error: dict | None = None,
    started_at: datetime | None = None,
) -> None:
    completed_at = datetime.now(UTC)
    merge_row(
        qualified_model_inference_runs_table,
        {
            "inference_run_id": (
                f"{media_id}:{dispatch_id}:{stage_name}:{model_name}:{config_hash[:12]}"
            ),
            "media_id": media_id,
            "dispatch_id": dispatch_id,
            "stage": stage_name,
            "provider": provider,
            "model_name": model_name,
            "model_version": model_version,
            "input_count": int(input_count),
            "success_count": int(success_count),
            "failed_count": int(failed_count),
            "duration_seconds": rounded_metric(duration_seconds),
            "gpu_type": metrics.get("gpu_type"),
            "metrics_json": json_dumps(metrics),
            "status": status,
            "error": json_dumps(error or {}),
            "started_at": started_at or completed_at,
            "completed_at": completed_at,
        },
        MODEL_INFERENCE_RUNS_SCHEMA,
        ["inference_run_id"],
    )


def register_frame_analysis_rows(rows: list[dict]) -> None:
    for row in rows:
        merge_row(qualified_frame_analysis_table, row, FRAME_ANALYSIS_SCHEMA, ["analysis_id"])


def run_florence_frame_analysis() -> dict:
    stage_started_at = datetime.now(UTC)
    stage_started = time.perf_counter()
    config = frame_analysis_config()
    if not config["enabled"]:
        metrics = {
            "skipped": True,
            "skipped_reason": "frame_analysis_disabled",
            "frame_analysis_table": FRAME_ANALYSIS_TABLE,
            "model_inference_runs_table": MODEL_INFERENCE_RUNS_TABLE,
        }
        write_model_inference_run(
            stage_name="run_florence_frame_analysis",
            provider=config["provider"],
            model_name=config["model_name"],
            model_version=config.get("model_revision"),
            input_count=0,
            success_count=0,
            failed_count=0,
            duration_seconds=time.perf_counter() - stage_started,
            metrics=metrics,
            status="skipped",
            started_at=stage_started_at,
        )
        return metrics

    frames = load_frame_assets()[: int(config["max_frames"])]
    components = load_florence_components(config)
    rows: list[dict] = []
    success_count = 0
    failed_count = 0
    for frame in frames:
        for task in config["tasks"]:
            task_started = time.perf_counter()
            try:
                result = run_florence_task(components, frame, task, config)
                latency_ms = (time.perf_counter() - task_started) * 1000
                rows.append(
                    frame_analysis_row(
                        frame,
                        config,
                        task=task,
                        status="completed",
                        latency_ms=rounded_metric(latency_ms),
                        raw_output=result["raw_output"],
                        parsed_payload=result["parsed_payload"],
                    )
                )
                success_count += 1
            except (RuntimeError, ValueError, OSError) as exc:
                latency_ms = (time.perf_counter() - task_started) * 1000
                rows.append(
                    frame_analysis_row(
                        frame,
                        config,
                        task=task,
                        status="failed",
                        latency_ms=rounded_metric(latency_ms),
                        error={"type": type(exc).__name__, "message": str(exc)},
                    )
                )
                failed_count += 1
    register_frame_analysis_rows(rows)
    elapsed = time.perf_counter() - stage_started
    metrics = {
        "frame_count": len(frames),
        "task_count": len(config["tasks"]),
        "input_count": len(rows),
        "success_count": success_count,
        "failed_count": failed_count,
        "elapsed_seconds": rounded_metric(elapsed),
        "inferences_per_second": rate_metric(success_count, elapsed),
        "model_name": config["model_name"],
        "model_version": config.get("model_revision"),
        "provider": config["provider"],
        "device": components["device"],
        "frame_analysis_table": FRAME_ANALYSIS_TABLE,
        "model_inference_runs_table": MODEL_INFERENCE_RUNS_TABLE,
        "smoke_ready": success_count > 0,
    }
    write_model_inference_run(
        stage_name="run_florence_frame_analysis",
        provider=config["provider"],
        model_name=config["model_name"],
        model_version=config.get("model_revision"),
        input_count=len(rows),
        success_count=success_count,
        failed_count=failed_count,
        duration_seconds=elapsed,
        metrics=metrics,
        status="completed" if failed_count == 0 else "completed_with_failures",
        started_at=stage_started_at,
    )
    if rows and success_count == 0:
        raise RuntimeError("Florence-2 frame analysis produced no successful outputs")
    return metrics


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
    if not azure_openai_batch_enabled():
        return []

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
        # model_name is intentionally excluded from the hash so that
        # changing the model config updates the existing row in-place via
        # the MERGE keyed on request_id, rather than inserting phantom rows.
        input_hash = stable_hash(
            {
                "frame_sha256": frame["sha256"],
                "prompt_version": models["prompt_version"],
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
        # model_name is intentionally excluded from the hash for the same
        # reason as frames: stable request_id across model config changes.
        input_hash = stable_hash(
            {
                "asr_run_id": asr_run["asr_run_id"],
                "transcript_text": asr_run["transcript_text"],
                "prompt_version": models["prompt_version"],
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
          provider_file_id,
          provider_batch_id,
          provider_output_file_id,
          provider_error_file_id,
          provider_status,
          provider_metadata,
          created_at,
          updated_at,
          submitted_at,
          completed_at,
          error
        FROM {qualified_ai_batches_table}
        WHERE media_id = {sql_literal(media_id)}
          AND dispatch_id = {sql_literal(dispatch_id)}
          AND status IN ('ready_for_submission', 'submitted', 'completed', 'failed')
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
    if not azure_openai_batch_enabled():
        return batch_inference_skip_metrics()

    all_requests = load_ai_requests()
    pending_requests = [request for request in all_requests if request["status"] == "pending"]
    existing_batches = [
        batch
        for batch in load_existing_ai_batches()
        if batch["status"] in {"ready_for_submission", "submitted", "completed"}
    ]
    now = datetime.now(UTC)

    # Invalidate any ready_for_submission batches that already have a provider_file_id.
    # Those files were uploaded to Azure OpenAI and are now stale (model config may have
    # changed or a previous attempt left mixed content). Marking them failed prevents
    # run_ai_batch_inference from picking them up and prevents the reuse trap below.
    if pending_requests:
        stale_batches = [
            b for b in existing_batches
            if b["status"] == "ready_for_submission" and b.get("provider_file_id")
        ]
        for stale in stale_batches:
            stale_failed = batch_row_with_provider_state(
                stale,
                status="failed",
                error={"stage": "stage_ai_batch_payloads", "reason": "invalidated_stale_file"},
            )
            write_ai_batch(stale_failed)
        # Refresh existing_batches list after invalidation.
        existing_batches = [
            batch
            for batch in load_existing_ai_batches()
            if batch["status"] in {"ready_for_submission", "submitted", "completed"}
        ]

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
        # Require an exact match: all pending requests must be in the JSONL AND the JSONL
        # must not contain any extra rows.  Extra rows mean the file was built from a
        # different (larger) request set and must not be reused.
        exact_match = (
            not pending_requests
            or (
                len(pending_in_batch) == len(pending_requests)
                and len(batch_request_ids) == len(pending_requests)
            )
        )
        if exact_match:
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
            "provider_file_id": None,
            "provider_batch_id": None,
            "provider_output_file_id": None,
            "provider_error_file_id": None,
            "provider_status": None,
            "provider_metadata": json_dumps({}),
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


def azure_openai_batch_config() -> dict:
    cfg = pipeline_config.get("azure_openai_batch") or pipeline_config.get("azure_openai") or {}
    if not isinstance(cfg, dict):
        raise ValueError("pipeline_config.azure_openai_batch/azure_openai must be an object")

    endpoint = str(cfg.get("endpoint") or os.environ.get("AZURE_OPENAI_ENDPOINT") or "").rstrip("/")
    api_version = str(
        cfg.get("api_version") or os.environ.get("AZURE_OPENAI_API_VERSION") or "2024-08-01-preview"
    )
    api_key = ""
    secret_scope = cfg.get("api_key_secret_scope")
    secret_key = cfg.get("api_key_secret_key")
    if secret_scope and secret_key:
        api_key = dbutils.secrets.get(str(secret_scope), str(secret_key))
    else:
        api_key_env = str(cfg.get("api_key_env") or "AZURE_OPENAI_API_KEY")
        api_key = os.environ.get(api_key_env, "")

    if not endpoint:
        raise ValueError(
            "Azure OpenAI Batch endpoint is missing. Set pipeline_config.azure_openai_batch.endpoint "
            "or AZURE_OPENAI_ENDPOINT."
        )
    if not endpoint.startswith("https://"):
        raise ValueError("Azure OpenAI Batch endpoint must use https://")
    endpoint_host = (urlparse(endpoint).hostname or "").lower()
    allowed_suffixes = [
        suffix.strip().lower()
        for suffix in os.environ.get(
            "AZURE_OPENAI_ALLOWED_ENDPOINT_SUFFIXES",
            "openai.azure.com,cognitiveservices.azure.com",
        ).split(",")
        if suffix.strip()
    ]
    if not allowed_suffixes:
        raise ValueError("AZURE_OPENAI_ALLOWED_ENDPOINT_SUFFIXES cannot be empty")
    if not any(
        endpoint_host == suffix or endpoint_host.endswith(f".{suffix}")
        for suffix in allowed_suffixes
    ):
        raise ValueError(
            "Azure OpenAI Batch endpoint host is not in the allowed Azure OpenAI suffix list"
        )
    if not api_key:
        raise ValueError(
            "Azure OpenAI Batch API key is missing. Use pipeline_config.azure_openai_batch "
            "api_key_secret_scope/api_key_secret_key or api_key_env."
        )

    return {
        "endpoint": endpoint,
        "api_version": api_version,
        "api_key": api_key,
        "completion_window": str(cfg.get("completion_window") or "24h"),
        "poll_interval_seconds": int(cfg.get("poll_interval_seconds") or 30),
        "max_wait_seconds": int(cfg.get("max_wait_seconds") or 3600),
        "request_timeout_seconds": int(cfg.get("request_timeout_seconds") or 120),
    }


def azure_openai_url(config: dict, path: str) -> str:
    separator = "&" if "?" in path else "?"
    return f"{config['endpoint']}/openai{path}{separator}api-version={config['api_version']}"


def azure_openai_request(
    config: dict,
    *,
    method: str,
    path: str,
    body: bytes | Iterable[bytes] | None = None,
    content_type: str | None = "application/json",
    content_length: int | None = None,
) -> bytes:
    headers = {"api-key": config["api_key"]}
    if content_type:
        headers["Content-Type"] = content_type
    if content_length is not None:
        headers["Content-Length"] = str(content_length)
    request = urllib.request.Request(  # noqa: S310
        azure_openai_url(config, path),
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(  # noqa: S310
            request,
            timeout=config["request_timeout_seconds"],
        ) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Azure OpenAI {method} {path} failed with {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Azure OpenAI {method} {path} failed: {exc}") from exc


def azure_openai_json(
    config: dict,
    *,
    method: str,
    path: str,
    payload: dict | None = None,
) -> dict:
    body = None
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    raw_response = azure_openai_request(config, method=method, path=path, body=body)
    return json.loads(raw_response.decode("utf-8"))


def azure_openai_upload_batch_file(config: dict, batch_uri: str) -> dict:
    boundary = f"----qprisma-{uuid4().hex}"
    filename = os.path.basename(batch_uri)
    preamble = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="purpose"\r\n\r\n',
            b"batch\r\n",
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                "Content-Type: application/jsonl\r\n\r\n"
            ).encode(),
        ]
    )
    epilogue = b"\r\n" + f"--{boundary}--\r\n".encode()
    content_length = len(preamble) + os.path.getsize(batch_uri) + len(epilogue)

    def multipart_body() -> Iterable[bytes]:
        yield preamble
        with open(batch_uri, "rb") as batch_file:
            while chunk := batch_file.read(1024 * 1024):
                yield chunk
        yield epilogue

    raw_response = azure_openai_request(
        config,
        method="POST",
        path="/files",
        body=multipart_body(),
        content_type=f"multipart/form-data; boundary={boundary}",
        content_length=content_length,
    )
    return json.loads(raw_response.decode("utf-8"))


def azure_openai_create_batch(config: dict, input_file_id: str, batch: dict) -> dict:
    return azure_openai_json(
        config,
        method="POST",
        path="/batches",
        payload={
            "input_file_id": input_file_id,
            "endpoint": "/chat/completions",
            "completion_window": config["completion_window"],
            "metadata": {
                "media_id": media_id,
                "dispatch_id": dispatch_id,
                "qprisma_batch_id": batch["batch_id"],
            },
        },
    )


def azure_openai_retrieve_batch(config: dict, provider_batch_id: str) -> dict:
    return azure_openai_json(config, method="GET", path=f"/batches/{provider_batch_id}")


def azure_openai_download_file(config: dict, file_id: str) -> str:
    raw_response = azure_openai_request(
        config,
        method="GET",
        path=f"/files/{file_id}/content",
        content_type=None,
    )
    return raw_response.decode("utf-8")


def provider_request_counts(provider_batch: dict) -> dict:
    request_counts = provider_batch.get("request_counts") or {}
    return {
        "total": int(request_counts.get("total") or 0),
        "completed": int(request_counts.get("completed") or 0),
        "failed": int(request_counts.get("failed") or 0),
    }


def batch_row_with_provider_state(
    batch: dict,
    *,
    status: str,
    provider_batch: dict | None = None,
    provider_file_id: str | None = None,
    provider_metadata: dict | None = None,
    error: dict | None = None,
    completed: bool = False,
) -> dict:
    provider_batch = provider_batch or {}
    now = datetime.now(UTC)
    metadata = {
        "request_counts": provider_request_counts(provider_batch),
        "raw_status": provider_batch.get("status"),
    }
    metadata.update(provider_metadata or {})
    return {
        **batch,
        "status": status,
        "provider_file_id": provider_file_id or batch.get("provider_file_id"),
        "provider_batch_id": provider_batch.get("id") or batch.get("provider_batch_id"),
        "provider_output_file_id": provider_batch.get("output_file_id")
        or batch.get("provider_output_file_id"),
        "provider_error_file_id": provider_batch.get("error_file_id")
        or batch.get("provider_error_file_id"),
        "provider_status": provider_batch.get("status") or batch.get("provider_status"),
        "provider_metadata": json_dumps(metadata),
        "updated_at": now,
        "submitted_at": batch.get("submitted_at") or now if status == "submitted" else batch.get("submitted_at"),
        "completed_at": now if completed else batch.get("completed_at"),
        "error": json_dumps(error or {}),
    }


def write_ai_batch(batch: dict) -> None:
    merge_row(qualified_ai_batches_table, batch, AI_BATCHES_SCHEMA, ["batch_id"])


def mark_ai_request_status(request: dict, status: str, now: datetime) -> None:
    merge_row(
        qualified_ai_requests_table,
        {**request, "status": status, "updated_at": now},
        AI_REQUESTS_SCHEMA,
        ["request_id"],
    )


def mark_batch_requests_status(batch: dict, status: str, now: datetime) -> int:
    request_ids = read_batch_request_ids(batch["batch_uri"])
    requests_by_id = {request["request_id"]: request for request in load_ai_requests()}
    updated_count = 0
    for request_id in request_ids:
        request = requests_by_id.get(request_id)
        if request:
            mark_ai_request_status(request, status, now)
            updated_count += 1
    return updated_count


def batch_artifact_uri(batch: dict, filename: str) -> str:
    return f"{os.path.dirname(batch['batch_uri'])}/{filename}"


def write_text_artifact(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as artifact_file:
        artifact_file.write(content)


def parse_jsonl(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def ai_result_row(batch: dict, request: dict, provider_result: dict) -> dict:
    response = provider_result.get("response") or {}
    body = response.get("body") or {}
    usage = body.get("usage") or {}
    status_code = int(response.get("status_code") or 0)
    content = ""
    normalized = {}
    error = {}
    status = "failed"
    if status_code == 200:
        choices = body.get("choices") or []
        if choices:
            content = str(((choices[0].get("message") or {}).get("content")) or "")
        try:
            parsed_content = json.loads(content or "{}")
            if isinstance(parsed_content, dict):
                normalized = parsed_content
                status = "completed"
            else:
                error = {"reason": "model_response_not_json_object", "content": content}
        except json.JSONDecodeError as exc:
            error = {"reason": "model_response_json_parse_failed", "message": str(exc), "content": content}
    else:
        error = provider_result.get("error") or body.get("error") or {"status_code": status_code}

    now = datetime.now(UTC)
    return {
        "result_id": f"{request['request_id']}:result:{stable_hash({'batch_id': batch['batch_id']})[:12]}",
        "request_id": request["request_id"],
        "batch_id": batch["batch_id"],
        "media_id": request["media_id"],
        "dispatch_id": request["dispatch_id"],
        "source_type": request["source_type"],
        "source_id": request["source_id"],
        "model_name": request["model_name"],
        "prompt_version": request["prompt_version"],
        "status": status,
        "response_json": json.dumps(provider_result, separators=(",", ":"), sort_keys=True),
        "normalized_json": json_dumps(normalized),
        "tokens_prompt": usage.get("prompt_tokens"),
        "tokens_completion": usage.get("completion_tokens"),
        "created_at": now,
        "updated_at": now,
        "error": json_dumps(error),
    }


def ingest_ai_batch_results(config: dict, batch: dict, provider_batch: dict) -> dict:
    output_file_id = provider_batch.get("output_file_id")
    error_file_id = provider_batch.get("error_file_id")
    if not output_file_id and not error_file_id:
        raise ValueError(f"Completed provider batch {provider_batch.get('id')} has no output or error file")

    provider_results = []
    provider_artifacts = {}
    if output_file_id:
        output_text = azure_openai_download_file(config, output_file_id)
        output_uri = batch_artifact_uri(batch, "provider_output.jsonl")
        write_text_artifact(output_uri, output_text)
        provider_artifacts["output_uri"] = output_uri
        provider_results.extend(parse_jsonl(output_text))
    if error_file_id:
        error_text = azure_openai_download_file(config, error_file_id)
        error_uri = batch_artifact_uri(batch, "provider_errors.jsonl")
        write_text_artifact(error_uri, error_text)
        provider_artifacts["error_uri"] = error_uri
        provider_results.extend(parse_jsonl(error_text))

    requests_by_id = {request["request_id"]: request for request in load_ai_requests()}
    status_counts: dict[str, int] = {}
    now = datetime.now(UTC)
    for provider_result in provider_results:
        request_id = provider_result.get("custom_id")
        request = requests_by_id.get(request_id)
        if not request:
            raise ValueError(f"Provider batch returned unknown custom_id: {request_id}")
        result = ai_result_row(batch, request, provider_result)
        merge_row(qualified_ai_results_table, result, AI_RESULTS_SCHEMA, ["result_id"])
        mark_ai_request_status(request, result["status"], now)
        status_counts[result["status"]] = status_counts.get(result["status"], 0) + 1

    completed_batch = batch_row_with_provider_state(
        batch,
        status="completed",
        provider_batch=provider_batch,
        provider_metadata=provider_artifacts,
        completed=True,
    )
    write_ai_batch(completed_batch)
    return {
        "batch_id": batch["batch_id"],
        "provider_batch_id": provider_batch.get("id"),
        "result_count": len(provider_results),
        "status_counts": status_counts,
        "request_counts": provider_request_counts(provider_batch),
    }


def submit_ai_batch(config: dict, batch: dict) -> dict:
    provider_file_id = batch.get("provider_file_id")
    if not provider_file_id:
        provider_file = azure_openai_upload_batch_file(config, batch["batch_uri"])
        provider_file_id = provider_file["id"]
        batch = batch_row_with_provider_state(
            batch,
            status="ready_for_submission",
            provider_file_id=provider_file_id,
            provider_metadata={"provider_file_uploaded": True},
        )
        write_ai_batch(batch)
    if batch.get("provider_batch_id"):
        return batch
    try:
        provider_batch = azure_openai_create_batch(config, provider_file_id, batch)
    except Exception as exc:
        # Mark the batch as failed so that the next stage_ai_batch_payloads run does
        # not attempt to reuse this batch row (which still has provider_file_id set).
        failed_batch = batch_row_with_provider_state(
            batch,
            status="failed",
            provider_file_id=provider_file_id,
            error={"stage": "create_batch", "error": str(exc)},
        )
        write_ai_batch(failed_batch)
        raise
    submitted_batch = batch_row_with_provider_state(
        batch,
        status="submitted",
        provider_batch=provider_batch,
        provider_file_id=provider_file_id,
    )
    write_ai_batch(submitted_batch)
    return submitted_batch


def wait_for_ai_batch(config: dict, batch: dict) -> dict:
    started = time.time()
    poll_count = 0
    provider_batch_id = batch.get("provider_batch_id")
    if not provider_batch_id:
        raise ValueError(f"Batch {batch['batch_id']} has no provider_batch_id")

    while True:
        provider_batch = azure_openai_retrieve_batch(config, provider_batch_id)
        poll_count += 1
        provider_status = provider_batch.get("status")
        if provider_status == "completed":
            result = ingest_ai_batch_results(config, batch, provider_batch)
            wait_elapsed = time.time() - started
            return {
                **result,
                "provider_status": provider_status,
                "wait_elapsed_seconds": rounded_metric(wait_elapsed),
                "poll_count": poll_count,
                "poll_interval_seconds": config["poll_interval_seconds"],
            }
        if provider_status in {"failed", "expired", "cancelled"}:
            failed_request_count = mark_batch_requests_status(batch, "failed", datetime.now(UTC))
            failed_batch = batch_row_with_provider_state(
                batch,
                status="failed",
                provider_batch=provider_batch,
                provider_metadata={"failed_request_count": failed_request_count},
                error={"provider_status": provider_status},
                completed=True,
            )
            write_ai_batch(failed_batch)
            wait_elapsed = time.time() - started
            raise RuntimeError(
                f"Azure OpenAI Batch {provider_batch_id} ended with status {provider_status} "
                f"after {round(wait_elapsed, 3)} seconds and {poll_count} polls"
            )

        write_ai_batch(
            batch_row_with_provider_state(
                batch,
                status="submitted",
                provider_batch=provider_batch,
            )
        )
        elapsed = time.time() - started
        if elapsed >= config["max_wait_seconds"]:
            write_ai_batch(
                batch_row_with_provider_state(
                    batch,
                    status="submitted",
                    provider_batch=provider_batch,
                    error={
                        "reason": "provider_batch_poll_timeout",
                        "max_wait_seconds": config["max_wait_seconds"],
                    },
                )
            )
            raise TimeoutError(
                f"Azure OpenAI Batch {provider_batch_id} did not complete within "
                f"{config['max_wait_seconds']} seconds"
            )
        time.sleep(config["poll_interval_seconds"])


def run_ai_batch_inference() -> dict:
    inference_started = time.perf_counter()
    if not azure_openai_batch_enabled():
        return {
            **batch_inference_skip_metrics(),
            "elapsed_seconds": rounded_metric(time.perf_counter() - inference_started),
        }

    config = azure_openai_batch_config()
    batches = [
        batch
        for batch in load_existing_ai_batches()
        if batch["status"] in {"ready_for_submission", "submitted"}
    ]
    if not batches:
        completed_batches = [
            batch for batch in load_existing_ai_batches() if batch["status"] == "completed"
        ]
        if completed_batches:
            elapsed = time.perf_counter() - inference_started
            return {
                "submitted_count": 0,
                "completed_count": len(completed_batches),
                "reused_completed": True,
                "elapsed_seconds": rounded_metric(elapsed),
            }
        raise ValueError("No AI batches are ready for inference. Run stage_ai_batch_payloads first.")

    submitted_count = 0
    result_summaries = []
    for batch in batches:
        active_batch = batch
        if batch["status"] == "ready_for_submission":
            active_batch = submit_ai_batch(config, batch)
            submitted_count += 1
        result_summaries.append(wait_for_ai_batch(config, active_batch))

    elapsed = time.perf_counter() - inference_started
    total_results = sum(int(summary.get("result_count") or 0) for summary in result_summaries)
    total_polls = sum(int(summary.get("poll_count") or 0) for summary in result_summaries)
    return {
        "submitted_count": submitted_count,
        "completed_count": len(result_summaries),
        "result_count": total_results,
        "elapsed_seconds": rounded_metric(elapsed),
        "results_per_second": rate_metric(total_results, elapsed),
        "poll_count": total_polls,
        "results": result_summaries,
        "ai_batches_table": AI_BATCHES_TABLE,
        "ai_results_table": AI_RESULTS_TABLE,
    }


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
    if "?" in normalized or "#" in normalized:
        raise ValueError(f"source_media.{field_name} must not include query strings or fragments")
    if normalized.startswith(("dbfs:/Volumes/", "/Volumes/")):
        return normalized
    raise ValueError(f"source_media.{field_name} must be a Unity Catalog volume path")


def validate_no_uri_credentials(uri: str, field_name: str) -> str:
    normalized = uri.strip()
    parsed = urlparse(normalized)
    if parsed.query or parsed.fragment:
        raise ValueError(f"source_media.{field_name} must not include query strings or fragments")
    if parsed.password or (parsed.scheme in {"http", "https"} and parsed.username):
        raise ValueError(f"source_media.{field_name} must not include embedded credentials")
    return normalized


def validate_cloud_uri(uri: str, field_name: str) -> str:
    normalized = validate_no_uri_credentials(uri, field_name)
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

    storage_account_url = validate_no_uri_credentials(storage_account_url, "storage_account_url")
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
    source_media_uri()


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
                "pipeline_config": safe_pipeline_config_for_persistence(),
                "source_media": safe_source_media_for_persistence(),
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
        try:
            quality = evaluate_source_quality(uri, probe)
        except QualityGateError as exc:
            register_source_file(uri, probe, exc.quality)
            raise
        register_source_file(uri, probe, quality)
        write_event(
            status="source_validated",
            message="Source media is readable by Databricks",
            source_uri=uri,
            details={"probe": probe, "quality": quality},
        )
        write_stage_run(
            stage_name=stage,
            status="completed",
            message="Source media is readable by Databricks",
            metrics={
                "bytes": probe["length"],
                "path": probe["path"],
                "duration_seconds": quality["metadata"].get("duration_seconds"),
                "video_codec": quality["metadata"].get("video_codec"),
                "audio_codec": quality["metadata"].get("audio_codec"),
                "width": quality["metadata"].get("width"),
                "height": quality["metadata"].get("height"),
                "fps": quality["metadata"].get("fps"),
                "quality_status": quality["status"],
            },
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
        if not source_has_audio():
            skip_metrics = {"skipped": True, "reason": "source_has_no_audio"}
            write_event(
                status="audio_extraction_skipped",
                message="Source media has no audio stream; skipping audio extraction",
                source_uri=uri,
                details=skip_metrics,
            )
            write_stage_run(
                stage_name=stage,
                status="completed",
                message="Audio extraction skipped because source has no audio stream",
                metrics=skip_metrics,
                completed=True,
            )
        else:
            audio_started = time.perf_counter()
            audio_asset = extract_audio_asset(uri)
            audio_chunks = build_audio_chunk_rows(audio_asset)
            register_audio_asset(audio_asset, audio_chunks)
            audio_elapsed = time.perf_counter() - audio_started
            audio_metrics = {
                "audio_asset_id": audio_asset["audio_asset_id"],
                "audio_uri": audio_asset["audio_uri"],
                "duration_seconds": audio_asset["duration_seconds"],
                "size_bytes": audio_asset["size_bytes"],
                "sample_rate_hz": audio_asset["sample_rate_hz"],
                "channels": audio_asset["channels"],
                "chunk_count": len(audio_chunks),
                "elapsed_seconds": rounded_metric(audio_elapsed),
                "audio_seconds_per_second": rate_metric(audio_asset["duration_seconds"], audio_elapsed),
                "bytes_per_second": rate_metric(audio_asset["size_bytes"], audio_elapsed),
                "chunks_per_second": rate_metric(len(audio_chunks), audio_elapsed),
            }
            write_event(
                status="audio_extracted",
                message="Audio asset extracted for faster-whisper",
                source_uri=uri,
                details=audio_metrics,
            )
            write_stage_run(
                stage_name=stage,
                status="completed",
                message="Audio asset extracted for faster-whisper",
                metrics=audio_metrics,
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
        frame_config = frame_extraction_config()
        frame_started = time.perf_counter()
        frame_assets = extract_frame_assets(uri)
        register_frame_assets(frame_assets)
        frame_elapsed = time.perf_counter() - frame_started
        frame_total_size_bytes = sum(frame["size_bytes"] for frame in frame_assets)
        frame_metrics = {
            "frame_count": len(frame_assets),
            "first_timestamp_ms": frame_assets[0]["timestamp_ms"] if frame_assets else None,
            "last_timestamp_ms": frame_assets[-1]["timestamp_ms"] if frame_assets else None,
            "frame_table": FRAME_ASSETS_TABLE,
            "total_size_bytes": frame_total_size_bytes,
            "avg_frame_size_bytes": rounded_metric(
                frame_total_size_bytes / len(frame_assets) if frame_assets else 0
            ),
            "elapsed_seconds": rounded_metric(frame_elapsed),
            "frames_per_second": rate_metric(len(frame_assets), frame_elapsed),
            "bytes_per_second": rate_metric(frame_total_size_bytes, frame_elapsed),
            "extraction_method": frame_config["method"],
            "max_frames": frame_config["max_frames"],
            "min_spacing_seconds": frame_config["min_spacing_seconds"],
            "dedupe_hashes": frame_config["dedupe_hashes"],
            "format": frame_config["format"],
            "quality": frame_config["quality"],
        }
        write_event(
            status="frames_extracted",
            message="Frame assets extracted for multimodal inference",
            source_uri=uri,
            details=frame_metrics,
        )
        write_stage_run(
            stage_name=stage,
            status="completed",
            message="Frame assets extracted for multimodal inference",
            metrics=frame_metrics,
            completed=True,
        )
    elif stage == "run_florence_frame_analysis":
        stage_message = STAGE_MESSAGES[stage]
        upsert_processing_run(
            status="running",
            progress=progress_for_stage(stage),
            current_stage=stage,
        )
        write_stage_run(stage_name=stage, status="running", message=stage_message)
        write_progress_outbox(stage, stage_message)
        florence_metrics = run_florence_frame_analysis()
        skipped = bool(florence_metrics.get("skipped"))
        write_event(
            status="florence_frame_analysis_skipped" if skipped else "florence_frame_analysis_completed",
            message="Florence-2 frame analysis skipped" if skipped else "Florence-2 frame analysis completed",
            details=florence_metrics,
        )
        write_stage_run(
            stage_name=stage,
            status="completed",
            message="Florence-2 frame analysis skipped" if skipped else "Florence-2 frame analysis completed",
            metrics=florence_metrics,
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
        model_config = faster_whisper_config()
        asr_run_id = f"{media_id}:asr:{model_config['model_name']}:{config_hash[:12]}"
        if not source_has_audio():
            skip_metrics = {"skipped": True, "reason": "source_has_no_audio"}
            write_event(
                status="asr_skipped",
                message="Source media has no audio stream; skipping ASR",
                details={"asr_run_id": asr_run_id, **skip_metrics},
            )
            write_stage_run(
                stage_name=stage,
                status="completed",
                message="ASR skipped because source has no audio stream",
                metrics={"asr_run_id": asr_run_id, **skip_metrics},
                completed=True,
            )
            continue_stage = False
        else:
            continue_stage = True

        if continue_stage:
            chunks = load_audio_chunks()
            audio_asset_id = chunks[0]["audio_asset_id"]
            asr_started_at = datetime.now(UTC)
            write_asr_run(
                asr_run_id=asr_run_id,
                audio_asset_id=audio_asset_id,
                model_config=model_config,
                status="running",
                started_at=asr_started_at,
                metrics={"chunk_count": len(chunks), "preset": model_config["preset"]},
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
                    "elapsed_seconds": rounded_metric(transcript["elapsed_seconds"]),
                    "audio_duration_seconds": rounded_metric(transcript["duration_seconds"]),
                    "real_time_factor": rounded_metric(transcript["real_time_factor"]),
                    "audio_seconds_per_second": transcript["audio_seconds_per_second"],
                    "seconds_per_chunk": rounded_metric(transcript["seconds_per_chunk"]),
                    "device": model_config["device"],
                    "compute_type": model_config["compute_type"],
                    "batch_size": model_config["batch_size"],
                    "preset": model_config["preset"],
                    "azure_openai_whisper": "disabled_for_primary_path",
                    "chunk_metrics": transcript["chunk_metrics"],
                },
            )
            write_event(
                status="asr_completed",
                message="faster-whisper ASR completed",
                details={
                    "asr_run_id": asr_run_id,
                    "audio_asset_id": audio_asset_id,
                    "model_name": model_config["model_name"],
                    "preset": model_config["preset"],
                    "segment_count": len(transcript["segments"]),
                    "language": transcript["language"],
                    "duration_seconds": transcript["duration_seconds"],
                    "elapsed_seconds": rounded_metric(transcript["elapsed_seconds"]),
                    "real_time_factor": rounded_metric(transcript["real_time_factor"]),
                    "audio_seconds_per_second": transcript["audio_seconds_per_second"],
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
                    "preset": model_config["preset"],
                    "device": model_config["device"],
                    "compute_type": model_config["compute_type"],
                    "batch_size": model_config["batch_size"],
                    "chunk_count": len(chunks),
                    "audio_duration_seconds": rounded_metric(transcript["duration_seconds"]),
                    "segment_count": len(transcript["segments"]),
                    "elapsed_seconds": rounded_metric(transcript["elapsed_seconds"]),
                    "real_time_factor": rounded_metric(transcript["real_time_factor"]),
                    "audio_seconds_per_second": transcript["audio_seconds_per_second"],
                    "seconds_per_chunk": rounded_metric(transcript["seconds_per_chunk"]),
                },
                completed=True,
            )
    elif stage == "detect_scenes_and_windows":
        stage_message = STAGE_MESSAGES[stage]
        upsert_processing_run(
            status="running",
            progress=progress_for_stage(stage),
            current_stage=stage,
        )
        write_stage_run(stage_name=stage, status="running", message=stage_message)
        write_progress_outbox(stage, stage_message)
        detection_metrics = detect_scenes_and_windows()
        write_event(
            status="scene_windows_detected",
            message="Temporal windows and scene candidates registered",
            details=detection_metrics,
        )
        write_stage_run(
            stage_name=stage,
            status="completed",
            message="Temporal windows and scene candidates registered",
            metrics=detection_metrics,
            completed=True,
        )
    elif stage == "run_databricks_scene_reasoning":
        stage_message = STAGE_MESSAGES[stage]
        upsert_processing_run(
            status="running",
            progress=progress_for_stage(stage),
            current_stage=stage,
        )
        write_stage_run(stage_name=stage, status="running", message=stage_message)
        write_progress_outbox(stage, stage_message)
        scene_metrics = run_databricks_scene_reasoning()
        skipped = bool(scene_metrics.get("skipped"))
        write_event(
            status="databricks_scene_reasoning_skipped" if skipped else "databricks_scene_reasoning_completed",
            message="Databricks Gemma 3 scene reasoning skipped"
            if skipped
            else "Databricks Gemma 3 scene reasoning completed",
            details=scene_metrics,
        )
        write_stage_run(
            stage_name=stage,
            status="completed",
            message="Databricks Gemma 3 scene reasoning skipped"
            if skipped
            else "Databricks Gemma 3 scene reasoning completed",
            metrics=scene_metrics,
            completed=True,
        )
    elif stage == "build_gold_processing_result":
        stage_message = "Building frontend-compatible Gold processing result"
        upsert_processing_run(
            status="running",
            progress=progress_for_stage(stage),
            current_stage=stage,
        )
        write_stage_run(stage_name=stage, status="running", message=stage_message)
        write_progress_outbox(stage, stage_message)
        gold_result = build_gold_processing_result()
        metrics = parse_json_dict(gold_result["metrics_json"])
        write_event(
            status="gold_processing_result_built",
            message="Gold processing result registered",
            details={
                "result_id": gold_result["result_id"],
                "status": gold_result["status"],
                "processing_results_table": GOLD_PROCESSING_RESULTS_TABLE,
                "metrics": metrics,
            },
        )
        write_stage_run(
            stage_name=stage,
            status="completed",
            message="Gold processing result registered",
            metrics={
                "result_id": gold_result["result_id"],
                "status": gold_result["status"],
                "processing_results_table": GOLD_PROCESSING_RESULTS_TABLE,
                **metrics,
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
        graph_build_started = time.perf_counter()
        graph_upserts = build_graph_upsert_rows()
        register_graph_upserts(graph_upserts)
        graph_build_elapsed = time.perf_counter() - graph_build_started
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
                "elapsed_seconds": rounded_metric(graph_build_elapsed),
                "upserts_per_second": rate_metric(len(graph_upserts), graph_build_elapsed),
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
                "elapsed_seconds": rounded_metric(graph_build_elapsed),
                "upserts_per_second": rate_metric(len(graph_upserts), graph_build_elapsed),
            },
            completed=True,
        )
    elif stage == "project_neo4j_graph":
        stage_message = STAGE_MESSAGES[stage]
        upsert_processing_run(
            status="running",
            progress=progress_for_stage(stage),
            current_stage=stage,
        )
        write_stage_run(stage_name=stage, status="running", message=stage_message)
        write_progress_outbox(stage, stage_message)
        projection_metrics = project_neo4j_graph()
        projection_skipped = bool(projection_metrics.get("skipped"))
        projection_message = (
            "Neo4j graph projection skipped"
            if projection_skipped
            else "Neo4j graph upserts applied"
        )
        write_event(
            status="neo4j_graph_skipped" if projection_skipped else "neo4j_graph_projected",
            message=projection_message,
            details={
                "applied_count": projection_metrics["applied_count"],
                "failed_count": projection_metrics["failed_count"],
                "graph_upserts_table": projection_metrics["graph_upserts_table"],
                "neo4j_database": projection_metrics.get("neo4j_database"),
                "skipped": projection_skipped,
                "skipped_reason": projection_metrics.get("skipped_reason"),
                "elapsed_seconds": projection_metrics.get("elapsed_seconds"),
                "upserts_per_second": projection_metrics.get("upserts_per_second"),
            },
        )
        write_stage_run(
            stage_name=stage,
            status="completed",
            message=projection_message,
            metrics=projection_metrics,
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
        gold_result = load_latest_gold_processing_result()
        if not gold_result:
            raise ValueError("Gold processing result is missing. Run build_gold_processing_result first.")
        processing_result = parse_json_dict(gold_result["processing_result_json"])
        video_metadata = parse_json_dict(gold_result["video_metadata_json"])
        write_event(
            status="completed",
            message="Databricks lakehouse video processing completed",
            details={
                "gold_result_id": gold_result["result_id"],
                "status": processing_result.get("status"),
                "frames_analyzed": processing_result.get("frames_analyzed"),
                "processing_results_table": GOLD_PROCESSING_RESULTS_TABLE,
            },
        )
        write_stage_run(
            stage_name=stage,
            status="completed",
            message="Databricks lakehouse video processing completed",
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
            message="Databricks lakehouse video processing completed",
            processing_result=processing_result,
            video_metadata=video_metadata,
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
        progress=progress_for_stage(stage),
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
