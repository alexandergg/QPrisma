"""Structured concurrency utilities for QPrisma.

Provides Python 3.11+ ``asyncio.TaskGroup``-based alternatives to
``asyncio.gather()`` with proper cancellation semantics: if any task
fails, all sibling tasks are cancelled immediately.

Use these utilities when *all* concurrent operations must succeed.
For partial-failure tolerance (e.g. transcription chunks), keep
``asyncio.gather(return_exceptions=True)``.
"""

import asyncio
import logging
from collections.abc import Callable, Sequence
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def gather_with_taskgroup(
    *coros: Any,
    task_name_prefix: str = "task",
) -> list[Any]:
    """Run coroutines concurrently using TaskGroup.

    Unlike ``asyncio.gather()``, this provides proper cancellation
    semantics — if any task fails, all others are cancelled.

    Args:
        *coros: Awaitable coroutines to run concurrently.
        task_name_prefix: Name prefix for tasks (visible in tracebacks
            and :func:`asyncio.current_task`).

    Returns:
        List of results in the same order as the input coroutines.

    Raises:
        ExceptionGroup: If one or more tasks fail.
    """
    results: dict[int, Any] = {}

    if not coros:
        return []

    async with asyncio.TaskGroup() as tg:
        for i, coro in enumerate(coros):

            async def _run(idx: int = i, c: Any = coro) -> None:
                results[idx] = await c

            tg.create_task(_run(), name=f"{task_name_prefix}-{i}")

    return [results[i] for i in range(len(results))]


async def map_concurrent(
    func: Callable[..., Any],
    items: Sequence[Any],
    max_concurrency: int | None = None,
    task_name_prefix: str = "map",
) -> list[Any]:
    """Map an async function over items with bounded concurrency using TaskGroup.

    All tasks must succeed; if any task raises, the remaining tasks are
    cancelled and the exception propagates as an ``ExceptionGroup``.

    Args:
        func: Async callable applied to each item.
        items: Sequence of items to process.
        max_concurrency: Maximum number of tasks running at once.
            ``None`` means unlimited.
        task_name_prefix: Name prefix for tasks (for debugging).

    Returns:
        List of results in the same order as *items*.

    Raises:
        ExceptionGroup: If one or more tasks fail.
    """
    if not items:
        return []

    results: dict[int, Any] = {}
    semaphore = asyncio.Semaphore(max_concurrency) if max_concurrency else None

    async def _bounded_run(idx: int, item: Any) -> None:
        if semaphore:
            async with semaphore:
                results[idx] = await func(item)
        else:
            results[idx] = await func(item)

    async with asyncio.TaskGroup() as tg:
        for i, item in enumerate(items):
            tg.create_task(
                _bounded_run(i, item),
                name=f"{task_name_prefix}-{i}",
            )

    return [results[i] for i in range(len(results))]
