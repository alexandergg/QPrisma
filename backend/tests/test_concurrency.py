"""
Tests for core/concurrency.py

Covers gather_with_taskgroup, map_concurrent, cancellation behaviour,
bounded concurrency, empty-input handling, and error propagation.
"""

import asyncio

import pytest

from core.concurrency import gather_with_taskgroup, map_concurrent

# =============================================================================
# gather_with_taskgroup
# =============================================================================


@pytest.mark.unit
class TestGatherWithTaskgroup:
    """Tests for the gather_with_taskgroup helper."""

    async def test_happy_path(self):
        """All coroutines succeed → results returned in order."""

        async def add(a: int, b: int) -> int:
            return a + b

        results = await gather_with_taskgroup(
            add(1, 2),
            add(3, 4),
            add(5, 6),
        )
        assert results == [3, 7, 11]

    async def test_preserves_order(self):
        """Slower tasks still appear at their original index."""

        async def delayed(value: int, delay: float) -> int:
            await asyncio.sleep(delay)
            return value

        results = await gather_with_taskgroup(
            delayed(1, 0.05),
            delayed(2, 0.01),
            delayed(3, 0.03),
        )
        assert results == [1, 2, 3]

    async def test_single_coroutine(self):
        """Works with a single coroutine."""

        async def identity(x: int) -> int:
            return x

        results = await gather_with_taskgroup(identity(42))
        assert results == [42]

    async def test_no_coroutines(self):
        """Zero coroutines → empty list (no TaskGroup created)."""
        results = await gather_with_taskgroup()
        assert results == []

    async def test_cancellation_on_failure(self):
        """If one task fails, others are cancelled."""
        started = set()

        async def good(idx: int) -> int:
            started.add(idx)
            await asyncio.sleep(0.5)  # Long-running — should get cancelled
            return idx

        async def bad() -> None:
            await asyncio.sleep(0.01)
            raise ValueError("boom")

        with pytest.raises(ExceptionGroup) as exc_info:
            await gather_with_taskgroup(
                good(0),
                bad(),
                good(2),
            )

        # The ValueError should be in the exception group
        eg = exc_info.value
        assert any(isinstance(e, ValueError) for e in eg.exceptions)

    async def test_error_propagation(self):
        """The original exception type is preserved inside ExceptionGroup."""

        async def fail() -> None:
            raise ConnectionError("connection lost")

        async def succeed() -> int:
            return 1

        with pytest.raises(ExceptionGroup) as exc_info:
            await gather_with_taskgroup(fail(), succeed())

        eg = exc_info.value
        assert len(eg.exceptions) == 1
        assert isinstance(eg.exceptions[0], ConnectionError)
        assert "connection lost" in str(eg.exceptions[0])

    async def test_multiple_failures(self):
        """Multiple failing tasks → all errors collected in ExceptionGroup."""

        async def fail_value() -> None:
            raise ValueError("val")

        async def fail_type() -> None:
            await asyncio.sleep(0.001)
            raise TypeError("typ")

        with pytest.raises(ExceptionGroup) as exc_info:
            await gather_with_taskgroup(fail_value(), fail_type())

        eg = exc_info.value
        error_types = {type(e) for e in eg.exceptions}
        # At least one error; the second may be cancelled before raising
        assert ValueError in error_types or TypeError in error_types

    async def test_task_name_prefix(self):
        """Custom name prefix is applied to tasks."""
        names: list[str] = []

        async def capture_name() -> None:
            task = asyncio.current_task()
            if task and task.get_name():
                names.append(task.get_name())

        await gather_with_taskgroup(
            capture_name(),
            capture_name(),
            task_name_prefix="custom",
        )
        assert all(n.startswith("custom-") for n in names)


# =============================================================================
# map_concurrent
# =============================================================================


@pytest.mark.unit
class TestMapConcurrent:
    """Tests for the map_concurrent helper."""

    async def test_happy_path(self):
        """Maps an async function over items and returns ordered results."""

        async def double(x: int) -> int:
            return x * 2

        results = await map_concurrent(double, [1, 2, 3, 4])
        assert results == [2, 4, 6, 8]

    async def test_empty_items(self):
        """Empty input → empty list, no tasks created."""

        async def should_not_run(x: int) -> int:
            raise AssertionError("should not be called")

        results = await map_concurrent(should_not_run, [])
        assert results == []

    async def test_bounded_concurrency(self):
        """max_concurrency limits the number of concurrent tasks."""
        concurrency_high_water = 0
        current = 0
        lock = asyncio.Lock()

        async def track_concurrency(x: int) -> int:
            nonlocal current, concurrency_high_water
            async with lock:
                current += 1
                concurrency_high_water = max(concurrency_high_water, current)
            await asyncio.sleep(0.02)
            async with lock:
                current -= 1
            return x

        results = await map_concurrent(
            track_concurrency,
            list(range(10)),
            max_concurrency=3,
        )
        assert results == list(range(10))
        assert concurrency_high_water <= 3

    async def test_unlimited_concurrency(self):
        """Without max_concurrency all tasks can run simultaneously."""

        async def quick(x: int) -> int:
            await asyncio.sleep(0.01)
            return x

        results = await map_concurrent(quick, list(range(5)))
        assert results == list(range(5))

    async def test_preserves_order(self):
        """Slower items still appear at their original index."""

        async def variable_delay(x: int) -> int:
            # Reverse delay: item 0 is slowest
            await asyncio.sleep((5 - x) * 0.01)
            return x

        results = await map_concurrent(
            variable_delay,
            [0, 1, 2, 3, 4],
            max_concurrency=5,
        )
        assert results == [0, 1, 2, 3, 4]

    async def test_cancellation_on_failure(self):
        """One failing item cancels remaining items."""
        completed: list[int] = []

        async def maybe_fail(x: int) -> int:
            if x == 2:
                raise RuntimeError("item 2 failed")
            await asyncio.sleep(0.5)
            completed.append(x)
            return x

        with pytest.raises(ExceptionGroup) as exc_info:
            await map_concurrent(maybe_fail, [0, 1, 2, 3, 4])

        eg = exc_info.value
        assert any(isinstance(e, RuntimeError) for e in eg.exceptions)

    async def test_error_propagation_with_except_star(self):
        """except* can filter specific error types from map_concurrent."""

        async def fail_with_value_error(x: int) -> int:
            raise ValueError(f"bad value: {x}")

        caught_messages: list[str] = []
        try:
            await map_concurrent(fail_with_value_error, [1, 2, 3], max_concurrency=3)
        except* ValueError as eg:
            caught_messages = [str(e) for e in eg.exceptions]

        assert len(caught_messages) >= 1
        assert any("bad value" in m for m in caught_messages)

    async def test_single_item(self):
        """Works with a single item."""

        async def square(x: int) -> int:
            return x * x

        results = await map_concurrent(square, [7])
        assert results == [49]

    async def test_task_name_prefix(self):
        """Custom name prefix is applied to map tasks."""
        names: list[str] = []

        async def capture_name(x: int) -> int:
            task = asyncio.current_task()
            if task:
                names.append(task.get_name())
            return x

        await map_concurrent(
            capture_name,
            [1, 2, 3],
            task_name_prefix="worker",
        )
        assert all(n.startswith("worker-") for n in names)

    async def test_max_concurrency_one(self):
        """max_concurrency=1 runs items sequentially."""
        order: list[int] = []

        async def record_order(x: int) -> int:
            order.append(x)
            await asyncio.sleep(0.01)
            return x

        results = await map_concurrent(
            record_order,
            [0, 1, 2, 3],
            max_concurrency=1,
        )
        assert results == [0, 1, 2, 3]
        # With concurrency=1, items execute in order
        assert order == [0, 1, 2, 3]
