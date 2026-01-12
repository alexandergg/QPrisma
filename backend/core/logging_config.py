"""
Logging Configuration
=====================
Centralized logging configuration for QPrisma backend.

Usage:
    from core.logging_config import get_logger
    logger = get_logger(__name__)

    logger.info("Processing started", extra={"media_id": "123"})
    logger.debug("Detail info")
    logger.warning("Something unusual")
    logger.error("Error occurred", exc_info=True)
"""

import logging
import os
import sys
from datetime import datetime


class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors for console output."""

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"
    BOLD = "\033[1m"

    def format(self, record: logging.LogRecord) -> str:
        # Add color based on level
        color = self.COLORS.get(record.levelname, "")

        # Format the base message
        formatted = super().format(record)

        # Add colors if terminal supports it
        if sys.stdout.isatty():
            formatted = f"{color}{formatted}{self.RESET}"

        return formatted


class StructuredFormatter(logging.Formatter):
    """Formatter for structured logging with context."""

    def format(self, record: logging.LogRecord) -> str:
        # Base format
        timestamp = datetime.utcnow().isoformat()
        level = record.levelname
        name = record.name
        message = record.getMessage()

        # Build structured output
        parts = [f"[{timestamp}]", f"[{level:8}]", f"[{name}]", message]

        # Add extra fields if present
        extra_fields = []
        for key, value in record.__dict__.items():
            if key not in [
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "exc_info",
                "exc_text",
                "thread",
                "threadName",
                "message",
                "taskName",
            ]:
                extra_fields.append(f"{key}={value}")

        if extra_fields:
            parts.append(f"| {' '.join(extra_fields)}")

        return " ".join(parts)


def setup_logging(
    level: str = "INFO",
    log_file: str | None = None,
    use_colors: bool = True,
    structured: bool = False,
) -> None:
    """
    Configure logging for the application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional file path for logging
        use_colors: Use colored output in console
        structured: Use structured logging format
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Clear existing handlers
    root_logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    if structured:
        formatter = StructuredFormatter()
    elif use_colors:
        formatter = ColoredFormatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s", datefmt="%H:%M:%S"
        )
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler (optional)
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(log_level)
        file_formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

    # Reduce noise from third-party libraries
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a module.

    Args:
        name: Module name (typically __name__)

    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)


# Pipeline-specific loggers for easy filtering
class PipelineLogger:
    """Helper class for pipeline-specific logging with context."""

    def __init__(self, logger: logging.Logger, media_id: str = ""):
        self.logger = logger
        self.media_id = media_id
        self._step = 0

    def set_media_id(self, media_id: str) -> None:
        self.media_id = media_id

    def step(self, step_num: int, description: str) -> None:
        """Log a pipeline step."""
        self._step = step_num
        self.logger.info(
            f"STEP {step_num}: {description}", extra={"media_id": self.media_id, "step": step_num}
        )

    def progress(self, message: str, **kwargs) -> None:
        """Log progress within a step."""
        self.logger.info(
            f"  {message}", extra={"media_id": self.media_id, "step": self._step, **kwargs}
        )

    def detail(self, message: str, **kwargs) -> None:
        """Log detailed debug info."""
        self.logger.debug(
            f"    {message}", extra={"media_id": self.media_id, "step": self._step, **kwargs}
        )

    def success(self, message: str, **kwargs) -> None:
        """Log success message."""
        self.logger.info(
            f"  [OK] {message}", extra={"media_id": self.media_id, "step": self._step, **kwargs}
        )

    def warning(self, message: str, **kwargs) -> None:
        """Log warning."""
        self.logger.warning(
            message, extra={"media_id": self.media_id, "step": self._step, **kwargs}
        )

    def error(self, message: str, exc_info: bool = False, **kwargs) -> None:
        """Log error."""
        self.logger.error(
            message,
            exc_info=exc_info,
            extra={"media_id": self.media_id, "step": self._step, **kwargs},
        )

    def summary(self, title: str, **stats) -> None:
        """Log a summary with statistics."""
        self.logger.info(f"{'='*60}")
        self.logger.info(f"  {title}")
        self.logger.info(f"{'='*60}")
        for key, value in stats.items():
            self.logger.info(f"  {key}: {value}")
        self.logger.info(f"{'='*60}")


# Initialize logging on import if not already configured
if not logging.getLogger().handlers:
    log_level = os.getenv("LOG_LEVEL", "INFO")
    log_file = os.getenv("LOG_FILE")
    setup_logging(level=log_level, log_file=log_file)
