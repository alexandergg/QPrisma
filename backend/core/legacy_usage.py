"""Lightweight counters for intentionally retained legacy compatibility paths."""

from __future__ import annotations

import logging
from collections import Counter
from types import MappingProxyType
from typing import Any

_legacy_usage_counts: Counter[str] = Counter()


def record_legacy_usage(
    logger: logging.Logger,
    *,
    feature: str,
    labels: dict[str, Any] | None = None,
    level: int = logging.INFO,
) -> None:
    """Record that a retained legacy compatibility path was used."""
    normalized_labels = _normalize_labels(labels or {})
    label_suffix = "|".join(f"{key}={value}" for key, value in normalized_labels.items())
    counter_key = feature if not label_suffix else f"{feature}|{label_suffix}"
    _legacy_usage_counts[counter_key] += 1

    logger.log(
        level,
        "legacy_usage_detected",
        extra={
            "legacy_feature": feature,
            "legacy_labels": MappingProxyType(normalized_labels),
        },
    )


def get_legacy_usage_counts() -> dict[str, int]:
    """Return a snapshot of in-process legacy compatibility counters."""
    return dict(_legacy_usage_counts)


def reset_legacy_usage_counts() -> None:
    """Reset in-process legacy compatibility counters for tests."""
    _legacy_usage_counts.clear()


def _normalize_labels(labels: dict[str, Any]) -> dict[str, str]:
    return {
        str(key)[:64]: str(value)[:128].replace("\n", "").replace("\r", "")
        for key, value in sorted(labels.items())
    }
