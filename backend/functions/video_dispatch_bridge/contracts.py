from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


class PayloadValidationError(ValueError):
    """Raised when a Service Bus message does not match the dispatch contract."""


@dataclass(frozen=True)
class VideoDispatchPayload:
    schema_version: str
    dispatch_id: str
    media_id: str
    blob_name: str
    source_media: dict[str, Any]
    user_id: str | None
    pipeline_config: dict[str, Any]
    databricks: dict[str, Any]

    @classmethod
    def from_json(cls, raw_body: bytes | str) -> VideoDispatchPayload:
        try:
            decoded = raw_body.decode("utf-8") if isinstance(raw_body, bytes) else raw_body
            payload = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PayloadValidationError("Message body must be valid UTF-8 JSON") from exc

        if not isinstance(payload, dict):
            raise PayloadValidationError("Message body must be a JSON object")

        required_string_fields = ("schema_version", "dispatch_id", "media_id", "blob_name")
        missing = [
            field
            for field in required_string_fields
            if not isinstance(payload.get(field), str) or not payload[field].strip()
        ]
        if missing:
            raise PayloadValidationError(f"Missing required string fields: {', '.join(missing)}")

        source_media = payload.get("source_media")
        if not isinstance(source_media, dict):
            raise PayloadValidationError("source_media must be an object")
        _require_source_media(source_media)

        databricks = payload.get("databricks")
        if not isinstance(databricks, dict):
            raise PayloadValidationError("databricks must be an object")

        pipeline_config = payload.get("pipeline_config") or {}
        if not isinstance(pipeline_config, dict):
            raise PayloadValidationError("pipeline_config must be an object when provided")

        user_id = payload.get("user_id")
        if user_id is not None and not isinstance(user_id, str):
            raise PayloadValidationError("user_id must be a string when provided")

        return cls(
            schema_version=payload["schema_version"],
            dispatch_id=payload["dispatch_id"],
            media_id=payload["media_id"],
            blob_name=payload["blob_name"],
            source_media=source_media,
            user_id=user_id,
            pipeline_config=pipeline_config,
            databricks=databricks,
        )

    def databricks_parameters(self, default_job_id: str) -> dict[str, Any]:
        job_id = str(self.databricks.get("video_job_id") or default_job_id).strip()
        if not job_id:
            raise PayloadValidationError("Databricks job ID is required")

        return {
            "job_id": job_id,
            "idempotency_token": self.dispatch_id,
            "job_parameters": {
                "schema_version": self.schema_version,
                "dispatch_id": self.dispatch_id,
                "media_id": self.media_id,
                "blob_name": self.blob_name,
                "user_id": self.user_id or "",
                "source_media": json.dumps(self.source_media, separators=(",", ":")),
                "pipeline_config": json.dumps(self.pipeline_config, separators=(",", ":")),
            },
        }


@dataclass(frozen=True)
class DatabricksStatusEvent:
    schema_version: str
    media_id: str
    dispatch_id: str
    status: str
    progress: float
    message: str
    processing_result: dict[str, Any]
    video_metadata: dict[str, Any]
    error: dict[str, Any]

    @classmethod
    def from_json(cls, raw_body: bytes | str) -> DatabricksStatusEvent:
        try:
            decoded = raw_body.decode("utf-8") if isinstance(raw_body, bytes) else raw_body
            payload = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PayloadValidationError("Status event body must be valid UTF-8 JSON") from exc

        if not isinstance(payload, dict):
            raise PayloadValidationError("Status event body must be a JSON object")

        missing = [
            field
            for field in ("schema_version", "media_id", "dispatch_id", "status", "message")
            if not isinstance(payload.get(field), str) or not payload[field].strip()
        ]
        if missing:
            raise PayloadValidationError(f"Missing status event fields: {', '.join(missing)}")

        status = payload["status"]
        if status not in {"running", "completed", "failed"}:
            raise PayloadValidationError("status must be one of: running, completed, failed")

        progress = payload.get("progress", 0.0)
        if isinstance(progress, bool) or not isinstance(progress, int | float):
            raise PayloadValidationError("progress must be a number between 0.0 and 1.0")
        if not 0.0 <= float(progress) <= 1.0:
            raise PayloadValidationError("progress must be a number between 0.0 and 1.0")

        processing_result = _json_object_field(payload, "processing_result")
        video_metadata = _json_object_field(payload, "video_metadata")
        error = _json_object_field(payload, "error")

        return cls(
            schema_version=payload["schema_version"],
            media_id=payload["media_id"],
            dispatch_id=payload["dispatch_id"],
            status=status,
            progress=float(progress),
            message=payload["message"],
            processing_result=processing_result,
            video_metadata=video_metadata,
            error=error,
        )


def _require_source_media(source_media: dict[str, Any]) -> None:
    has_explicit_path = any(
        isinstance(source_media.get(field), str) and source_media[field].strip()
        for field in ("volume_path", "uri", "abfss_uri", "wasbs_uri")
    )
    if not has_explicit_path:
        required = ("storage_account_url", "container_name", "blob_name", "blob_url")
        missing = [
            field
            for field in required
            if not isinstance(source_media.get(field), str) or not source_media[field].strip()
        ]
        if missing:
            raise PayloadValidationError(f"Missing source_media fields: {', '.join(missing)}")

    auth = source_media.get("auth")
    if not isinstance(auth, dict) or auth.get("mode") != "managed_identity":
        raise PayloadValidationError("source_media.auth.mode must be managed_identity")


def _json_object_field(payload: dict[str, Any], field: str) -> dict[str, Any]:
    value = payload.get(field) or {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise PayloadValidationError(f"{field} must be a JSON object") from exc
    if not isinstance(value, dict):
        raise PayloadValidationError(f"{field} must be a JSON object")
    return value
