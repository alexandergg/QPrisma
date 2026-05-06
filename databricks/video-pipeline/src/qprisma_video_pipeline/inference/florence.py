"""Florence-2 frame analysis helpers."""

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

