"""
Tests for api/routes/chat_routes.py

Covers chat, search, and agent chat endpoints.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.mark.unit
class TestChat:
    def test_requires_auth(self, client):
        resp = client.post("/chat", json={"message": "hello"})
        assert resp.status_code in (401, 403)

    def test_no_openai_returns_503(self, authenticated_client):
        with patch("api.routes.chat_routes.get_async_openai_client", return_value=None):
            resp = authenticated_client.post("/chat", json={"message": "hello"})

        assert resp.status_code == 503

    def test_chat_success(self, authenticated_client, mock_openai_client, mock_graph_search_service):
        with (
            patch("api.routes.chat_routes.get_async_openai_client", return_value=mock_openai_client),
            patch("api.routes.chat_routes.get_graph_search_service", return_value=mock_graph_search_service),
            patch("api.routes.chat_routes.ChatService") as MockChatService,
        ):
            mock_instance = AsyncMock()
            mock_instance.chat = AsyncMock(return_value=("Hello back!", []))
            MockChatService.return_value = mock_instance

            resp = authenticated_client.post("/chat", json={"message": "hello"})

        assert resp.status_code == 200
        assert resp.json()["response"] == "Hello back!"

    def test_chat_with_media_id(self, authenticated_client, mock_openai_client, mock_graph_search_service):
        with (
            patch("api.routes.chat_routes.get_async_openai_client", return_value=mock_openai_client),
            patch("api.routes.chat_routes.get_graph_search_service", return_value=mock_graph_search_service),
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
class TestSearch:
    def test_requires_auth(self, client):
        resp = client.post("/search", json={"query": "test"})
        assert resp.status_code in (401, 403)

    def test_search_success(self, authenticated_client, mock_graph_search_service):
        with patch("api.routes.chat_routes.get_graph_search_service", return_value=mock_graph_search_service):
            resp = authenticated_client.post("/search", json={"query": "people talking"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["query"] == "people talking"
        assert "results" in body


@pytest.mark.unit
class TestAgentChat:
    def test_requires_auth(self, client):
        resp = client.post("/chat/agent", json={"message": "hello"})
        assert resp.status_code in (401, 403)

    def test_agent_chat_success(self, authenticated_client):
        mock_agent = AsyncMock()
        mock_agent.run = AsyncMock(
            return_value={
                "response": "Agent response",
                "sources": [],
                "tool_calls_made": 2,
                "navigation_actions": [],
                "suggested_questions": [],
                "clip_suggestions": [],
                "entities_mentioned": [],
            }
        )

        with (
            patch("agent.create_redis_checkpointer", return_value=None),
            patch("agent.get_video_agent_graph", return_value=mock_agent),
        ):
            resp = authenticated_client.post(
                "/chat/agent",
                json={"message": "find highlights"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["response"] == "Agent response"
        assert body["tool_calls_made"] == 2
        assert body["session_id"] is not None

    def test_agent_chat_with_session_id(self, authenticated_client):
        mock_agent = AsyncMock()
        mock_agent.run = AsyncMock(
            return_value={
                "response": "Continued",
                "sources": [],
                "tool_calls_made": 1,
                "navigation_actions": [],
                "suggested_questions": [],
                "clip_suggestions": [],
                "entities_mentioned": [],
            }
        )

        with (
            patch("agent.create_redis_checkpointer", return_value=None),
            patch("agent.get_video_agent_graph", return_value=mock_agent),
        ):
            resp = authenticated_client.post(
                "/chat/agent",
                json={"message": "more details", "session_id": "sess_abc"},
            )

        assert resp.status_code == 200
        assert resp.json()["session_id"] == "sess_abc"
