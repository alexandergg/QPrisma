"""
Tests for core/exceptions.py

Covers APIError structured detail, factory methods,
QPrismaException hierarchy, and domain-specific exceptions.
"""

import pytest

from core.exceptions import (
    AccessDeniedError,
    APIError,
    ConfigurationError,
    FrameExtractionError,
    GraphConnectionError,
    GraphError,
    NotFoundError,
    ProcessingError,
    QPrismaException,
    ServiceUnavailableError,
    TranscriptionError,
    ValidationError,
    access_denied_error,
    internal_error,
    not_found_error,
    rate_limit_error,
    service_unavailable_error,
    validation_error,
)

# =============================================================================
# APIError
# =============================================================================


@pytest.mark.unit
class TestAPIError:
    def test_structured_detail(self):
        err = APIError(
            code="MEDIA_NOT_FOUND",
            status_code=404,
            detail="Media item not found",
            context={"media_id": "abc123"},
        )
        assert err.status_code == 404
        assert err.code == "MEDIA_NOT_FOUND"
        assert err.detail["error"]["code"] == "MEDIA_NOT_FOUND"
        assert err.detail["error"]["message"] == "Media item not found"
        assert err.detail["error"]["context"]["media_id"] == "abc123"

    def test_empty_context(self):
        err = APIError(code="TEST", status_code=400, detail="test")
        assert err.context == {}

    def test_is_http_exception(self):
        from fastapi import HTTPException

        err = APIError(code="TEST", status_code=500, detail="test")
        assert isinstance(err, HTTPException)


# =============================================================================
# Factory Methods
# =============================================================================


@pytest.mark.unit
class TestFactoryMethods:
    def test_not_found_error(self):
        err = not_found_error("media", "abc123")
        assert err.status_code == 404
        assert err.code == "MEDIA_NOT_FOUND"
        assert "abc123" in err.detail["error"]["message"]

    def test_access_denied_error(self):
        err = access_denied_error("project", "proj_1")
        assert err.status_code == 403
        assert err.code == "ACCESS_DENIED"

    def test_validation_error_with_field(self):
        err = validation_error("Invalid format", field="email")
        assert err.status_code == 400
        assert err.code == "VALIDATION_ERROR"
        assert err.context["field"] == "email"

    def test_validation_error_without_field(self):
        err = validation_error("General error")
        assert err.context == {}

    def test_service_unavailable_error(self):
        err = service_unavailable_error("Neo4j")
        assert err.status_code == 503
        assert err.context["service"] == "Neo4j"

    def test_rate_limit_error_with_retry(self):
        err = rate_limit_error(retry_after=60)
        assert err.status_code == 429
        assert err.context["retry_after"] == 60

    def test_rate_limit_error_without_retry(self):
        err = rate_limit_error()
        assert err.status_code == 429
        assert err.context == {}

    def test_internal_error_default(self):
        err = internal_error()
        assert err.status_code == 500
        assert "internal error" in err.detail["error"]["message"].lower()

    def test_internal_error_custom(self):
        err = internal_error("Custom failure")
        assert err.detail["error"]["message"] == "Custom failure"


# =============================================================================
# QPrismaException Hierarchy
# =============================================================================


@pytest.mark.unit
class TestQPrismaException:
    def test_base_exception(self):
        err = QPrismaException("Something went wrong")
        assert str(err) == "Something went wrong"
        assert err.code == "QPRISMA_ERROR"
        assert err.details == {}

    def test_with_code_and_details(self):
        err = QPrismaException("Error", code="MY_ERROR", details={"key": "val"})
        assert err.code == "MY_ERROR"
        assert err.details["key"] == "val"

    def test_service_unavailable(self):
        err = ServiceUnavailableError("Database")
        assert "Database" in str(err)
        assert err.code == "SERVICE_UNAVAILABLE"

    def test_configuration_error(self):
        err = ConfigurationError("OPENAI_KEY")
        assert "OPENAI_KEY" in str(err)
        assert err.code == "CONFIGURATION_ERROR"

    def test_processing_error(self):
        err = ProcessingError("Frame extraction failed", video_id="v1")
        assert err.details["video_id"] == "v1"

    def test_transcription_error(self):
        err = TranscriptionError("Whisper failed", video_id="v2")
        assert err.code == "TRANSCRIPTION_ERROR"

    def test_frame_extraction_error(self):
        err = FrameExtractionError("FFmpeg crash", video_id="v3")
        assert err.code == "FRAME_EXTRACTION_ERROR"

    def test_not_found_error(self):
        err = NotFoundError("media", "m1")
        assert err.code == "NOT_FOUND"
        assert "m1" in str(err)

    def test_access_denied_error(self):
        err = AccessDeniedError("project", "p1", user_id="u1")
        assert err.code == "ACCESS_DENIED"
        assert err.details["user_id"] == "u1"

    def test_validation_error(self):
        err = ValidationError("Bad input", field="name")
        assert err.code == "VALIDATION_ERROR"
        assert err.details["field"] == "name"

    def test_graph_error(self):
        err = GraphError("Query failed", operation="search")
        assert err.code == "GRAPH_ERROR"

    def test_graph_connection_error(self):
        err = GraphConnectionError()
        assert err.code == "GRAPH_CONNECTION_ERROR"
        assert "connect" in str(err).lower()
