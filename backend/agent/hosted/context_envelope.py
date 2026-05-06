"""Shared QPrisma context envelope helpers for hosted-agent requests."""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

from core.legacy_usage import record_legacy_usage

logger = logging.getLogger(__name__)

CONTEXT_PREFIX_B64 = "[QPRISMA_CONTEXT_B64:"
CONTEXT_PREFIX_LEGACY = "[QPRISMA_CONTEXT:"


def format_qprisma_context(metadata: dict[str, Any], message: str) -> str:
    """Prepend a robust base64url-encoded QPrisma context envelope."""
    if not metadata:
        return message

    payload = json.dumps(metadata, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    return f"{CONTEXT_PREFIX_B64}{encoded}]\n{message}"


def extract_qprisma_context(text: str) -> tuple[dict[str, Any], str]:
    """Extract QPrisma context metadata from new or legacy envelope formats."""
    if text.startswith(CONTEXT_PREFIX_B64):
        return _extract_base64_context(text)
    if text.startswith(CONTEXT_PREFIX_LEGACY):
        return _extract_legacy_context(text)
    return {}, text


def _extract_base64_context(text: str) -> tuple[dict[str, Any], str]:
    end_idx = text.find("]", len(CONTEXT_PREFIX_B64))
    if end_idx == -1:
        logger.warning("QPRISMA_CONTEXT_B64 prefix found but terminator is missing")
        return {}, text

    encoded = text[len(CONTEXT_PREFIX_B64) : end_idx]
    try:
        padding = "=" * (-len(encoded) % 4)
        decoded = base64.urlsafe_b64decode(f"{encoded}{padding}").decode("utf-8")
        metadata = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("QPRISMA_CONTEXT_B64 prefix found but payload is malformed: %s", exc)
        return {}, text

    if not isinstance(metadata, dict):
        logger.warning("QPRISMA_CONTEXT_B64 payload is not an object")
        return {}, text

    return metadata, _strip_single_newline(text[end_idx + 1 :])


def _extract_legacy_context(text: str) -> tuple[dict[str, Any], str]:
    payload_start = len(CONTEXT_PREFIX_LEGACY)
    try:
        metadata, payload_end = json.JSONDecoder().raw_decode(text[payload_start:])
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("QPRISMA_CONTEXT prefix found but JSON is malformed: %s", exc)
        return {}, text

    closing_idx = payload_start + payload_end
    if closing_idx >= len(text) or text[closing_idx] != "]":
        logger.warning("QPRISMA_CONTEXT prefix found but closing bracket is missing")
        return {}, text
    if not isinstance(metadata, dict):
        logger.warning("QPRISMA_CONTEXT payload is not an object")
        return {}, text

    record_legacy_usage(logger, feature="qprisma_context_legacy")
    return metadata, _strip_single_newline(text[closing_idx + 1 :])


def _strip_single_newline(text: str) -> str:
    if text.startswith("\r\n"):
        return text[2:]
    if text.startswith("\n"):
        return text[1:]
    return text
