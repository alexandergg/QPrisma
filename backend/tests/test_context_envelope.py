"""Tests for hosted-agent QPrisma context envelope helpers."""

import pytest
from agent.hosted.context_envelope import (
    CONTEXT_PREFIX_B64,
    extract_qprisma_context,
    format_qprisma_context,
)


@pytest.mark.unit
def test_format_and_extract_base64_context_with_arrays():
    metadata = {
        "media_id": "media-1",
        "media_ids": ["media-1", "media-2"],
        "user_id": "user-1",
    }

    enveloped = format_qprisma_context(metadata, "Compare these videos")

    assert enveloped.startswith(CONTEXT_PREFIX_B64)
    parsed, cleaned = extract_qprisma_context(enveloped)
    assert parsed == metadata
    assert cleaned == "Compare these videos"


@pytest.mark.unit
def test_extract_legacy_context_with_array_payload():
    legacy = (
        '[QPRISMA_CONTEXT:{"media_ids":["media-1","media-2"],"user_id":"user-1"}]\n'
        "Compare these videos"
    )

    parsed, cleaned = extract_qprisma_context(legacy)

    assert parsed == {"media_ids": ["media-1", "media-2"], "user_id": "user-1"}
    assert cleaned == "Compare these videos"


@pytest.mark.unit
def test_extract_plain_message_returns_original():
    parsed, cleaned = extract_qprisma_context("No envelope here")

    assert parsed == {}
    assert cleaned == "No envelope here"


@pytest.mark.unit
def test_malformed_envelope_returns_original_text():
    text = "[QPRISMA_CONTEXT_B64:not-valid-json]\nHello"

    parsed, cleaned = extract_qprisma_context(text)

    assert parsed == {}
    assert cleaned == text
