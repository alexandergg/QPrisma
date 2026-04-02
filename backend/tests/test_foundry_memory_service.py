"""Tests for FoundryMemoryService."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from azure.core.exceptions import ResourceNotFoundError

from services.foundry_memory_service import FoundryMemoryService


def _make_service(**overrides):
    """Create a FoundryMemoryService with test defaults."""
    defaults = {
        "project_endpoint": "https://test.services.ai.azure.com/api/projects/test",
        "memory_store_name": "test-store",
        "chat_model": "gpt-4o",
        "embedding_model": "text-embedding-3-large",
    }
    defaults.update(overrides)
    return FoundryMemoryService(**defaults)


@pytest.mark.unit
class TestFoundryMemoryServiceEnabled:
    def test_enabled_when_all_config_present(self):
        service = _make_service()
        assert service.enabled is True

    def test_disabled_when_endpoint_missing(self):
        service = _make_service(project_endpoint="")
        assert service.enabled is False

    def test_disabled_when_store_name_missing(self):
        service = _make_service(memory_store_name="")
        assert service.enabled is False


@pytest.mark.unit
class TestEnsureMemoryStore:
    @pytest.mark.asyncio
    async def test_returns_error_when_disabled(self):
        service = _make_service(project_endpoint="")
        result = await service.ensure_memory_store()
        assert "error" in result

    @pytest.mark.asyncio
    async def test_returns_existing_store(self):
        service = _make_service()
        mock_store = SimpleNamespace(name="test-store", id="store-123", description="desc")

        mock_client = MagicMock()
        mock_client.beta.memory_stores.get.return_value = mock_store
        service._project_client = mock_client

        with patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
            result = await service.ensure_memory_store()

        assert result["name"] == "test-store"
        assert result["id"] == "store-123"
        mock_client.beta.memory_stores.get.assert_called_once_with("test-store")

    @pytest.mark.asyncio
    async def test_creates_store_when_not_found(self):
        service = _make_service()
        mock_store = SimpleNamespace(name="test-store", id="store-new", description="QPrisma")

        mock_client = MagicMock()
        mock_client.beta.memory_stores.get.side_effect = ResourceNotFoundError("not found")
        mock_client.beta.memory_stores.create.return_value = mock_store
        service._project_client = mock_client

        with patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
            result = await service.ensure_memory_store()

        assert result["name"] == "test-store"
        assert result["id"] == "store-new"
        mock_client.beta.memory_stores.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_propagates_non_not_found_exception(self):
        service = _make_service()

        mock_client = MagicMock()
        mock_client.beta.memory_stores.get.side_effect = PermissionError("forbidden")
        service._project_client = mock_client

        with (
            patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn(*a, **kw)),
            pytest.raises(PermissionError, match="forbidden"),
        ):
            await service.ensure_memory_store()


@pytest.mark.unit
class TestUpdateMemories:
    @pytest.mark.asyncio
    async def test_skipped_when_disabled(self):
        service = _make_service(project_endpoint="")
        result = await service.update_memories(scope="tid_oid", messages="hello")
        assert result["skipped"] is True

    @pytest.mark.asyncio
    async def test_returns_update_id(self):
        service = _make_service()

        mock_poller = SimpleNamespace(update_id="upd-1", status=lambda: "running")
        mock_client = MagicMock()
        mock_client.beta.memory_stores.begin_update_memories.return_value = mock_poller
        service._project_client = mock_client

        with patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
            result = await service.update_memories(scope="tid_oid", messages="hello")

        assert result["update_id"] == "upd-1"
        assert result["status"] == "running"

    @pytest.mark.asyncio
    async def test_returns_error_on_failure(self):
        service = _make_service()

        mock_client = MagicMock()
        mock_client.beta.memory_stores.begin_update_memories.side_effect = RuntimeError("fail")
        service._project_client = mock_client

        with patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
            result = await service.update_memories(scope="tid_oid", messages="hello")

        assert "error" in result


@pytest.mark.unit
class TestSearchMemories:
    @pytest.mark.asyncio
    async def test_returns_empty_when_disabled(self):
        service = _make_service(project_endpoint="")
        result = await service.search_memories(scope="tid_oid", query="test")
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_memories(self):
        service = _make_service()

        mem_item = SimpleNamespace(memory_id="mem-1", content="likes coffee")
        mock_response = SimpleNamespace(
            memories=[SimpleNamespace(memory_item=mem_item)],
        )
        mock_client = MagicMock()
        mock_client.beta.memory_stores.search_memories.return_value = mock_response
        service._project_client = mock_client

        with patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
            result = await service.search_memories(scope="tid_oid", query="coffee preferences")

        assert len(result) == 1
        assert result[0]["memory_id"] == "mem-1"
        assert result[0]["content"] == "likes coffee"

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self):
        service = _make_service()

        mock_client = MagicMock()
        mock_client.beta.memory_stores.search_memories.side_effect = RuntimeError("oops")
        service._project_client = mock_client

        with patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
            result = await service.search_memories(scope="tid_oid", query="test")

        assert result == []


@pytest.mark.unit
class TestDeleteUserMemories:
    @pytest.mark.asyncio
    async def test_returns_false_when_disabled(self):
        service = _make_service(project_endpoint="")
        result = await service.delete_user_memories(scope="tid_oid")
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_on_success(self):
        service = _make_service()

        mock_client = MagicMock()
        mock_client.beta.memory_stores.delete_scope.return_value = None
        service._project_client = mock_client

        with patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
            result = await service.delete_user_memories(scope="tid_oid")

        assert result is True
        mock_client.beta.memory_stores.delete_scope.assert_called_once_with(
            name="test-store", scope="tid_oid"
        )

    @pytest.mark.asyncio
    async def test_returns_false_on_error(self):
        service = _make_service()

        mock_client = MagicMock()
        mock_client.beta.memory_stores.delete_scope.side_effect = RuntimeError("fail")
        service._project_client = mock_client

        with patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
            result = await service.delete_user_memories(scope="tid_oid")

        assert result is False
