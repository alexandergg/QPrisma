# Databricks notebook source
"""Minimal observable QPrisma video-processing job.

This first real pilot job validates the Service Bus -> Databricks contract,
checks that the original media can be read by Databricks compute, and writes
stage events to a Delta ops table. Heavy video stages will be added after this
end-to-end control-plane path is proven.
"""

# COMMAND ----------

from datetime import UTC, datetime
import json
import re
from urllib.parse import urlparse
from uuid import uuid4

from pyspark.sql.types import DoubleType, StringType, StructField, StructType, TimestampType

# COMMAND ----------

WIDGET_DEFAULTS = {
    "catalog": "qprisma_dev",
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


def source_media_uri() -> str:
    explicit_uri = source_media.get("abfss_uri") or source_media.get("wasbs_uri")
    if explicit_uri:
        return str(explicit_uri)

    container = str(source_media.get("container_name") or source_media.get("container") or "")
    blob = str(source_media.get("blob_name") or blob_name)
    storage_account_url = str(source_media.get("storage_account_url") or "")
    if not container or not blob or not storage_account_url:
        raise ValueError(
            "source_media must include container_name, blob_name and storage_account_url"
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
        validate_source_contract()
        write_event(
            status="running",
            message="Manifest registered",
            details={
                "pipeline_config": pipeline_config,
                "source_media": source_media,
            },
        )
    elif stage == "validate_and_probe_media":
        validate_source_contract()
        uri = source_media_uri()
        probe = probe_source_media(uri)
        write_event(
            status="source_validated",
            message="Source media is readable by Databricks",
            source_uri=uri,
            details={"probe": probe},
        )
    elif stage == "publish_outbox":
        processing_result = {
            "backend": "databricks",
            "pipeline": "minimal_pilot",
            "dispatch_id": dispatch_id,
            "stages": [
                "register_manifest",
                "validate_and_probe_media",
                "publish_outbox",
            ],
        }
        write_event(
            status="completed",
            message="Minimal Databricks pilot job completed",
            details={
                "next": "Replace pilot stages with medallion video processing tasks",
                "processing_result": processing_result,
            },
        )
        write_outbox_event(
            status="completed",
            progress=1.0,
            message="Minimal Databricks pilot job completed",
            processing_result=processing_result,
        )
    else:
        raise ValueError(f"Unsupported pipeline stage: {stage}")
except Exception as exc:
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
