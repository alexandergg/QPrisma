"""Centralized Neo4j error handling and retry policies.

Provides:
- Transient-error classification for Neo4j exceptions
- Read retry decorator (exponential backoff, max 3 retries)
- Write retry decorator (single retry for idempotent MERGE, fail-fast for CREATE/DELETE)
- Structured logging for all failed queries
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from neo4j.exceptions import (
    AuthError,
    ClientError,
    CypherSyntaxError,
    DatabaseUnavailable,
    ServiceUnavailable,
    SessionExpired,
    TransientError,
)

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# Exceptions that indicate a transient failure safe to retry
TRANSIENT_EXCEPTIONS: tuple[type[Exception], ...] = (
    ServiceUnavailable,
    SessionExpired,
    TransientError,
    DatabaseUnavailable,
    ConnectionError,
)

# Exceptions that are permanent — retrying won't help
PERMANENT_EXCEPTIONS: tuple[type[Exception], ...] = (
    AuthError,
    CypherSyntaxError,
    ClientError,
)


def is_transient(exc: Exception) -> bool:
    """Return True if the exception represents a transient Neo4j failure."""
    return isinstance(exc, TRANSIENT_EXCEPTIONS)


def neo4j_read_retry(
    max_retries: int = 3,
    base_delay: float = 0.5,
    backoff_factor: float = 2.0,
    max_delay: float = 8.0,
) -> Callable[[F], F]:
    """Retry decorator for Neo4j read operations.

    Retries on transient failures with exponential backoff.
    Permanent failures propagate immediately.
    """

    def decorator(fn: F) -> F:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    if isinstance(exc, PERMANENT_EXCEPTIONS) or not is_transient(exc):
                        logger.error(
                            "Neo4j read permanent failure in %s: %s",
                            fn.__qualname__,
                            exc,
                        )
                        raise
                    if attempt < max_retries:
                        delay = min(base_delay * (backoff_factor**attempt), max_delay)
                        logger.warning(
                            "Neo4j read transient failure in %s (attempt %d/%d), "
                            "retrying in %.1fs: %s",
                            fn.__qualname__,
                            attempt + 1,
                            max_retries + 1,
                            delay,
                            exc,
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            "Neo4j read exhausted retries in %s after %d attempts: %s",
                            fn.__qualname__,
                            max_retries + 1,
                            exc,
                        )
            raise last_exc  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator


def neo4j_write_retry(
    max_retries: int = 1,
    base_delay: float = 1.0,
) -> Callable[[F], F]:
    """Retry decorator for idempotent Neo4j write operations (MERGE).

    Single retry with fixed delay — safe only for idempotent operations.
    Non-idempotent writes (CREATE, DELETE) should NOT use this decorator.
    """

    def decorator(fn: F) -> F:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    if isinstance(exc, PERMANENT_EXCEPTIONS) or not is_transient(exc):
                        logger.error(
                            "Neo4j write permanent failure in %s: %s",
                            fn.__qualname__,
                            exc,
                        )
                        raise
                    if attempt < max_retries:
                        logger.warning(
                            "Neo4j write transient failure in %s (attempt %d/%d), "
                            "retrying in %.1fs: %s",
                            fn.__qualname__,
                            attempt + 1,
                            max_retries + 1,
                            base_delay,
                            exc,
                        )
                        time.sleep(base_delay)
                    else:
                        logger.error(
                            "Neo4j write exhausted retries in %s after %d attempts: %s",
                            fn.__qualname__,
                            max_retries + 1,
                            exc,
                        )
            raise last_exc  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator


def execute_with_error_handling(
    fn: Callable[..., Any],
    *args: Any,
    query_name: str = "unknown",
    **kwargs: Any,
) -> Any:
    """Execute a function with structured Neo4j error logging.

    Wraps any Neo4j operation with consistent error classification and
    logging.  Does NOT retry — use the retry decorators for that.

    Args:
        fn: The callable to execute.
        query_name: Human-readable name for log messages.

    Returns:
        The return value of *fn*.

    Raises:
        The original exception with structured logging added.
    """
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        failure_type = "transient" if is_transient(exc) else "permanent"
        logger.error(
            "Neo4j %s failure in '%s': [%s] %s",
            failure_type,
            query_name,
            type(exc).__name__,
            exc,
        )
        raise
