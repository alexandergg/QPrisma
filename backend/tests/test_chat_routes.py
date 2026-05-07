"""Tests for removed legacy chat endpoints."""

import pytest


@pytest.mark.unit
class TestClassicChatRemoved:
    """POST /chat was removed in favor of authenticated A2A endpoints."""

    def test_classic_chat_endpoint_removed(self, authenticated_client):
        resp = authenticated_client.post("/chat", json={"message": "hello"})
        assert resp.status_code in (404, 405)

    def test_classic_chat_endpoint_no_longer_prompts_auth(self, client):
        resp = client.post("/chat", json={"message": "hello"})
        assert resp.status_code in (404, 405)


@pytest.mark.unit
class TestSearchRemoved:
    """POST /search was removed — verify endpoint returns 404/405."""

    def test_search_endpoint_removed(self, authenticated_client):
        resp = authenticated_client.post("/search", json={"query": "test"})
        assert resp.status_code in (404, 405)


@pytest.mark.unit
class TestAgentChatRemoved:
    """POST /chat/agent was removed in favor of authenticated A2A endpoints."""

    def test_agent_chat_endpoint_removed(self, authenticated_client):
        resp = authenticated_client.post("/chat/agent", json={"message": "hello"})
        assert resp.status_code in (404, 405)

    def test_agent_chat_endpoint_no_longer_prompts_auth(self, client):
        resp = client.post("/chat/agent", json={"message": "hello"})
        assert resp.status_code in (404, 405)
