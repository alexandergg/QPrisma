from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json

if __package__:
    from .contracts import DatabricksStatusEvent, VideoDispatchPayload
else:
    from contracts import DatabricksStatusEvent, VideoDispatchPayload


class DispatchStateError(RuntimeError):
    """Raised when dispatch state cannot be read or written safely."""


@dataclass(frozen=True)
class ExistingRun:
    databricks_run_id: int


@dataclass(frozen=True)
class ExistingStagedSourceMedia:
    volume_path: str


class PostgresDispatchStateStore:
    def __init__(self, database_url: str | None) -> None:
        if not database_url:
            raise DispatchStateError("DATABASE_URL is required for dispatch state projection")
        self._database_url = database_url

    def get_existing_run(self, payload: VideoDispatchPayload) -> ExistingRun | None:
        with psycopg2.connect(self._database_url) as conn, conn.cursor() as cursor:
            cursor.execute("SELECT pipeline_config FROM media WHERE id = %s", (payload.media_id,))
            row = cursor.fetchone()

        if row is None:
            raise DispatchStateError(f"Media row {payload.media_id} was not found")

        pipeline_config = _as_dict(row[0])
        dispatch = pipeline_config.get("dispatch")
        if not isinstance(dispatch, dict):
            return None

        if dispatch.get("dispatch_id") != payload.dispatch_id:
            return None

        run_id = dispatch.get("databricks_run_id")
        return ExistingRun(run_id) if isinstance(run_id, int) else None

    def get_staged_source_media(
        self, payload: VideoDispatchPayload
    ) -> ExistingStagedSourceMedia | None:
        with psycopg2.connect(self._database_url) as conn, conn.cursor() as cursor:
            cursor.execute("SELECT pipeline_config FROM media WHERE id = %s", (payload.media_id,))
            row = cursor.fetchone()

        if row is None:
            raise DispatchStateError(f"Media row {payload.media_id} was not found")

        pipeline_config = _as_dict(row[0])
        dispatch = _as_dict(pipeline_config.get("dispatch"))
        if dispatch.get("dispatch_id") != payload.dispatch_id:
            return None

        source_media = _as_dict(dispatch.get("source_media"))
        volume_path = source_media.get("volume_path")
        if not isinstance(volume_path, str) or not volume_path.strip():
            staging = _as_dict(dispatch.get("staging"))
            volume_path = staging.get("volume_path")
        return (
            ExistingStagedSourceMedia(volume_path.strip())
            if isinstance(volume_path, str) and volume_path.strip()
            else None
        )

    def mark_source_media_staged(
        self, payload: VideoDispatchPayload, source_media: dict[str, Any]
    ) -> None:
        volume_path = source_media.get("volume_path")
        if not isinstance(volume_path, str) or not volume_path.strip():
            raise DispatchStateError(
                "Cannot mark source media staged without source_media.volume_path"
            )

        with psycopg2.connect(self._database_url) as conn, conn.cursor() as cursor:
            cursor.execute("SELECT pipeline_config FROM media WHERE id = %s", (payload.media_id,))
            row = cursor.fetchone()
            if row is None:
                raise DispatchStateError(f"Media row {payload.media_id} was not found")

            pipeline_config = _as_dict(row[0])
            dispatch = _as_dict(pipeline_config.get("dispatch"))
            existing_dispatch_id = dispatch.get("dispatch_id")
            if existing_dispatch_id and existing_dispatch_id != payload.dispatch_id:
                raise DispatchStateError(
                    f"Staging dispatch_id does not match media row {payload.media_id}"
                )

            staging = _as_dict(source_media.get("staging"))
            dispatch.update(
                {
                    "backend": "databricks",
                    "dispatch_id": payload.dispatch_id,
                    "source_media": source_media,
                    "staging": staging
                    or {
                        "status": "completed",
                        "volume_path": volume_path,
                        "completed_at": datetime.now(UTC).isoformat(),
                    },
                }
            )
            pipeline_config["dispatch"] = dispatch

            cursor.execute(
                """
                UPDATE media
                SET pipeline_config = %s,
                    processing_method = %s,
                    last_updated = %s
                WHERE id = %s
                """,
                (
                    Json(pipeline_config),
                    "databricks",
                    datetime.now(UTC),
                    payload.media_id,
                ),
            )
            if cursor.rowcount != 1:
                raise DispatchStateError(f"Failed to update media row {payload.media_id}")

    def mark_run_started(self, payload: VideoDispatchPayload, databricks_run_id: int) -> None:
        with psycopg2.connect(self._database_url) as conn, conn.cursor() as cursor:
            cursor.execute("SELECT pipeline_config FROM media WHERE id = %s", (payload.media_id,))
            row = cursor.fetchone()
            if row is None:
                raise DispatchStateError(f"Media row {payload.media_id} was not found")

            pipeline_config = _as_dict(row[0])
            dispatch = _as_dict(pipeline_config.get("dispatch"))
            dispatch.update(
                {
                    "backend": "databricks",
                    "dispatch_id": payload.dispatch_id,
                    "databricks_run_id": databricks_run_id,
                    "databricks_run_started_at": datetime.now(UTC).isoformat(),
                }
            )
            pipeline_config["dispatch"] = dispatch

            cursor.execute(
                """
                UPDATE media
                SET pipeline_config = %s,
                    processing_status = %s,
                    processing_message = %s,
                    processing_progress = %s,
                    last_updated = %s
                WHERE id = %s
                """,
                (
                    Json(pipeline_config),
                    "running",
                    "Databricks run started",
                    0.05,
                    datetime.now(UTC),
                    payload.media_id,
                ),
            )
            if cursor.rowcount != 1:
                raise DispatchStateError(f"Failed to update media row {payload.media_id}")

    def apply_status_event(self, event: DatabricksStatusEvent) -> None:
        with psycopg2.connect(self._database_url) as conn, conn.cursor() as cursor:
            cursor.execute("SELECT pipeline_config FROM media WHERE id = %s", (event.media_id,))
            row = cursor.fetchone()
            if row is None:
                raise DispatchStateError(f"Media row {event.media_id} was not found")

            pipeline_config = _as_dict(row[0])
            dispatch = _as_dict(pipeline_config.get("dispatch"))
            existing_dispatch_id = dispatch.get("dispatch_id")
            if existing_dispatch_id and existing_dispatch_id != event.dispatch_id:
                raise DispatchStateError(
                    f"Status event dispatch_id does not match media row {event.media_id}"
                )

            dispatch.update(
                {
                    "backend": "databricks",
                    "dispatch_id": event.dispatch_id,
                    "databricks_status": event.status,
                    "databricks_status_message": event.message,
                    "databricks_status_updated_at": datetime.now(UTC).isoformat(),
                }
            )
            if event.error:
                dispatch["error"] = event.error
            pipeline_config["dispatch"] = dispatch

            updates = _media_updates_for_status_event(event, pipeline_config)
            assignments = sql.SQL(", ").join(
                sql.SQL("{} = %s").format(sql.Identifier(column)) for column in updates
            )
            cursor.execute(
                sql.SQL("UPDATE media SET {}, last_updated = %s WHERE id = %s").format(assignments),
                (*updates.values(), datetime.now(UTC), event.media_id),
            )
            if cursor.rowcount != 1:
                raise DispatchStateError(f"Failed to update media row {event.media_id}")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _media_updates_for_status_event(
    event: DatabricksStatusEvent, pipeline_config: dict[str, Any]
) -> dict[str, Any]:
    if event.status == "completed":
        updates: dict[str, Any] = {
            "pipeline_config": Json(pipeline_config),
            "processing_status": "completed",
            "processing_message": event.message,
            "processing_progress": 1.0,
            "processed": True,
            "processing_method": "databricks",
            "processing_result": Json(event.processing_result),
        }
        if event.video_metadata:
            updates["video_metadata"] = Json(event.video_metadata)
        audio_data = event.processing_result.get("audio_data")
        if isinstance(audio_data, dict):
            updates["audio_data"] = Json(audio_data)
        return updates

    if event.status == "failed":
        return {
            "pipeline_config": Json(pipeline_config),
            "processing_status": "failed",
            "processing_message": "Databricks video pipeline failed",
            "processing_progress": event.progress,
            "processed": False,
            "processing_method": "databricks",
        }

    return {
        "pipeline_config": Json(pipeline_config),
        "processing_status": "running",
        "processing_message": event.message,
        "processing_progress": event.progress,
        "processed": False,
        "processing_method": "databricks",
    }
