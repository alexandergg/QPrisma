"""
Tests for core/errors.py

Covers all lightweight HTTP exception helper functions.
"""

import logging

import pytest
from fastapi import HTTPException

from core.errors import (
    bad_request,
    conflict,
    forbidden,
    internal_error,
    not_found,
    service_unavailable,
    unauthorized,
)

# =============================================================================
# Helper return types
# =============================================================================


@pytest.mark.unit
class TestHelperReturnTypes:
    """Every helper must return an HTTPException, not raise it."""

    def test_not_found_returns_http_exception(self):
        exc = not_found()
        assert isinstance(exc, HTTPException)

    def test_bad_request_returns_http_exception(self):
        exc = bad_request()
        assert isinstance(exc, HTTPException)

    def test_forbidden_returns_http_exception(self):
        exc = forbidden()
        assert isinstance(exc, HTTPException)

    def test_unauthorized_returns_http_exception(self):
        exc = unauthorized()
        assert isinstance(exc, HTTPException)

    def test_internal_error_returns_http_exception(self):
        exc = internal_error()
        assert isinstance(exc, HTTPException)

    def test_conflict_returns_http_exception(self):
        exc = conflict()
        assert isinstance(exc, HTTPException)

    def test_service_unavailable_returns_http_exception(self):
        exc = service_unavailable()
        assert isinstance(exc, HTTPException)


# =============================================================================
# Status codes
# =============================================================================


@pytest.mark.unit
class TestStatusCodes:
    def test_not_found_404(self):
        assert not_found().status_code == 404

    def test_bad_request_400(self):
        assert bad_request().status_code == 400

    def test_forbidden_403(self):
        assert forbidden().status_code == 403

    def test_unauthorized_401(self):
        assert unauthorized().status_code == 401

    def test_internal_error_500(self):
        assert internal_error().status_code == 500

    def test_conflict_409(self):
        assert conflict().status_code == 409

    def test_service_unavailable_503(self):
        assert service_unavailable().status_code == 503


# =============================================================================
# Default messages
# =============================================================================


@pytest.mark.unit
class TestDefaultMessages:
    def test_not_found_default(self):
        assert not_found().detail == "Resource not found"

    def test_not_found_with_resource(self):
        assert not_found("Media").detail == "Media not found"

    def test_not_found_with_custom_detail(self):
        exc = not_found("Media", detail="Media with id=abc not found")
        assert exc.detail == "Media with id=abc not found"

    def test_bad_request_default(self):
        assert bad_request().detail == "Invalid request"

    def test_bad_request_custom(self):
        assert bad_request("Missing field").detail == "Missing field"

    def test_forbidden_default(self):
        assert forbidden().detail == "Access denied"

    def test_forbidden_custom(self):
        assert forbidden("Not authorized").detail == "Not authorized"

    def test_unauthorized_default(self):
        assert unauthorized().detail == "Authentication required"

    def test_internal_error_default(self):
        assert internal_error().detail == "An internal error occurred"

    def test_internal_error_custom(self):
        assert internal_error(detail="DB error").detail == "DB error"

    def test_conflict_default(self):
        assert conflict().detail == "Resource conflict"

    def test_service_unavailable_default(self):
        assert service_unavailable().detail == "Service temporarily unavailable"


# =============================================================================
# internal_error logging
# =============================================================================


@pytest.mark.unit
class TestInternalErrorLogging:
    def test_no_logging_by_default(self, caplog):
        with caplog.at_level(logging.ERROR, logger="core.errors"):
            internal_error()
        assert caplog.text == ""

    def test_logs_message(self, caplog):
        with caplog.at_level(logging.ERROR, logger="core.errors"):
            internal_error(log_message="Something broke")
        assert "Something broke" in caplog.text

    def test_logs_exception(self, caplog):
        err = ValueError("test error")
        with caplog.at_level(logging.ERROR, logger="core.errors"):
            internal_error(exc=err)
        assert "Internal error" in caplog.text


# =============================================================================
# Raise semantics
# =============================================================================


@pytest.mark.unit
class TestRaiseSemantics:
    """Helpers return exceptions so they can be raised with ``raise helper()``."""

    def test_raise_not_found(self):
        with pytest.raises(HTTPException) as exc_info:
            raise not_found("Project")
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Project not found"

    def test_raise_forbidden(self):
        with pytest.raises(HTTPException) as exc_info:
            raise forbidden("Not authorized")
        assert exc_info.value.status_code == 403

    def test_raise_bad_request(self):
        with pytest.raises(HTTPException) as exc_info:
            raise bad_request("end_time must be greater than start_time")
        assert exc_info.value.status_code == 400
        assert "end_time" in exc_info.value.detail
