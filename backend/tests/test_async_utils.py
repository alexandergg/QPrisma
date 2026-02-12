"""
Tests for core/async_utils.py

Covers run_sync, async_wrap, file operations, and executor management.
"""


import pytest

from core.async_utils import (
    async_wrap,
    get_executor,
    read_file_async,
    run_sync,
    write_file_async,
)

# =============================================================================
# run_sync
# =============================================================================


@pytest.mark.unit
class TestRunSync:
    async def test_basic_execution(self):
        def add(a, b):
            return a + b

        result = await run_sync(add, 2, 3)
        assert result == 5

    async def test_with_kwargs(self):
        def greet(name, greeting="Hello"):
            return f"{greeting}, {name}!"

        result = await run_sync(greet, "World", greeting="Hi")
        assert result == "Hi, World!"

    async def test_exception_propagation(self):
        def fail():
            raise ValueError("Boom")

        with pytest.raises(ValueError, match="Boom"):
            await run_sync(fail)

    async def test_returns_none(self):
        def noop():
            pass

        result = await run_sync(noop)
        assert result is None


# =============================================================================
# async_wrap
# =============================================================================


@pytest.mark.unit
class TestAsyncWrap:
    async def test_wraps_function(self):
        def multiply(a, b):
            return a * b

        async_multiply = async_wrap(multiply)
        result = await async_multiply(3, 4)
        assert result == 12

    async def test_preserves_args_and_kwargs(self):
        def func(a, b, c=10):
            return a + b + c

        async_func = async_wrap(func)
        result = await async_func(1, 2, c=100)
        assert result == 103


# =============================================================================
# File Operations
# =============================================================================


@pytest.mark.unit
class TestFileOperations:
    async def test_write_and_read(self, tmp_path):
        filepath = str(tmp_path / "test.txt")
        await write_file_async(filepath, "Hello World")
        content = await read_file_async(filepath)
        assert content == "Hello World"

    async def test_read_binary(self, tmp_path):
        filepath = str(tmp_path / "test.bin")
        await write_file_async(filepath, b"\x00\x01\x02", mode="wb")
        content = await read_file_async(filepath, mode="rb")
        assert content == b"\x00\x01\x02"


# =============================================================================
# Executor
# =============================================================================


@pytest.mark.unit
class TestExecutor:
    def test_get_executor(self):
        executor = get_executor()
        assert executor is not None
        assert executor._max_workers == 4
