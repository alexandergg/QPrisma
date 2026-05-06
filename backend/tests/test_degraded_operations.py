"""Tests for best-effort degradation observability."""

import logging

import pytest

from core.degraded import (
    DegradationImpact,
    get_degradation_counts,
    record_degraded_operation,
    reset_degradation_counts,
)


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
