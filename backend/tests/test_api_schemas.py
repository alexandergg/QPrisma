"""
Tests for models/api_schemas.py

Covers request/response model validation, deduplication logic,
field constraints, and enum values.
"""

import pytest
from pydantic import ValidationError

from models.api_schemas import (
    AgentChatRequest,
    ChatRequest,
    JobStatus,
    ProcessingConfig,
    RegisterRequest,
    SearchRequest,
)


# =============================================================================
# ChatRequest
# =============================================================================


@pytest.mark.unit
class TestChatRequest:
    def test_minimal(self):
        req = ChatRequest(message="hello")
        assert req.message == "hello"
        assert req.media_id is None
        assert req.media_ids is None

    def test_with_media_id(self):
        req = ChatRequest(message="hi", media_id="vid_1")
        assert req.get_effective_media_ids() == ["vid_1"]

    def test_with_media_ids(self):
        req = ChatRequest(message="hi", media_ids=["vid_1", "vid_2"])
        assert req.get_effective_media_ids() == ["vid_1", "vid_2"]

    def test_deduplication(self):
        req = ChatRequest(message="hi", media_id="vid_1", media_ids=["vid_1", "vid_2"])
        ids = req.get_effective_media_ids()
        assert ids == ["vid_1", "vid_2"]

    def test_max_10_effective_ids(self):
        """get_effective_media_ids truncates to 10 even with media_id + media_ids."""
        req = ChatRequest(
            message="hi",
            media_id="v0",
            media_ids=[f"v{i}" for i in range(1, 10)],  # 9 items (max_length=10)
        )
        ids = req.get_effective_media_ids()
        assert len(ids) <= 10

    def test_media_ids_max_length_validation(self):
        with pytest.raises(ValidationError):
            ChatRequest(
                message="hi",
                media_ids=[f"v{i}" for i in range(11)],  # 11 > max_length=10
            )


# =============================================================================
# AgentChatRequest
# =============================================================================


@pytest.mark.unit
class TestAgentChatRequest:
    def test_minimal(self):
        req = AgentChatRequest(message="find highlights")
        assert req.session_id is None
        assert req.output_format == "markdown"

    def test_with_session_id(self):
        req = AgentChatRequest(message="more", session_id="sess_123")
        assert req.session_id == "sess_123"

    def test_deduplication(self):
        req = AgentChatRequest(
            message="compare",
            media_id="v1",
            media_ids=["v1", "v2"],
        )
        assert req.get_effective_media_ids() == ["v1", "v2"]

    def test_output_format_options(self):
        for fmt in ("markdown", "json", "structured"):
            req = AgentChatRequest(message="hi", output_format=fmt)
            assert req.output_format == fmt


# =============================================================================
# RegisterRequest
# =============================================================================


@pytest.mark.unit
class TestRegisterRequest:
    def test_valid(self):
        req = RegisterRequest(email="a@b.com", password="longpassword", name="Test")
        assert req.email == "a@b.com"

    def test_short_password(self):
        with pytest.raises(ValidationError):
            RegisterRequest(email="a@b.com", password="short", name="Test")

    def test_short_name(self):
        with pytest.raises(ValidationError):
            RegisterRequest(email="a@b.com", password="longpassword", name="A")

    def test_invalid_email(self):
        with pytest.raises(ValidationError):
            RegisterRequest(email="notanemail", password="longpassword", name="Test")


# =============================================================================
# SearchRequest
# =============================================================================


@pytest.mark.unit
class TestSearchRequest:
    def test_defaults(self):
        req = SearchRequest(query="test")
        assert req.limit == 20
        assert req.media_id is None

    def test_limit_bounds(self):
        req = SearchRequest(query="test", limit=1)
        assert req.limit == 1
        req = SearchRequest(query="test", limit=100)
        assert req.limit == 100

    def test_limit_too_high(self):
        with pytest.raises(ValidationError):
            SearchRequest(query="test", limit=101)

    def test_limit_too_low(self):
        with pytest.raises(ValidationError):
            SearchRequest(query="test", limit=0)


# =============================================================================
# ProcessingConfig
# =============================================================================


@pytest.mark.unit
class TestProcessingConfig:
    def test_defaults(self):
        config = ProcessingConfig()
        assert config.extract_frames is True
        assert config.transcribe_audio is True
        assert config.max_frames == 100
        assert config.use_batch_api is True

    def test_custom_values(self):
        config = ProcessingConfig(max_frames=50, use_batch_api=False, priority="high")
        assert config.max_frames == 50
        assert config.use_batch_api is False


# =============================================================================
# JobStatus
# =============================================================================


@pytest.mark.unit
class TestJobStatus:
    def test_enum_values(self):
        assert JobStatus.PENDING == "pending"
        assert JobStatus.PROCESSING == "processing"
        assert JobStatus.COMPLETED == "completed"
        assert JobStatus.FAILED == "failed"
        assert JobStatus.CANCELLED == "cancelled"

    def test_from_string(self):
        assert JobStatus("pending") == JobStatus.PENDING
        assert JobStatus("completed") == JobStatus.COMPLETED
