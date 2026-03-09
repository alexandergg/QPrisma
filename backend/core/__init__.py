"""
Core utilities for QPrisma backend.

This package contains:
- config: Application configuration using Pydantic Settings
- constants: Centralized constants
- errors: Lightweight HTTP exception helpers for routes
- exceptions: Custom exception classes
- logging_config: Logging configuration
- retry: Centralized async retry utilities
"""

from .async_utils import (
    async_wrap,
    get_executor,
    read_file_async,
    run_sync,
    shutdown_executor,
    write_file_async,
)
from .config import Settings, create_azure_openai_client, get_settings, settings
from .constants import (
    DEFAULT_MAX_FRAMES,
    DEFAULT_PAGE_SIZE,
    DEFAULT_SEARCH_LIMIT,
    MAX_PAGE_SIZE,
    MAX_SEARCH_LIMIT,
    WHISPER_MAX_FILE_SIZE_MB,
)
from .errors import (
    bad_request,
    conflict,
    forbidden,
    not_found,
    service_unavailable,
    unauthorized,
)
from .errors import internal_error as http_internal_error
from .exceptions import (
    # Base exceptions
    AccessDeniedError,
    # Structured API errors (recommended)
    APIError,
    ConfigurationError,
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
from .logging_config import PipelineLogger, get_logger, setup_logging
from .retry import retry_async, retry_on

__all__ = [
    # Async Utilities
    "run_sync",
    "async_wrap",
    "get_executor",
    "shutdown_executor",
    "read_file_async",
    "write_file_async",
    # Config
    "Settings",
    "get_settings",
    "settings",
    "create_azure_openai_client",
    # Constants
    "DEFAULT_MAX_FRAMES",
    "DEFAULT_PAGE_SIZE",
    "DEFAULT_SEARCH_LIMIT",
    "MAX_PAGE_SIZE",
    "MAX_SEARCH_LIMIT",
    "WHISPER_MAX_FILE_SIZE_MB",
    # Lightweight HTTP error helpers (for routes)
    "not_found",
    "bad_request",
    "forbidden",
    "unauthorized",
    "http_internal_error",
    "conflict",
    "service_unavailable",
    # Structured API Errors (recommended for routes)
    "APIError",
    "not_found_error",
    "access_denied_error",
    "validation_error",
    "service_unavailable_error",
    "rate_limit_error",
    "internal_error",
    # Base Exceptions (for services)
    "QPrismaException",
    "ServiceUnavailableError",
    "ConfigurationError",
    "ProcessingError",
    "TranscriptionError",
    "NotFoundError",
    "AccessDeniedError",
    "ValidationError",
    "GraphError",
    "GraphConnectionError",
    # Retry utilities
    "retry_async",
    "retry_on",
    # Logging
    "get_logger",
    "setup_logging",
    "PipelineLogger",
]
