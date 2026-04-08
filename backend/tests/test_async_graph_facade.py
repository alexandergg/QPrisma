"""Tests for AsyncKnowledgeGraphFacade and async retry decorators.

Verifies:
- Sync methods are auto-wrapped as async via __getattr__
- Wrapping cache prevents repeated delegation overhead
- Properties (is_connected, sync_service) bypass wrapping
- connect() / disconnect() delegate to sync service via to_thread
- Singleton lifecycle (get_async_knowledge_graph_facade)
- Async retry decorators (read and write variants)
"""

from unittest.mock import MagicMock, patch

import pytest

from services.async_graph_facade import (
    AsyncKnowledgeGraphFacade,
    get_async_knowledge_graph_facade,
)

# =============================================================================
# Helpers
# =============================================================================


def _make_sync_service(**overrides: object) -> MagicMock:
    """Build a mock KnowledgeGraphService with sane defaults."""
    svc = MagicMock()
    svc.is_connected = overrides.pop("is_connected", True)
    svc.connect.return_value = True
    svc.disconnect.return_value = None
    svc.get_stats.return_value = {"nodes": 42}
    svc.get_video_node.return_value = {"id": "v1"}
    svc.expand_context.return_value = {"center_node_id": "n1"}
    for k, v in overrides.items():
        setattr(svc, k, v)
    return svc


# =============================================================================
# AsyncKnowledgeGraphFacade — core behaviour
# =============================================================================


@pytest.mark.unit
class TestAsyncGraphFacade:
    """Tests for the async facade wrapper."""

    @pytest.mark.asyncio
    async def test_auto_wraps_sync_method_as_async(self):
        """Calling a sync method through the facade returns an awaitable."""
        svc = _make_sync_service()
        facade = AsyncKnowledgeGraphFacade(svc)

        result = await facade.get_stats(user_id="u1")

        svc.get_stats.assert_called_once_with(user_id="u1")
        assert result == {"nodes": 42}

    @pytest.mark.asyncio
    async def test_wrapper_is_cached(self):
        """Second access to the same method returns the cached wrapper."""
        svc = _make_sync_service()
        facade = AsyncKnowledgeGraphFacade(svc)

        wrapper_a = facade.get_stats
        wrapper_b = facade.get_stats
        assert wrapper_a is wrapper_b

    @pytest.mark.asyncio
    async def test_non_callable_attribute_passed_through(self):
        """Non-callable attributes are returned directly without wrapping."""
        svc = _make_sync_service()
        svc.some_value = 99
        facade = AsyncKnowledgeGraphFacade(svc)

        assert facade.some_value == 99

    @pytest.mark.asyncio
    async def test_multiple_methods_cached_independently(self):
        """Different methods are cached independently."""
        svc = _make_sync_service()
        facade = AsyncKnowledgeGraphFacade(svc)

        await facade.get_stats(user_id="u1")
        await facade.get_video_node("v1")

        svc.get_stats.assert_called_once()
        svc.get_video_node.assert_called_once_with("v1")

    @pytest.mark.asyncio
    async def test_kwargs_forwarded_correctly(self):
        """Mixed positional and keyword args pass through to the sync method."""
        svc = _make_sync_service()
        facade = AsyncKnowledgeGraphFacade(svc)

        await facade.expand_context(node_id="n1", hops=2, max_nodes=10, user_id="u1")

        svc.expand_context.assert_called_once_with(node_id="n1", hops=2, max_nodes=10, user_id="u1")


# =============================================================================
# Properties
# =============================================================================


@pytest.mark.unit
class TestFacadeProperties:
    """Verify properties bypass the auto-wrapping layer."""

    def test_is_connected_reflects_sync_service(self):
        svc = _make_sync_service(is_connected=True)
        facade = AsyncKnowledgeGraphFacade(svc)
        assert facade.is_connected is True

    def test_is_connected_reflects_disconnected(self):
        svc = _make_sync_service(is_connected=False)
        facade = AsyncKnowledgeGraphFacade(svc)
        assert facade.is_connected is False

    def test_sync_service_property(self):
        svc = _make_sync_service()
        facade = AsyncKnowledgeGraphFacade(svc)
        assert facade.sync_service is svc

    def test_repr(self):
        svc = _make_sync_service(is_connected=True)
        facade = AsyncKnowledgeGraphFacade(svc)
        assert "connected=True" in repr(facade)


# =============================================================================
# Lifecycle: connect / disconnect
# =============================================================================


@pytest.mark.unit
class TestFacadeLifecycle:
    @pytest.mark.asyncio
    async def test_connect_delegates_to_sync(self):
        svc = _make_sync_service()
        facade = AsyncKnowledgeGraphFacade(svc)

        result = await facade.connect()

        svc.connect.assert_called_once()
        assert result is True

    @pytest.mark.asyncio
    async def test_disconnect_delegates_to_sync(self):
        svc = _make_sync_service()
        facade = AsyncKnowledgeGraphFacade(svc)

        await facade.disconnect()

        svc.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_failure_propagates(self):
        svc = _make_sync_service()
        svc.connect.side_effect = ConnectionError("refused")
        facade = AsyncKnowledgeGraphFacade(svc)

        with pytest.raises(ConnectionError, match="refused"):
            await facade.connect()


# =============================================================================
# Singleton: get_async_knowledge_graph_facade
# =============================================================================


@pytest.mark.unit
class TestFacadeSingleton:
    def test_singleton_returns_same_instance(self):
        import services.async_graph_facade as mod

        mod._async_facade = None

        svc = _make_sync_service()
        with patch(
            "services.knowledge_graph.get_knowledge_graph_service",
            return_value=svc,
        ):
            a = get_async_knowledge_graph_facade()
            b = get_async_knowledge_graph_facade()

        assert a is b
        mod._async_facade = None  # cleanup

    def test_singleton_reset_creates_new(self):
        import services.async_graph_facade as mod

        mod._async_facade = None

        svc1 = _make_sync_service()
        svc2 = _make_sync_service()
        with patch(
            "services.knowledge_graph.get_knowledge_graph_service",
            return_value=svc1,
        ):
            a = get_async_knowledge_graph_facade()

        mod._async_facade = None

        with patch(
            "services.knowledge_graph.get_knowledge_graph_service",
            return_value=svc2,
        ):
            b = get_async_knowledge_graph_facade()

        assert a is not b
        mod._async_facade = None  # cleanup


# =============================================================================
# Async retry decorators
# =============================================================================


@pytest.mark.unit
class TestAsyncRetryDecorators:
    """Tests for async_neo4j_read_retry and async_neo4j_write_retry."""

    @pytest.mark.asyncio
    async def test_read_retry_success_on_first_attempt(self):
        from services.graph.neo4j_resilience import async_neo4j_read_retry

        call_count = 0

        @async_neo4j_read_retry(max_retries=2, base_delay=0.01)
        async def my_query():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await my_query()
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_read_retry_retries_on_transient_error(self):
        from neo4j.exceptions import ServiceUnavailable

        from services.graph.neo4j_resilience import async_neo4j_read_retry

        attempts = 0

        @async_neo4j_read_retry(max_retries=2, base_delay=0.01)
        async def flaky_query():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ServiceUnavailable("gone")
            return "recovered"

        result = await flaky_query()
        assert result == "recovered"
        assert attempts == 3

    @pytest.mark.asyncio
    async def test_read_retry_raises_permanent_error_immediately(self):
        from services.graph.neo4j_resilience import async_neo4j_read_retry

        call_count = 0

        @async_neo4j_read_retry(max_retries=3, base_delay=0.01)
        async def bad_query():
            nonlocal call_count
            call_count += 1
            raise ValueError("bad input")

        with pytest.raises(ValueError, match="bad input"):
            await bad_query()
        assert call_count == 1  # no retries for permanent errors

    @pytest.mark.asyncio
    async def test_read_retry_exhausts_retries(self):
        from neo4j.exceptions import ServiceUnavailable

        from services.graph.neo4j_resilience import async_neo4j_read_retry

        @async_neo4j_read_retry(max_retries=2, base_delay=0.01)
        async def always_fail():
            raise ServiceUnavailable("still gone")

        with pytest.raises(ServiceUnavailable):
            await always_fail()

    @pytest.mark.asyncio
    async def test_write_retry_success(self):
        from services.graph.neo4j_resilience import async_neo4j_write_retry

        @async_neo4j_write_retry(max_retries=1, base_delay=0.01)
        async def write_op():
            return "written"

        assert await write_op() == "written"

    @pytest.mark.asyncio
    async def test_write_retry_retries_once_on_transient(self):
        from neo4j.exceptions import ServiceUnavailable

        from services.graph.neo4j_resilience import async_neo4j_write_retry

        attempts = 0

        @async_neo4j_write_retry(max_retries=1, base_delay=0.01)
        async def write_op():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ServiceUnavailable("transient")
            return "ok"

        result = await write_op()
        assert result == "ok"
        assert attempts == 2
