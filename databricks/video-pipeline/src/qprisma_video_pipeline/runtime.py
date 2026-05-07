"""Databricks runtime bootstrap and shared namespace binding."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from types import ModuleType
from typing import Any

from . import (
    audio,
    config,
    contracts,
    ffmpeg,
    frames,
    gold,
    graph,
    observability,
    quality,
    scenes,
    source_media,
    stage_utils,
    stages,
    storage_paths,
    tables,
)
from .inference import config as inference_config, florence

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

RUNTIME_MODULES: tuple[ModuleType, ...] = (
    config,
    tables,
    observability,
    storage_paths,
    ffmpeg,
    quality,
    source_media,
    audio,
    frames,
    inference_config,
    florence,
    scenes,
    gold,
    graph,
    stage_utils,
    stages,
)


def widget(dbutils: Any, name: str, *, required: bool = False) -> str:
    value = dbutils.widgets.get(name).strip()
    if required and not value:
        raise ValueError(f"Required Databricks job parameter '{name}' is missing")
    return value


def quote_identifier(value: str) -> str:
    if not contracts.IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"Invalid Unity Catalog identifier: {value}")
    return f"`{value}`"


def qualified_table_names(catalog: str, schema: str) -> dict[str, str]:
    def qualify(table_name: str) -> str:
        return f"{quote_identifier(catalog)}.{quote_identifier(schema)}.{quote_identifier(table_name)}"

    return {
        "qualified_ops_table": qualify(contracts.OPS_EVENTS_TABLE),
        "qualified_outbox_table": qualify(contracts.OPS_OUTBOX_TABLE),
        "qualified_manifest_table": qualify(contracts.MEDIA_MANIFEST_TABLE),
        "qualified_source_files_table": qualify(contracts.SOURCE_FILES_TABLE),
        "qualified_runs_table": qualify(contracts.PROCESSING_RUNS_TABLE),
        "qualified_stage_runs_table": qualify(contracts.STAGE_RUNS_TABLE),
        "qualified_quarantine_table": qualify(contracts.QUARANTINE_TABLE),
        "qualified_audio_assets_table": qualify(contracts.AUDIO_ASSETS_TABLE),
        "qualified_audio_chunks_table": qualify(contracts.AUDIO_CHUNKS_TABLE),
        "qualified_asr_runs_table": qualify(contracts.ASR_RUNS_TABLE),
        "qualified_transcript_segments_table": qualify(contracts.TRANSCRIPT_SEGMENTS_TABLE),
        "qualified_frame_assets_table": qualify(contracts.FRAME_ASSETS_TABLE),
        "qualified_frame_analysis_table": qualify(contracts.FRAME_ANALYSIS_TABLE),
        "qualified_temporal_windows_table": qualify(contracts.TEMPORAL_WINDOWS_TABLE),
        "qualified_scene_candidates_table": qualify(contracts.SCENE_CANDIDATES_TABLE),
        "qualified_scene_visual_analysis_table": qualify(contracts.SCENE_VISUAL_ANALYSIS_TABLE),
        "qualified_model_inference_runs_table": qualify(contracts.MODEL_INFERENCE_RUNS_TABLE),
        "qualified_gold_processing_results_table": qualify(contracts.GOLD_PROCESSING_RESULTS_TABLE),
        "qualified_graph_upserts_table": qualify(contracts.GRAPH_UPSERTS_TABLE),
    }


def public_namespace() -> dict[str, Any]:
    namespace: dict[str, Any] = {}
    for source_module in (contracts, *RUNTIME_MODULES):
        namespace.update(
            {
                name: value
                for name, value in vars(source_module).items()
                if not name.startswith("_")
            }
        )
    namespace["quote_identifier"] = quote_identifier
    return namespace


def bind_namespace(namespace: dict[str, Any]) -> None:
    for target_module in RUNTIME_MODULES:
        target_module.__dict__.update(namespace)


def initialize_runtime(spark: Any, dbutils: Any) -> dict[str, Any]:
    for widget_name, default_value in WIDGET_DEFAULTS.items():
        dbutils.widgets.text(widget_name, default_value)

    catalog = widget(dbutils, "catalog", required=True)
    schema = widget(dbutils, "schema", required=True)
    queue_name = widget(dbutils, "queue_name", required=True)
    stage = widget(dbutils, "stage", required=True)
    schema_version = widget(dbutils, "schema_version", required=True)
    dispatch_id = widget(dbutils, "dispatch_id", required=True)
    media_id = widget(dbutils, "media_id", required=True)
    blob_name = widget(dbutils, "blob_name", required=True)
    user_id = widget(dbutils, "user_id")
    source_media_raw = widget(dbutils, "source_media", required=True)
    pipeline_config_raw = widget(dbutils, "pipeline_config")

    source_media = config.parse_json_object(source_media_raw, "source_media")
    pipeline_config = config.parse_json_object(pipeline_config_raw, "pipeline_config")
    config.validate_no_raw_secrets(source_media, "source_media")
    config.validate_no_raw_secrets(pipeline_config)
    processing_version = str(pipeline_config.get("processing_version") or schema_version)
    config_hash = hashlib.sha256(
        json.dumps(pipeline_config, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()

    namespace = public_namespace()
    namespace.update(
        {
            "spark": spark,
            "dbutils": dbutils,
            "catalog": catalog,
            "schema": schema,
            "queue_name": queue_name,
            "stage": stage,
            "schema_version": schema_version,
            "dispatch_id": dispatch_id,
            "media_id": media_id,
            "blob_name": blob_name,
            "user_id": user_id,
            "source_media_raw": source_media_raw,
            "pipeline_config_raw": pipeline_config_raw,
            "source_media": source_media,
            "pipeline_config": pipeline_config,
            "run_id": dispatch_id,
            "processing_version": processing_version,
            "config_hash": config_hash,
        }
    )
    namespace.update(qualified_table_names(catalog, schema))
    bind_namespace(namespace)
    return namespace


def bundle_src_path(dbutils: Any) -> str:
    context = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
    notebook_path = context.notebookPath().get()
    notebook_dir = os.path.dirname(notebook_path)
    return os.path.normpath(os.path.join("/Workspace", notebook_dir.lstrip("/"), "..", "src"))


def ensure_bundle_src_on_path(dbutils: Any) -> None:
    src_path = bundle_src_path(dbutils)
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
