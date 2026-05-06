"""Delta contracts, stage metadata, and validation constants."""

from __future__ import annotations

import re

from pyspark.sql.types import (
    DoubleType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

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

