# Databricks notebook source
"""Minimal observable QPrisma video-processing job.

This first real pilot job validates the Service Bus -> Databricks contract,
checks that the original media can be read by Databricks compute, and writes
stage events to a Delta ops table. Heavy video stages will be added after this
end-to-end control-plane path is proven.
"""

# COMMAND ----------

from datetime import UTC, datetime
import hashlib
import json
import re
from urllib.parse import urlparse
from uuid import uuid4

from pyspark.sql.types import DoubleType, LongType, StringType, StructField, StructType, TimestampType

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

STAGE_PROGRESS = {
    "register_manifest": 0.10,
    "validate_and_probe_media": 0.20,
    "publish_outbox": 1.00,
}
STAGE_MESSAGES = {
    "register_manifest": "Registering video manifest in Databricks",
    "validate_and_probe_media": "Validating staged source media in Databricks",
    "publish_outbox": "Publishing Databricks pilot result",
}
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


def json_dumps(value: dict) -> str:
    return json.dumps(value or {}, separators=(",", ":"), sort_keys=True)


def merge_row(table_name: str, row: dict, row_schema: StructType, key_columns: list[str]) -> None:
    temp_view = f"merge_{uuid4().hex}"
    spark.createDataFrame([row], schema=row_schema).createOrReplaceTempView(temp_view)
    on_clause = " AND ".join(f"target.{key} = source.{key}" for key in key_columns)
    update_clause = ", ".join(f"target.{field.name} = source.{field.name}" for field in row_schema)
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
            "stages": [
                "register_manifest",
                "validate_and_probe_media",
                "publish_outbox",
            ],
            "delta_tables": {
                "manifest": MEDIA_MANIFEST_TABLE,
                "source_files": SOURCE_FILES_TABLE,
                "processing_runs": PROCESSING_RUNS_TABLE,
                "stage_runs": STAGE_RUNS_TABLE,
                "events": OPS_EVENTS_TABLE,
                "outbox": OPS_OUTBOX_TABLE,
                "quarantine": QUARANTINE_TABLE,
            },
            "next": [
                "extract_audio_assets",
                "extract_frame_assets",
                "run_faster_whisper_asr",
                "build_multimodal_inference_requests",
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
