"""FFmpeg and FFprobe execution helpers."""

from __future__ import annotations

import os
import subprocess
import tempfile

from .contracts import *


def ffmpeg_input_path(uri: str) -> str:
    if uri.startswith("/Volumes/"):
        return uri
    if uri.startswith("dbfs:/Volumes/"):
        return uri.replace("dbfs:", "", 1)

    suffix = os.path.splitext(blob_name)[1] or ".mp4"
    local_dir = tempfile.mkdtemp(prefix="qprisma_video_")
    local_path = os.path.join(local_dir, f"{safe_path_segment(media_id)}{suffix}")
    dbutils.fs.cp(uri, f"file:{local_path}")
    return local_path


def run_command(command: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(command, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise RuntimeError(f"Command failed: {' '.join(command)}\n{stderr}") from exc
