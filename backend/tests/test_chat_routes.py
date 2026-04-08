"""
Tests for api/routes/chat_routes.py

Covers chat, search, and agent chat endpoints.
"""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.unit
class TestChat:
    def test_requires_auth(self, client):
        resp = client.post("/chat", json={"message": "hello"})
        assert resp.status_code in (401, 403)

    def test_no_openai_returns_503(self, authenticated_client):
        with patch("api.routes.chat_routes.get_async_openai_client", return_value=None):
            resp = authenticated_client.post("/chat", json={"message": "hello"})

        assert resp.status_code == 503

    def test_chat_success(
        self, authenticated_client, mock_openai_client, mock_graph_search_service
    ):
        with (
            patch(
                "api.routes.chat_routes.get_async_openai_client", return_value=mock_openai_client
            ),
            patch(
                "api.routes.chat_routes.get_graph_search_service",
                return_value=mock_graph_search_service,
            ),
            patch("api.routes.chat_routes.ChatService") as MockChatService,
        ):
            mock_instance = AsyncMock()
            mock_instance.chat = AsyncMock(return_value=("Hello back!", []))
            MockChatService.return_value = mock_instance

            resp = authenticated_client.post("/chat", json={"message": "hello"})

        assert resp.status_code == 200
        assert resp.json()["response"] == "Hello back!"

    def test_chat_with_media_id(
        self, authenticated_client, mock_openai_client, mock_graph_search_service
    ):
        with (
            patch(
                "api.routes.chat_routes.get_async_openai_client", return_value=mock_openai_client
            ),
            patch(
                "api.routes.chat_routes.get_graph_search_service",
                return_value=mock_graph_search_service,
            ),
            patch("api.routes.chat_routes.ChatService") as MockChatService,
        ):
            mock_instance = AsyncMock()
            mock_instance.chat = AsyncMock(return_value=("Context reply", []))
            MockChatService.return_value = mock_instance

            resp = authenticated_client.post(
                "/chat",
                json={"message": "what happens?", "media_id": "vid_123"},
            )

        assert resp.status_code == 200

    def test_chat_invalid_body(self, authenticated_client):
        resp = authenticated_client.post("/chat", json={})
        assert resp.status_code == 422


@pytest.mark.unit
class TestSearchRemoved:
    """POST /search was removed — verify endpoint returns 404/405."""

    def test_search_endpoint_removed(self, authenticated_client):
        resp = authenticated_client.post("/search", json={"query": "test"})
        assert resp.status_code in (404, 405)


@pytest.mark.unit
class TestAgentChat:
    def test_requires_auth(self, client):
        resp = client.post("/chat/agent", json={"message": "hello"})
        assert resp.status_code in (401, 403)

    def test_agent_chat_success(self, authenticated_client):
        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(
            return_value={"content": "Agent response", "thread_id": "thread_001"}
        )

        with patch(
            "services.foundry_agent_client.get_foundry_agent_client",
            return_value=mock_client,
        ):
            resp = authenticated_client.post(
                "/chat/agent",
                json={"message": "find highlights"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["response"] == "Agent response"
        assert body["tool_calls_made"] == 0
        assert body["session_id"] is not None

    def test_agent_chat_with_session_id(self, authenticated_client):
        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(
            return_value={"content": "Continued", "thread_id": "sess_abc"}
        )

        with patch(
            "services.foundry_agent_client.get_foundry_agent_client",
            return_value=mock_client,
        ):
            resp = authenticated_client.post(
                "/chat/agent",
                json={"message": "more details", "session_id": "sess_abc"},
            )

        assert resp.status_code == 200
        assert resp.json()["session_id"] == "sess_abc"
