from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class BridgeSettings:
    databricks_workspace_url: str
    databricks_video_job_id: str
    databricks_auth_type: str
    databricks_client_id: str | None
    databricks_client_secret: str | None
    databricks_token: str | None
    databricks_sql_warehouse_id: str | None
    databricks_outbox_catalog: str
    databricks_outbox_schema: str
    databricks_outbox_table: str
    databricks_outbox_poll_batch_size: int
    database_url: str | None
    http_timeout_seconds: float

    @classmethod
    def from_environment(cls) -> BridgeSettings:
        return cls(
            databricks_workspace_url=_required("DATABRICKS_WORKSPACE_URL"),
            databricks_video_job_id=os.environ.get("DATABRICKS_VIDEO_JOB_ID", "").strip(),
            databricks_auth_type=os.environ.get("DATABRICKS_AUTH_TYPE", "oauth_m2m").strip(),
            databricks_client_id=_optional("DATABRICKS_CLIENT_ID"),
            databricks_client_secret=_optional("DATABRICKS_CLIENT_SECRET"),
            databricks_token=_optional("DATABRICKS_TOKEN"),
            databricks_sql_warehouse_id=_optional("DATABRICKS_SQL_WAREHOUSE_ID"),
            databricks_outbox_catalog=os.environ.get(
                "DATABRICKS_OUTBOX_CATALOG", "dbw_qprisma_dev"
            ).strip(),
            databricks_outbox_schema=os.environ.get("DATABRICKS_OUTBOX_SCHEMA", "video").strip(),
            databricks_outbox_table=os.environ.get(
                "DATABRICKS_OUTBOX_TABLE", "video_pipeline_outbox"
            ).strip(),
            databricks_outbox_poll_batch_size=_positive_int(
                "DATABRICKS_OUTBOX_POLL_BATCH_SIZE", default=25
            ),
            database_url=_optional("DATABASE_URL"),
            http_timeout_seconds=float(os.environ.get("DATABRICKS_HTTP_TIMEOUT_SECONDS", "30")),
        )


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _optional(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def _positive_int(name: str, *, default: int) -> int:
    raw_value = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < 1:
        raise ValueError(f"{name} must be greater than zero")
    return value
