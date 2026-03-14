"""
Async Utilities

Utilities for running synchronous blocking code in async FastAPI context.
Prevents blocking the event loop with CPU-bound or I/O-bound sync operations.
"""

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial, wraps
from typing import ParamSpec, TypeVar

# Thread pool for blocking operations
# Size based on typical video processing workload (I/O bound)
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="qprisma-sync-")

P = ParamSpec("P")
R = TypeVar("R")


async def run_sync(func: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
    """
    Run a synchronous function in the thread pool without blocking the event loop.

    Use this for:
    - PIL / FFmpeg image and video operations
    - Synchronous Azure SDK calls
    - CPU-bound processing
    - File I/O

    Example:
        # Instead of blocking:
        result = video_processor.extract_frames(video_path)

        # Use:
        result = await run_sync(video_processor.extract_frames, video_path)

    Args:
        func: Synchronous function to execute
        *args: Positional arguments for the function
        **kwargs: Keyword arguments for the function

    Returns:
        The return value of the function
    """
    loop = asyncio.get_running_loop()

    if kwargs:
        func = partial(func, **kwargs)

    return await loop.run_in_executor(_executor, func, *args)


def async_wrap(func: Callable[P, R]) -> Callable[P, R]:
    """
    Decorator to wrap a synchronous function for async execution.

    Use this to create async versions of sync methods:

    Example:
        class VideoProcessor:
            def extract_frames(self, path: str) -> list:
                ...  # sync code

            # Create async version
            extract_frames_async = async_wrap(extract_frames)

    Or as a decorator:
        @async_wrap
        def process_file(path: str) -> dict:
            ...  # CPU-bound sync code
    """

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        return await run_sync(func, *args, **kwargs)

    return wrapper


def get_executor() -> ThreadPoolExecutor:
    """Get the shared thread pool executor."""
    return _executor


def shutdown_executor(wait: bool = True) -> None:
    """
    Shutdown the thread pool executor.

    Call this on application shutdown to clean up threads.

    Args:
        wait: If True, wait for pending tasks to complete
    """
    _executor.shutdown(wait=wait)


# Type-safe async versions for common operations
async def read_file_async(path: str, mode: str = "r") -> str | bytes:
    """Read a file asynchronously."""

    def _read():
        with open(path, mode) as f:
            return f.read()

    return await run_sync(_read)


async def write_file_async(path: str, content: str | bytes, mode: str = "w") -> None:
    """Write to a file asynchronously."""

    def _write():
        with open(path, mode) as f:
            f.write(content)

    await run_sync(_write)
