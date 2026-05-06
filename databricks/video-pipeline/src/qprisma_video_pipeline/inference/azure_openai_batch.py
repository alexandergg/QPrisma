"""Azure OpenAI batch request staging, submission, polling, and ingestion helpers."""

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

from ..contracts import *

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

