"""
Core utilities for QPrisma backend.

This package contains:
- config: Application configuration using Pydantic Settings
- constants: Centralized constants
- exceptions: Custom exception classes
- logging_config: Logging configuration
"""

from .config import Settings, get_settings, settings
from .constants import (
    DEFAULT_MAX_FRAMES,
    DEFAULT_PAGE_SIZE,
    DEFAULT_SEARCH_LIMIT,
    MAX_PAGE_SIZE,
    MAX_SEARCH_LIMIT,
    WHISPER_MAX_FILE_SIZE_MB,
)
from .exceptions import (
    AccessDeniedError,
    ConfigurationError,
    GraphConnectionError,
    GraphError,
    NotFoundError,
    ProcessingError,
    QPrismaException,
    ServiceUnavailableError,
    TranscriptionError,
    ValidationError,
)
from .logging_config import PipelineLogger, get_logger, setup_logging

__all__ = [
    # Config
    "Settings",
    "get_settings",
    "settings",
    # Constants
    "DEFAULT_MAX_FRAMES",
    "DEFAULT_PAGE_SIZE",
    "DEFAULT_SEARCH_LIMIT",
    "MAX_PAGE_SIZE",
    "MAX_SEARCH_LIMIT",
    "WHISPER_MAX_FILE_SIZE_MB",
    # Exceptions
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
