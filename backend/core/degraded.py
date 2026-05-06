"""Helpers for observable best-effort degradation paths."""

import logging
from collections import Counter
from collections.abc import Mapping
from enum import StrEnum


class DegradationImpact(StrEnum):
    """Operational impact of a non-blocking failure."""

    CACHE_READ = "cache_read"
    CACHE_WRITE = "cache_write"
    CACHE_INVALIDATION = "cache_invalidation"
    BLOB_HYDRATION = "blob_hydration"
    OPTIONAL_DISPATCH = "optional_dispatch"
    MEMORY_UPDATE = "memory_update"
    MEMORY_SEARCH = "memory_search"
    MEMORY_DELETE = "memory_delete"


_degradation_counts: Counter[tuple[str, str, str, str]] = Counter()


def record_degraded_operation(
    logger: logging.Logger,
    *,
    component: str,
    operation: str,
    impact: DegradationImpact,
    exc: BaseException,
    level: int = logging.WARNING,
    extra_labels: Mapping[str, str] | None = None,
) -> None:
    """Record and log a best-effort failure without leaking exception text."""
    error_type = type(exc).__name__
    _degradation_counts[(component, operation, impact.value, error_type)] += 1

    labels = dict(extra_labels or {})
    logger.log(
        level,
        "Optional operation degraded: component=%s operation=%s impact=%s error_type=%s labels=%s",
        component,
        operation,
        impact.value,
        error_type,
        labels,
    )
    logger.debug(
        "Optional operation degradation traceback",
        exc_info=(type(exc), exc, exc.__traceback__),
    )


def get_degradation_counts() -> dict[str, int]:
    """Return degradation counters for tests and operational diagnostics."""
    return {
        "|".join((component, operation, impact, error_type)): count
        for (component, operation, impact, error_type), count in _degradation_counts.items()
    }


def reset_degradation_counts() -> None:
    """Reset degradation counters."""
    _degradation_counts.clear()
