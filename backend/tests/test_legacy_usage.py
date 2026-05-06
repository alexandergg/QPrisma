"""Tests for legacy compatibility path usage counters."""

import logging

import pytest
from agent.hosted.context_envelope import extract_qprisma_context

from core.legacy_usage import (
    get_legacy_usage_counts,
    record_legacy_usage,
    reset_legacy_usage_counts,
)


@pytest.mark.unit
def test_record_legacy_usage_counts_by_feature_and_labels(caplog):
    reset_legacy_usage_counts()
    logger = logging.getLogger("tests.legacy_usage")

    with caplog.at_level(logging.INFO, logger=logger.name):
        record_legacy_usage(
            logger,
            feature="classic_chat_endpoint",
            labels={"media_context": True},
        )

    assert get_legacy_usage_counts() == {
        "classic_chat_endpoint|media_context=True": 1,
    }
    assert "legacy_usage_detected" in caplog.text


@pytest.mark.unit
def test_extract_legacy_context_records_usage():
    reset_legacy_usage_counts()

    metadata, message = extract_qprisma_context(
        '[QPRISMA_CONTEXT:{"media_id":"media-1","user_id":"user-1"}]\nQuestion'
    )

    assert metadata["media_id"] == "media-1"
    assert message == "Question"
    assert get_legacy_usage_counts() == {"qprisma_context_legacy": 1}
