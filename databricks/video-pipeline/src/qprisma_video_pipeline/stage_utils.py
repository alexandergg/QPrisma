"""Shared observable stage helpers."""

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

from .contracts import *

def complete_observable_stage(
    *,
    stage_name: str,
    message: str,
    metrics: dict | None = None,
    event_status: str = "completed",
) -> None:
    upsert_processing_run(
        status="running",
        progress=progress_for_stage(stage_name),
        current_stage=stage_name,
    )
    write_stage_run(stage_name=stage_name, status="running", message=STAGE_MESSAGES[stage_name])
    write_progress_outbox(stage_name, STAGE_MESSAGES[stage_name])
    write_event(status=event_status, message=message, details=metrics or {})
    write_stage_run(
        stage_name=stage_name,
        status="completed",
        message=message,
        metrics=metrics or {},
        completed=True,
    )


