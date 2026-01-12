"""
Custom Exceptions

Application-specific exceptions for better error handling.
"""

from typing import Any


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
