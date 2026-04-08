"""Tests for services.graph.neo4j_resilience — retry decorators and error classification."""

from unittest.mock import MagicMock, patch

import pytest
from neo4j.exceptions import (
    AuthError,
    CypherSyntaxError,
    DatabaseUnavailable,
    ServiceUnavailable,
    SessionExpired,
    TransientError,
)

from services.graph.neo4j_resilience import (
    PERMANENT_EXCEPTIONS,
    TRANSIENT_EXCEPTIONS,
    execute_with_error_handling,
    is_transient,
    neo4j_read_retry,
    neo4j_write_retry,
)


class TestIsTransient:
    """Tests for is_transient() classification."""

    @pytest.mark.parametrize(
        "exc_cls",
        [ServiceUnavailable, SessionExpired, TransientError, DatabaseUnavailable, ConnectionError],
    )
    def test_transient_exceptions_classified(self, exc_cls):
        assert is_transient(exc_cls("test")) is True

    @pytest.mark.parametrize("exc_cls", [AuthError, CypherSyntaxError, ValueError, KeyError])
    def test_permanent_exceptions_classified(self, exc_cls):
        assert is_transient(exc_cls("test")) is False

    def test_constants_are_tuples(self):
        assert isinstance(TRANSIENT_EXCEPTIONS, tuple)
        assert isinstance(PERMANENT_EXCEPTIONS, tuple)


class TestNeo4jReadRetry:
    """Tests for neo4j_read_retry decorator."""

    @patch("services.graph.neo4j_resilience.time.sleep")
    def test_retries_on_transient_error(self, mock_sleep):
        call_count = 0

        @neo4j_read_retry(max_retries=2, base_delay=0.1)
        def flaky_read():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ServiceUnavailable("connection lost")
            return "success"

        result = flaky_read()
        assert result == "success"
        assert call_count == 3
        assert mock_sleep.call_count == 2

    @patch("services.graph.neo4j_resilience.time.sleep")
    def test_raises_after_exhausting_retries(self, mock_sleep):
        @neo4j_read_retry(max_retries=2, base_delay=0.1)
        def always_fails():
            raise ServiceUnavailable("down")

        with pytest.raises(ServiceUnavailable):
            always_fails()
        assert mock_sleep.call_count == 2

    def test_does_not_retry_permanent_errors(self):
        @neo4j_read_retry(max_retries=3)
        def syntax_error():
            raise CypherSyntaxError("bad query")

        with pytest.raises(CypherSyntaxError):
            syntax_error()

    def test_does_not_retry_auth_errors(self):
        @neo4j_read_retry(max_retries=3)
        def auth_fail():
            raise AuthError("invalid credentials")

        with pytest.raises(AuthError):
            auth_fail()

    def test_succeeds_without_retry(self):
        @neo4j_read_retry(max_retries=3)
        def ok():
            return 42

        assert ok() == 42

    @patch("services.graph.neo4j_resilience.time.sleep")
    def test_exponential_backoff(self, mock_sleep):
        call_count = 0

        @neo4j_read_retry(max_retries=3, base_delay=1.0, backoff_factor=2.0, max_delay=8.0)
        def fail_3_times():
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                raise TransientError("transient")
            return "ok"

        result = fail_3_times()
        assert result == "ok"
        delays = [c.args[0] for c in mock_sleep.call_args_list]
        assert delays == [1.0, 2.0, 4.0]

    @patch("services.graph.neo4j_resilience.time.sleep")
    def test_max_delay_cap(self, mock_sleep):
        call_count = 0

        @neo4j_read_retry(max_retries=3, base_delay=4.0, backoff_factor=3.0, max_delay=5.0)
        def capped():
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                raise SessionExpired("expired")
            return "ok"

        capped()
        delays = [c.args[0] for c in mock_sleep.call_args_list]
        # 4.0, min(12.0, 5.0)=5.0, min(36.0, 5.0)=5.0
        assert delays == [4.0, 5.0, 5.0]


class TestNeo4jWriteRetry:
    """Tests for neo4j_write_retry decorator."""

    @patch("services.graph.neo4j_resilience.time.sleep")
    def test_single_retry_on_transient(self, mock_sleep):
        call_count = 0

        @neo4j_write_retry(max_retries=1, base_delay=0.1)
        def flaky_write():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ServiceUnavailable("connection lost")
            return "written"

        result = flaky_write()
        assert result == "written"
        assert call_count == 2
        mock_sleep.assert_called_once_with(0.1)

    @patch("services.graph.neo4j_resilience.time.sleep")
    def test_raises_after_single_retry(self, mock_sleep):
        @neo4j_write_retry(max_retries=1, base_delay=0.1)
        def always_fails():
            raise DatabaseUnavailable("down")

        with pytest.raises(DatabaseUnavailable):
            always_fails()
        assert mock_sleep.call_count == 1

    def test_does_not_retry_permanent_errors(self):
        @neo4j_write_retry(max_retries=1)
        def bad_write():
            raise CypherSyntaxError("bad query")

        with pytest.raises(CypherSyntaxError):
            bad_write()

    def test_succeeds_without_retry(self):
        @neo4j_write_retry(max_retries=1)
        def ok_write():
            return "merged"

        assert ok_write() == "merged"


class TestExecuteWithErrorHandling:
    """Tests for execute_with_error_handling()."""

    def test_returns_result_on_success(self):
        fn = MagicMock(return_value=42)
        result = execute_with_error_handling(fn, query_name="test_query")
        assert result == 42
        fn.assert_called_once()

    def test_logs_and_reraises_transient(self):
        fn = MagicMock(side_effect=ServiceUnavailable("conn lost"))
        with pytest.raises(ServiceUnavailable):
            execute_with_error_handling(fn, query_name="read_nodes")

    def test_logs_and_reraises_permanent(self):
        fn = MagicMock(side_effect=CypherSyntaxError("bad"))
        with pytest.raises(CypherSyntaxError):
            execute_with_error_handling(fn, query_name="bad_query")

    def test_passes_args_and_kwargs(self):
        fn = MagicMock(return_value="ok")
        execute_with_error_handling(fn, "arg1", "arg2", query_name="q", kw1="v1")
        fn.assert_called_once_with("arg1", "arg2", kw1="v1")

    def test_preserves_function_name(self):
        @neo4j_read_retry(max_retries=0)
        def my_func():
            return 1

        assert my_func.__name__ == "my_func"
