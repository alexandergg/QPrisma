"""Validation helpers for staged Video-MME dataset files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PARQUET_MAGIC = b"PAR1"
_SNIFF_BYTES = 256
_PRINTABLE_SAMPLE_BYTES = 120
_HTML_OR_XML_PREFIXES = (b"<!doctype html", b"<html", b"<?xml", b"<error")


@dataclass(frozen=True)
class FileInspection:
    """Small diagnostic summary for a staged dataset file."""

    size_bytes: int
    detected_format: str
    sample_text: str


def _read_head_tail(path: Path) -> tuple[bytes, bytes, int]:
    size_bytes = path.stat().st_size
    with path.open("rb") as fh:
        head = fh.read(_SNIFF_BYTES)
        tail = b""
        if size_bytes >= len(PARQUET_MAGIC):
            fh.seek(size_bytes - len(PARQUET_MAGIC))
            tail = fh.read(len(PARQUET_MAGIC))
    return head, tail, size_bytes


def _render_sample_text(data: bytes) -> str:
    if not data:
        return ""
    text = data[:_PRINTABLE_SAMPLE_BYTES].decode("utf-8", errors="replace")
    return " ".join(text.split())


def inspect_staged_file(path: Path) -> FileInspection:
    """Return a lightweight signature for the staged file."""

    head, tail, size_bytes = _read_head_tail(path)
    stripped = head.lstrip().lower()

    if size_bytes == 0:
        detected_format = "empty"
    elif head[: len(PARQUET_MAGIC)] == PARQUET_MAGIC and tail == PARQUET_MAGIC:
        detected_format = "parquet"
    elif stripped.startswith(_HTML_OR_XML_PREFIXES):
        detected_format = "html_or_xml"
    elif stripped.startswith((b"{", b"[")):
        detected_format = "json_like"
    else:
        try:
            stripped.decode("utf-8")
        except UnicodeDecodeError:
            detected_format = "binary"
        else:
            detected_format = "text"

    return FileInspection(
        size_bytes=size_bytes,
        detected_format=detected_format,
        sample_text=_render_sample_text(head),
    )


def _sample_suffix(inspection: FileInspection) -> str:
    if not inspection.sample_text:
        return ""
    return f" First bytes: {inspection.sample_text!r}."


def _invalid_payload_message(path: Path, *, label: str, expected_format: str) -> str:
    inspection = inspect_staged_file(path)
    return (
        f"{label} at {path} does not look like {expected_format}. "
        f"Detected {inspection.detected_format} content ({inspection.size_bytes} bytes)."
        f"{_sample_suffix(inspection)} "
        "This usually means the URL returned an HTML/XML error page or another indirect response "
        "instead of the raw dataset file, such as an expired SAS URL or a Hugging Face page URL "
        "instead of a direct download URL."
    )


def build_parquet_read_error(path: Path, *, label: str, detail: str) -> str:
    """Build a consistent error message for parquet parse failures."""

    inspection = inspect_staged_file(path)
    return (
        f"Failed to read {label} parquet at {path}: {detail}. "
        f"Detected {inspection.detected_format} content ({inspection.size_bytes} bytes)."
        f"{_sample_suffix(inspection)} "
        "If this file came from automation, confirm the download URL points to the raw parquet bytes "
        "and that the upload or download was not truncated."
    )


def validate_staged_dataset_file(path: Path, *, label: str) -> FileInspection:
    """Fail fast when a staged dataset file clearly is not what its suffix claims."""

    inspection = inspect_staged_file(path)
    suffix = path.suffix.lower()

    if inspection.size_bytes == 0:
        raise RuntimeError(f"{label} at {path} is empty.")

    if suffix == ".parquet" and inspection.detected_format != "parquet":
        raise RuntimeError(_invalid_payload_message(path, label=label, expected_format="parquet"))

    if suffix in {".json", ".jsonl", ".csv"} and inspection.detected_format == "html_or_xml":
        raise RuntimeError(_invalid_payload_message(path, label=label, expected_format=suffix[1:]))

    return inspection
