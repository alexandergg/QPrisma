"""
Centralized retry utilities for QPrisma services.

Provides lightweight async retry helpers with exponential backoff.
For external-library-based retries (e.g. ``tenacity``), continue
using them where already established — this module is for cases where
a simple, dependency-free retry is preferred.
"""

import asyncio
import logging
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T")


async def retry_async(
    func: Callable[..., Any],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    operation_name: str = "operation",
    **kwargs: Any,
) -> Any:
    """Execute an async function with exponential backoff retry.

    Parameters
    ----------
    func:
        The async callable to execute.
    max_retries:
        Maximum number of retries after the initial attempt.
    base_delay:
        Initial delay between retries in seconds.
    max_delay:
        Upper-bound on the delay between retries.
    backoff_factor:
        Multiplier applied to the delay after each failed attempt.
    retryable_exceptions:
        Exception types that trigger a retry.
    operation_name:
        Human-readable label for log messages.
    """
    last_exception: Exception | None = None
    total_attempts = max_retries + 1
    for attempt in range(total_attempts):
        try:
            return await func(*args, **kwargs)
        except retryable_exceptions as e:
            last_exception = e
            if attempt == max_retries:
                logger.error(f"{operation_name} failed after {total_attempts} attempts: {e}")
                raise
            delay = min(base_delay * (backoff_factor**attempt), max_delay)
            logger.warning(
                f"{operation_name} attempt {attempt + 1}/{total_attempts} failed: {e}. "
                f"Retrying in {delay:.1f}s"
            )
            await asyncio.sleep(delay)
    raise last_exception  # type: ignore[misc]


def retry_on(
    *exceptions: type[Exception],
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> Callable:
    """Decorator for retrying async functions on specified exceptions.

    Usage::

        @retry_on(ConnectionError, TimeoutError, max_retries=2)
        async def fetch_data():
            ...
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await retry_async(
                func,
                *args,
                max_retries=max_retries,
                base_delay=base_delay,
                retryable_exceptions=exceptions,
                operation_name=func.__name__,
                **kwargs,
            )

        return wrapper

    return decorator
