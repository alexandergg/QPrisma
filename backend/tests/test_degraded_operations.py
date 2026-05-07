"""Tests for best-effort degradation observability."""

import logging

import pytest

from core.degraded import (
    DegradationImpact,
    get_degradation_counts,
    record_degraded_operation,
    reset_degradation_counts,
)
from services.cache_service import CacheService


@pytest.mark.unit
def test_record_degraded_operation_counts_and_sanitizes(caplog):
    reset_degradation_counts()
    logger = logging.getLogger("tests.degraded")

    with caplog.at_level(logging.WARNING, logger=logger.name):
        record_degraded_operation(
            logger,
            component="graph",
            operation="cache_read",
            impact=DegradationImpact.CACHE_READ,
            exc=RuntimeError("secret connection string"),
        )

    counts = get_degradation_counts()
    assert counts["graph|cache_read|cache_read|RuntimeError"] == 1
    assert "RuntimeError" in caplog.text
    assert "secret connection string" not in caplog.text


@pytest.mark.unit
def test_record_degraded_operation_debug_log_is_sanitized(caplog):
    reset_degradation_counts()
    logger = logging.getLogger("tests.degraded.debug")

    with caplog.at_level(logging.DEBUG, logger=logger.name):
        record_degraded_operation(
            logger,
            component="memory",
            operation="search",
            impact=DegradationImpact.MEMORY_SEARCH,
            exc=RuntimeError("secret token"),
            level=logging.DEBUG,
        )

    assert "RuntimeError" in caplog.text
    assert "secret token" not in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cache_get_failure_records_sanitized_degradation(caplog, monkeypatch):
    reset_degradation_counts()
    cache = CacheService()
    cache._connected = True
    monkeypatch.setattr(cache.client, "get", _raise_runtime_error)

    with caplog.at_level(logging.DEBUG, logger="services.cache_service"):
        result = await cache.get_search_result("query-key")

    assert result is None
    assert cache.metrics.errors == 1
    assert get_degradation_counts()["cache|raw_get|cache_read|RuntimeError"] == 1
    assert "RuntimeError" in caplog.text
    assert "secret cache backend" not in caplog.text


async def _raise_runtime_error(*_args, **_kwargs):
    raise RuntimeError("secret cache backend")
