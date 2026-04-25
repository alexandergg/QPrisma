"""Helpers for QPrisma prompt context envelopes."""

from __future__ import annotations

import json
from typing import Any

QPRISMA_CONTEXT_PREFIX = "[QPRISMA_CONTEXT:"
QPRISMA_BENCH_PREFIX = "[QPRISMA_BENCH:"

_json_decoder = json.JSONDecoder()


def _parse_prefixed_json(text: str, prefix: str) -> tuple[dict[str, Any] | None, str | None]:
    if not text.startswith(prefix):
        return None, None

    json_start = len(prefix)
    try:
        metadata, json_end = _json_decoder.raw_decode(text, json_start)
    except (json.JSONDecodeError, ValueError):
        return None, None

    if not isinstance(metadata, dict):
        return None, None

    if json_end >= len(text) or text[json_end] != "]":
        return None, None

    rest_start = json_end + 1
    if rest_start < len(text) and text[rest_start] == "\n":
        rest_start += 1

    return metadata, text[rest_start:]


def extract_qprisma_envelopes(text: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Extract leading QPrisma context and benchmark envelopes from text."""
    context: dict[str, Any] = {}
    benchmark: dict[str, Any] = {}
    cleaned = text
    parsed_any = False

    while True:
        if cleaned.startswith(QPRISMA_CONTEXT_PREFIX):
            parsed, rest = _parse_prefixed_json(cleaned, QPRISMA_CONTEXT_PREFIX)
            if parsed is None or rest is None:
                return (context, benchmark, cleaned) if parsed_any else ({}, {}, text)
            context = parsed
            cleaned = rest
            parsed_any = True
            continue

        if cleaned.startswith(QPRISMA_BENCH_PREFIX):
            parsed, rest = _parse_prefixed_json(cleaned, QPRISMA_BENCH_PREFIX)
            if parsed is None or rest is None:
                return (context, benchmark, cleaned) if parsed_any else ({}, {}, text)
            benchmark = parsed
            cleaned = rest
            parsed_any = True
            continue

        return context, benchmark, cleaned


def normalize_media_selection(
    media_id: Any,
    media_ids: Any,
) -> tuple[str | None, list[str]]:
    """Normalize explicit and list-shaped media selection fields."""
    normalized_media_id = media_id if isinstance(media_id, str) and media_id else None
    normalized_media_ids = (
        [item for item in media_ids if isinstance(item, str) and item]
        if isinstance(media_ids, list)
        else []
    )

    if normalized_media_id is None and len(normalized_media_ids) == 1:
        normalized_media_id = normalized_media_ids[0]

    return normalized_media_id, normalized_media_ids


def is_letter_only_benchmark(benchmark_context: Any) -> bool:
    """Return True for Video-MME-style MCQ letter-only evaluation requests."""
    if not isinstance(benchmark_context, dict):
        return False

    eval_mode = str(benchmark_context.get("eval_mode") or "").lower()
    response_format = str(benchmark_context.get("format") or "").lower()
    return eval_mode == "mcq" and response_format == "letter_only"
