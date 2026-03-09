"""
Standardized error responses for QPrisma API.

Lightweight HTTP exception helpers for common error patterns in route handlers.
These complement the structured ``APIError`` helpers in ``core.exceptions``
by providing quick, human-readable error factories for the most frequent
status codes.

Usage in routes::

    from core.errors import not_found, bad_request, forbidden

    raise not_found("Media")
    raise bad_request("end_time must be greater than start_time")
    raise forbidden("Not authorized")
"""

import logging

from fastapi import HTTPException

logger = logging.getLogger(__name__)


def not_found(resource: str = "Resource", detail: str | None = None) -> HTTPException:
    """Return a 404 Not Found error."""
    return HTTPException(status_code=404, detail=detail or f"{resource} not found")


def bad_request(detail: str = "Invalid request") -> HTTPException:
    """Return a 400 Bad Request error."""
    return HTTPException(status_code=400, detail=detail)


def forbidden(detail: str = "Access denied") -> HTTPException:
    """Return a 403 Forbidden error."""
    return HTTPException(status_code=403, detail=detail)


def unauthorized(detail: str = "Authentication required") -> HTTPException:
    """Return a 401 Unauthorized error."""
    return HTTPException(status_code=401, detail=detail)


def internal_error(
    detail: str = "An internal error occurred",
    log_message: str | None = None,
    exc: Exception | None = None,
) -> HTTPException:
    """Return a 500 Internal Server Error with optional server-side logging."""
    if log_message or exc:
        logger.error(log_message or "Internal error", exc_info=exc)
    return HTTPException(status_code=500, detail=detail)


def conflict(detail: str = "Resource conflict") -> HTTPException:
    """Return a 409 Conflict error."""
    return HTTPException(status_code=409, detail=detail)


def service_unavailable(detail: str = "Service temporarily unavailable") -> HTTPException:
    """Return a 503 Service Unavailable error."""
    return HTTPException(status_code=503, detail=detail)
