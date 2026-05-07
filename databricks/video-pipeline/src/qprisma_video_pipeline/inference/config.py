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

def inference_mode_config() -> dict:
    cfg = pipeline_config.get("inference") or {}
    if cfg and not isinstance(cfg, dict):
        raise ValueError("pipeline_config.inference must be an object when provided")
    mode = str(cfg.get("mode") or pipeline_config.get("inference_mode") or "local_databricks").strip().lower()
    supported_modes = {"local_databricks"}
    if mode not in supported_modes:
        raise ValueError("pipeline_config.inference.mode must be local_databricks for this Databricks DAG")
    return {"mode": mode}
