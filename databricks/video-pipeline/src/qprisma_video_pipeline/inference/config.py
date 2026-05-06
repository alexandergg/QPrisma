"""Model routing and inference-mode configuration helpers."""

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

def pipeline_models_config() -> dict:
    """Return model routing config for the pipeline.

    Model routing rules:
    - ``vision`` / ``summary``: used for Azure OpenAI Batch API requests. Defaults to
      ``gpt-5.1-batch`` which is the only batch-capable deployment available.
    - ``direct``: used for synchronous / non-batch LLM calls. Defaults to ``gpt-5.5``.

    Callers should use ``models["vision"]`` and ``models["summary"]`` for batch
    inference requests and ``models["direct"]`` for any real-time / conversational
    calls so that the correct deployment endpoint is always targeted.
    """
    models = pipeline_config.get("models") or {}
    if not isinstance(models, dict):
        raise ValueError("pipeline_config.models must be an object when provided")
    return {
        "vision": str(models.get("vision") or pipeline_config.get("vision_model") or "gpt-5.1-batch"),
        "summary": str(models.get("summary") or pipeline_config.get("summary_model") or "gpt-5.1-batch"),
        "direct": str(models.get("direct") or pipeline_config.get("direct_model") or "gpt-5.5"),
        "prompt_version": str(pipeline_config.get("prompt_version") or schema_version),
    }


def inference_mode_config() -> dict:
    cfg = pipeline_config.get("inference") or {}
    if cfg and not isinstance(cfg, dict):
        raise ValueError("pipeline_config.inference must be an object when provided")
    mode = str(cfg.get("mode") or pipeline_config.get("inference_mode") or "local_databricks").strip().lower()
    supported_modes = {"local_databricks"}
    if mode not in supported_modes:
        raise ValueError("pipeline_config.inference.mode must be local_databricks for this Databricks DAG")
    return {"mode": mode}


def azure_openai_batch_enabled() -> bool:
    return inference_mode_config()["mode"] == "batch_cost"


def batch_inference_skip_metrics() -> dict:
    mode = inference_mode_config()["mode"]
    return {
        "skipped": True,
        "skipped_reason": f"inference_mode_{mode}_does_not_use_azure_openai_batch",
        "inference_mode": mode,
        "ai_batches_table": AI_BATCHES_TABLE,
        "ai_results_table": AI_RESULTS_TABLE,
    }

