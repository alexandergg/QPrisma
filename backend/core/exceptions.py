"""
Custom Exceptions

Application-specific exceptions for better error handling.
Includes HTTPException subclasses with structured error codes.
"""

from typing import Any

from fastapi import HTTPException

# =============================================================================
# Structured API Error
# =============================================================================


class APIError(HTTPException):
    """
    Structured API error with consistent error codes.

    Use this instead of bare HTTPException for machine-readable error responses.

    Example:
        raise APIError(
            code="MEDIA_NOT_FOUND",
            status_code=404,
            detail="Media item not found",
            context={"media_id": "abc123"}
        )

    Response format:
        {
            "error": {
                "code": "MEDIA_NOT_FOUND",
                "message": "Media item not found",
                "context": {"media_id": "abc123"}
            }
        }
    """

    def __init__(
        self,
        code: str,
        status_code: int,
        detail: str,
        context: dict[str, Any] | None = None,
    ):
        self.code = code
        self.context = context or {}
        super().__init__(
            status_code=status_code,
            detail={
                "error": {
                    "code": code,
                    "message": detail,
                    "context": self.context,
                }
            },
        )


# Common API error factory functions
def not_found_error(resource_type: str, resource_id: str) -> APIError:
    """Create a 404 Not Found error."""
    return APIError(
        code=f"{resource_type.upper()}_NOT_FOUND",
        status_code=404,
        detail=f"{resource_type} '{resource_id}' not found",
        context={"resource_type": resource_type, "resource_id": resource_id},
    )


def access_denied_error(resource_type: str, resource_id: str) -> APIError:
    """Create a 403 Access Denied error."""
    return APIError(
        code="ACCESS_DENIED",
        status_code=403,
        detail=f"Access denied to {resource_type} '{resource_id}'",
        context={"resource_type": resource_type, "resource_id": resource_id},
    )


def validation_error(message: str, field: str | None = None) -> APIError:
    """Create a 400 Validation Error."""
    return APIError(
        code="VALIDATION_ERROR",
        status_code=400,
        detail=message,
        context={"field": field} if field else {},
    )


def service_unavailable_error(service_name: str) -> APIError:
    """Create a 503 Service Unavailable error."""
    return APIError(
        code="SERVICE_UNAVAILABLE",
        status_code=503,
        detail=f"Service '{service_name}' is temporarily unavailable",
        context={"service": service_name},
    )


def rate_limit_error(retry_after: int | None = None) -> APIError:
    """Create a 429 Rate Limit error."""
    return APIError(
        code="RATE_LIMIT_EXCEEDED",
        status_code=429,
        detail="Too many requests. Please try again later.",
        context={"retry_after": retry_after} if retry_after else {},
    )


def internal_error(message: str = "An internal error occurred") -> APIError:
    """Create a 500 Internal Server Error."""
    return APIError(
        code="INTERNAL_ERROR",
        status_code=500,
        detail=message,
    )


# =============================================================================
# Base Exception
# =============================================================================


class QPrismaException(Exception):
    """Base exception for all QPrisma errors."""

    def __init__(
        self,
        message: str,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code or "QPRISMA_ERROR"
        self.details = details or {}


# =============================================================================
# Service Exceptions
# =============================================================================


class ServiceUnavailableError(QPrismaException):
    """Raised when a required service is not available."""

    def __init__(self, service_name: str, details: dict | None = None):
        super().__init__(
            message=f"Service '{service_name}' is not available",
            code="SERVICE_UNAVAILABLE",
            details={"service": service_name, **(details or {})},
        )


class ConfigurationError(QPrismaException):
    """Raised when configuration is missing or invalid."""

    def __init__(self, config_name: str, message: str | None = None):
        super().__init__(
            message=message or f"Configuration '{config_name}' is missing or invalid",
            code="CONFIGURATION_ERROR",
            details={"config": config_name},
        )


# =============================================================================
# Processing Exceptions
# =============================================================================


class ProcessingError(QPrismaException):
    """Raised when video/audio processing fails."""

    def __init__(self, message: str, video_id: str | None = None):
        super().__init__(
            message=message,
            code="PROCESSING_ERROR",
            details={"video_id": video_id} if video_id else {},
        )


class TranscriptionError(ProcessingError):
    """Raised when audio transcription fails."""

    def __init__(self, message: str, video_id: str | None = None):
        super().__init__(message=message, video_id=video_id)
        self.code = "TRANSCRIPTION_ERROR"


class FrameExtractionError(ProcessingError):
    """Raised when frame extraction fails."""

    def __init__(self, message: str, video_id: str | None = None):
        super().__init__(message=message, video_id=video_id)
        self.code = "FRAME_EXTRACTION_ERROR"


# =============================================================================
# Data Exceptions
# =============================================================================


class NotFoundError(QPrismaException):
    """Raised when a requested resource is not found."""

    def __init__(self, resource_type: str, resource_id: str):
        super().__init__(
            message=f"{resource_type} '{resource_id}' not found",
            code="NOT_FOUND",
            details={"resource_type": resource_type, "resource_id": resource_id},
        )


class AccessDeniedError(QPrismaException):
    """Raised when access to a resource is denied."""

    def __init__(self, resource_type: str, resource_id: str, user_id: str | None = None):
        super().__init__(
            message=f"Access denied to {resource_type} '{resource_id}'",
            code="ACCESS_DENIED",
            details={
                "resource_type": resource_type,
                "resource_id": resource_id,
                "user_id": user_id,
            },
        )


class ValidationError(QPrismaException):
    """Raised when input validation fails."""

    def __init__(self, message: str, field: str | None = None):
        super().__init__(
            message=message,
            code="VALIDATION_ERROR",
            details={"field": field} if field else {},
        )


# =============================================================================
# Knowledge Graph Exceptions
# =============================================================================


class GraphError(QPrismaException):
    """Raised when a Knowledge Graph operation fails."""

    def __init__(self, message: str, operation: str | None = None):
        super().__init__(
            message=message,
            code="GRAPH_ERROR",
            details={"operation": operation} if operation else {},
        )


class GraphConnectionError(GraphError):
    """Raised when connection to Neo4j fails."""

    def __init__(self, message: str = "Failed to connect to Knowledge Graph"):
        super().__init__(message=message, operation="connect")
        self.code = "GRAPH_CONNECTION_ERROR"
