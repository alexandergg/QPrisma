"""
Core utilities for QPrisma backend.

This package contains:
- config: Application configuration using Pydantic Settings
- constants: Centralized constants
- exceptions: Custom exception classes
- logging_config: Logging configuration
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
    # Logging
    "get_logger",
    "setup_logging",
    "PipelineLogger",
]
