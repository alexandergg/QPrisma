"""Delta table creation and schema migration helpers."""

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

def ensure_table_columns(table_name: str, columns: dict[str, str]) -> None:
    existing_columns = set(spark.table(table_name).columns)
    for column_name, column_type in columns.items():
        if column_name not in existing_columns:
            spark.sql(f"ALTER TABLE {table_name} ADD COLUMNS ({column_name} {column_type})")


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
