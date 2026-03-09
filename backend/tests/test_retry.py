"""
Tests for core/retry.py

Covers retry_async helper and retry_on decorator.
"""

import asyncio

import pytest

from core.retry import retry_async, retry_on

# =============================================================================
# retry_async
# =============================================================================


@pytest.mark.unit
class TestRetryAsync:
    @pytest.mark.asyncio
    async def test_succeeds_first_attempt(self):
        call_count = 0

        async def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await retry_async(succeed, max_retries=3, base_delay=0)
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_failure_then_succeeds(self):
        call_count = 0

        async def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("transient")
            return "recovered"

        result = await retry_async(
            fail_twice,
            max_retries=3,
            base_delay=0,
            retryable_exceptions=(ConnectionError,),
            operation_name="test_op",
        )
        assert result == "recovered"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self):
        call_count = 0

        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise TimeoutError("always")

        with pytest.raises(TimeoutError, match="always"):
            await retry_async(
                always_fail,
                max_retries=2,
                base_delay=0,
                retryable_exceptions=(TimeoutError,),
            )
        # initial + 2 retries = 3 total attempts
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_non_retryable_exception_not_retried(self):
        call_count = 0

        async def wrong_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("not retryable")

        with pytest.raises(ValueError, match="not retryable"):
            await retry_async(
                wrong_error,
                max_retries=3,
                base_delay=0,
                retryable_exceptions=(ConnectionError,),
            )
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_passes_args_and_kwargs(self):
        async def adder(a, b, extra=0):
            return a + b + extra

        result = await retry_async(adder, 2, 3, extra=10, max_retries=0, base_delay=0)
        assert result == 15

    @pytest.mark.asyncio
    async def test_delay_is_bounded_by_max_delay(self):
        """Ensure backoff doesn't exceed max_delay (logic check, no real sleep)."""
        call_count = 0
        delays_observed = []
        original_sleep = asyncio.sleep

        async def mock_sleep(delay):
            delays_observed.append(delay)
            # Don't actually sleep in tests

        async def fail_thrice():
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                raise ConnectionError("retry me")
            return "done"

        # Monkey-patch sleep temporarily
        import core.retry as retry_mod

        retry_mod.asyncio.sleep = mock_sleep  # type: ignore[attr-defined]
        try:
            result = await retry_async(
                fail_thrice,
                max_retries=4,
                base_delay=1.0,
                max_delay=5.0,
                backoff_factor=10.0,
                retryable_exceptions=(ConnectionError,),
            )
        finally:
            retry_mod.asyncio.sleep = original_sleep  # type: ignore[attr-defined]

        assert result == "done"
        # All delays should be <= max_delay
        for d in delays_observed:
            assert d <= 5.0


# =============================================================================
# retry_on decorator
# =============================================================================


@pytest.mark.unit
class TestRetryOnDecorator:
    @pytest.mark.asyncio
    async def test_decorator_retries_specified_exceptions(self):
        call_count = 0

        @retry_on(ConnectionError, max_retries=2, base_delay=0)
        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("transient")
            return "ok"

        result = await flaky()
        assert result == "ok"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_decorator_preserves_function_name(self):
        @retry_on(Exception, max_retries=1, base_delay=0)
        async def my_named_function():
            return True

        assert my_named_function.__name__ == "my_named_function"

    @pytest.mark.asyncio
    async def test_decorator_raises_on_exhaustion(self):
        @retry_on(RuntimeError, max_retries=1, base_delay=0)
        async def always_fails():
            raise RuntimeError("permanent")

        with pytest.raises(RuntimeError, match="permanent"):
            await always_fails()

    @pytest.mark.asyncio
    async def test_decorator_passes_arguments(self):
        @retry_on(Exception, max_retries=0, base_delay=0)
        async def greet(name: str, excited: bool = False):
            suffix = "!" if excited else "."
            return f"Hello {name}{suffix}"

        assert await greet("World", excited=True) == "Hello World!"
