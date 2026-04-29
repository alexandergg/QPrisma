"""
Tests for A2A route rate limiting.

Verifies that rate-limited A2A endpoints include the correct
X-RateLimit headers, and that discovery/health endpoints are NOT
rate-limited.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.a2a_models import (
    Message,
    Part,
    Role,
    Task,
    TaskState,
    TaskStatus,
)

# =============================================================================
# Helpers
# =============================================================================


def _make_send_body() -> dict:
    """Minimal valid SendMessageRequest JSON payload."""
    return {
        "message": {
            "role": "ROLE_USER",
            "parts": [{"text": "hello"}],
        }
    }


def _make_task(
    task_id: str = "task-1",
    state: TaskState = TaskState.COMPLETED,
    user_id: str = "user_test123",
) -> Task:
    return Task(
        id=task_id,
        contextId="ctx-1",
        status=TaskStatus(
            state=state,
            message=Message(role=Role.AGENT, parts=[Part(text="done")]),
        ),
        metadata={"user_id": user_id},
    )


# =============================================================================
# Rate-limited endpoints (should have X-RateLimit-Limit header)
# =============================================================================


@pytest.mark.unit
class TestMessageEndpointRateLimits:
    """POST /a2a/message:send, /a2a/message:stream."""

    def test_send_message_has_rate_limit_header(self, authenticated_client):
        mock_executor = MagicMock()
        mock_executor.send_message = AsyncMock(return_value=_make_task())

        with patch("api.routes.a2a_message_routes.get_executor", return_value=mock_executor):
            resp = authenticated_client.post("/a2a/message:send", json=_make_send_body())

        assert resp.status_code == 200
        assert "x-ratelimit-limit" in resp.headers
        assert resp.headers["x-ratelimit-limit"] == "60"

    def test_stream_message_has_rate_limit_header(self, authenticated_client):
        async def _fake_stream(req):
            return
            yield  # make it an async generator  # noqa: E501 — unreachable yield makes this a generator

        mock_executor = MagicMock()
        mock_executor.send_streaming_message = _fake_stream

        with patch("api.routes.a2a_message_routes.get_executor", return_value=mock_executor):
            resp = authenticated_client.post("/a2a/message:stream", json=_make_send_body())

        assert resp.status_code == 200
        assert "x-ratelimit-limit" in resp.headers
        assert resp.headers["x-ratelimit-limit"] == "60"


@pytest.mark.unit
class TestTaskEndpointRateLimits:
    """GET /a2a/tasks/{id}, GET /a2a/tasks, POST cancel, POST subscribe."""

    def test_get_task_rate_limit_120(self, authenticated_client):
        mock_executor = MagicMock()
        mock_executor.get_task = AsyncMock(return_value=_make_task("t-1"))

        with patch("api.routes.a2a_task_routes.get_executor", return_value=mock_executor):
            resp = authenticated_client.get("/a2a/tasks/t-1")

        assert resp.status_code == 200
        assert resp.headers.get("x-ratelimit-limit") == "120"

    def test_list_tasks_rate_limit_60(self, authenticated_client):
        mock_executor = MagicMock()
        mock_executor.list_tasks = AsyncMock(return_value=([], 0))

        with patch("api.routes.a2a_task_routes.get_executor", return_value=mock_executor):
            resp = authenticated_client.get("/a2a/tasks")

        assert resp.status_code == 200
        assert resp.headers.get("x-ratelimit-limit") == "60"

    def test_cancel_task_rate_limit_30(self, authenticated_client):
        mock_executor = MagicMock()
        mock_executor.get_task = AsyncMock(return_value=_make_task("t-1", TaskState.WORKING))
        mock_executor.cancel_task = AsyncMock(return_value=_make_task("t-1", TaskState.CANCELED))

        with patch("api.routes.a2a_task_routes.get_executor", return_value=mock_executor):
            resp = authenticated_client.post("/a2a/tasks/t-1:cancel")

        assert resp.status_code == 200
        assert resp.headers.get("x-ratelimit-limit") == "30"

    def test_subscribe_task_rate_limit_60(self, authenticated_client):
        working_task = _make_task("t-1", TaskState.WORKING)
        mock_executor = MagicMock()
        mock_executor.get_task = AsyncMock(return_value=working_task)

        with patch("api.routes.a2a_task_routes.get_executor", return_value=mock_executor):
            resp = authenticated_client.post("/a2a/tasks/t-1:subscribe")

        assert resp.status_code == 200
        assert resp.headers.get("x-ratelimit-limit") == "60"


# =============================================================================
# Discovery / health endpoints (should NOT have rate-limit header)
# =============================================================================


@pytest.mark.unit
class TestDiscoveryEndpointsNotRateLimited:
    """Discovery and health endpoints must remain unrestricted."""

    def test_well_known_agent_card_no_rate_limit(self, client):
        resp = client.get("/.well-known/agent-card.json")
        assert resp.status_code == 200
        assert "x-ratelimit-limit" not in resp.headers

    def test_a2a_agent_card_no_rate_limit(self, client):
        resp = client.get("/a2a/agent-card.json")
        assert resp.status_code == 200
        assert "x-ratelimit-limit" not in resp.headers
        assert resp.json()["securitySchemes"]["bearerAuth"]["scheme"] == "bearer"
        assert resp.json()["security"] == [{"bearerAuth": []}]

    def test_health_no_rate_limit(self, client):
        resp = client.get("/a2a/health")
        assert resp.status_code == 200
        assert "x-ratelimit-limit" not in resp.headers
