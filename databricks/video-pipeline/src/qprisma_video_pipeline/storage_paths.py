"""Artifact path helpers and local-to-volume copy utilities."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
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

def safe_path_segment(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return normalized.strip("._") or "unknown"


def volume_path(*parts: str) -> str:
    safe_parts = [safe_path_segment(part) for part in parts if part]
    return "/".join([f"/Volumes/{catalog}/{schema}/video_artifacts", *safe_parts])


def local_artifact_path(*parts: str) -> str:
    safe_parts = [safe_path_segment(part) for part in parts if part]
    return os.path.join(tempfile.gettempdir(), "qprisma-video-pipeline", *safe_parts)


def copy_local_file_to_volume(local_path: str, destination: str) -> None:
    dbutils.fs.mkdirs(os.path.dirname(destination))
    try:
        dbutils.fs.rm(destination)
    except Exception as exc:
        if "FileNotFound" not in str(exc) and "does not exist" not in str(exc):
            raise
    dbutils.fs.cp(f"file:{local_path}", destination)


