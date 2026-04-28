"""Tests for services/foundry_agent_client.py."""

from __future__ import annotations

import types
from unittest.mock import AsyncMock, patch

import pytest

from services.foundry_agent_client import FoundryAgentClient


@pytest.mark.unit
def test_get_openai_client_binds_agent_endpoint():
    calls: dict[str, object] = {}
    fake_openai_client = object()

    class FakeCredential:
        pass

    class FakeProjectClient:
        def __init__(self, *, endpoint: str, credential: FakeCredential, allow_preview: bool):
            calls["project_init"] = {
                "endpoint": endpoint,
                "credential_type": type(credential).__name__,
                "allow_preview": allow_preview,
            }

        def get_openai_client(self, **kwargs):
            calls["get_openai_client"] = kwargs
            return fake_openai_client

    client = FoundryAgentClient(
        project_endpoint="https://example.services.ai.azure.com/api/projects/demo",
        agent_name="qprisma-video-agent",
    )

    with (
        patch("azure.ai.projects.AIProjectClient", FakeProjectClient),
        patch("azure.identity.DefaultAzureCredential", FakeCredential),
    ):
        openai_client = client._get_openai_client()

    assert openai_client is fake_openai_client
    assert calls["project_init"] == {
        "endpoint": "https://example.services.ai.azure.com/api/projects/demo",
        "credential_type": "FakeCredential",
        "allow_preview": True,
    }
    assert calls["get_openai_client"] == {"agent_name": "qprisma-video-agent"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_message_uses_bound_agent_client_without_agent_reference():
    calls: list[dict[str, object]] = []

    class FakeResponsesClient:
        def create(self, **kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(id="resp_123", output_text="Agent response")

    fake_openai_client = types.SimpleNamespace(responses=FakeResponsesClient())

    client = FoundryAgentClient(
        project_endpoint="https://example.services.ai.azure.com/api/projects/demo",
        agent_name="qprisma-video-agent",
    )

    with patch.object(client, "_get_openai_client", return_value=fake_openai_client):
        result = await client.send_message(
            "What happens first?",
            media_id="vid_123",
            user_id="user_456",
            session_id="conv_abc",
            conversation_id="conv_abc",
        )

    assert result == {
        "content": "Agent response",
        "thread_id": "resp_123",
        "conversation_id": "conv_abc",
        "metadata": {
            "media_id": "vid_123",
            "user_id": "user_456",
            "session_id": "conv_abc",
        },
    }
    assert calls == [
        {
            "input": [{"role": "user", "content": "What happens first?"}],
            "metadata": {
                "media_id": "vid_123",
                "user_id": "user_456",
                "session_id": "conv_abc",
            },
            "conversation": "conv_abc",
        }
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_message_includes_multi_video_context():
    calls: list[dict[str, object]] = []

    class FakeResponsesClient:
        def create(self, **kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(id="resp_multi", output_text="Agent response")

    fake_openai_client = types.SimpleNamespace(responses=FakeResponsesClient())

    client = FoundryAgentClient(
        project_endpoint="https://example.services.ai.azure.com/api/projects/demo",
        agent_name="qprisma-video-agent",
    )

    with patch.object(client, "_get_openai_client", return_value=fake_openai_client):
        await client.send_message(
            "Compare these videos.",
            media_ids=["vid_a", "vid_b"],
            user_id="user_456",
            session_id="conv_multi",
            conversation_id="conv_multi",
        )

    assert calls == [
        {
            "input": [{"role": "user", "content": "Compare these videos."}],
            "metadata": {
                "media_ids": ["vid_a", "vid_b"],
                "user_id": "user_456",
                "session_id": "conv_multi",
            },
            "conversation": "conv_multi",
        }
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_message_retries_with_new_conversation_when_stale():
    calls: list[dict[str, object]] = []
    stale_conversation_id = "conv_stale\r\nforged"

    class FakeResponsesClient:
        def create(self, **kwargs):
            calls.append(kwargs)
            if kwargs.get("conversation") == stale_conversation_id:
                raise RuntimeError("conversation not found")
            return types.SimpleNamespace(id="resp_456", output_text="Recovered response")

    fake_openai_client = types.SimpleNamespace(responses=FakeResponsesClient())

    client = FoundryAgentClient(
        project_endpoint="https://example.services.ai.azure.com/api/projects/demo",
        agent_name="qprisma-video-agent",
    )

    with (
        patch.object(client, "_get_openai_client", return_value=fake_openai_client),
        patch.object(client, "_is_retriable", return_value=True),
        patch.object(client, "create_conversation", AsyncMock(return_value="conv_fresh")),
        patch("services.foundry_agent_client.logger.warning") as warning_mock,
    ):
        result = await client.send_message(
            "Try again",
            media_id="vid_999",
            user_id="user_456",
            session_id=stale_conversation_id,
            conversation_id=stale_conversation_id,
        )

    assert result == {
        "content": "Recovered response",
        "thread_id": "resp_456",
        "conversation_id": "conv_fresh",
        "metadata": {
            "media_id": "vid_999",
            "user_id": "user_456",
            "session_id": "conv_fresh",
        },
    }
    warning_mock.assert_called_once_with(
        "Retrying send_message with new conversation",
        extra={"agent_name": "qprisma-video-agent"},
    )
    assert calls == [
        {
            "input": [{"role": "user", "content": "Try again"}],
            "metadata": {
                "media_id": "vid_999",
                "user_id": "user_456",
                "session_id": "conv_stale\r\nforged",
            },
            "conversation": "conv_stale\r\nforged",
        },
        {
            "input": [{"role": "user", "content": "Try again"}],
            "metadata": {
                "media_id": "vid_999",
                "user_id": "user_456",
                "session_id": "conv_fresh",
            },
            "conversation": "conv_fresh",
        },
    ]


@pytest.mark.unit
def test_sanitize_log_value_strips_control_chars_and_truncates():
    assert FoundryAgentClient._sanitize_log_value("abc\r\ndef\tghi", max_len=10) == "abcdefghi"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_message_failure_logs_without_request_fields():
    class FakeResponsesClient:
        def create(self, **kwargs):
            raise RuntimeError("request failed")

    fake_openai_client = types.SimpleNamespace(responses=FakeResponsesClient())
    client = FoundryAgentClient(
        project_endpoint="https://example.services.ai.azure.com/api/projects/demo",
        agent_name="qprisma-video-agent",
    )

    with (
        patch.object(client, "_get_openai_client", return_value=fake_openai_client),
        patch("services.foundry_agent_client.logger.exception") as exception_mock,
        pytest.raises(RuntimeError, match="request failed"),
    ):
        await client.send_message("Try again", media_id="vid_999\r\nforged")

    exception_mock.assert_called_once_with(
        "Foundry agent call failed",
        extra={"agent_name": "qprisma-video-agent"},
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_streaming_message_failure_logs_without_request_fields():
    class FakeResponsesClient:
        def create(self, **kwargs):
            raise RuntimeError("stream failed")

    fake_openai_client = types.SimpleNamespace(responses=FakeResponsesClient())
    client = FoundryAgentClient(
        project_endpoint="https://example.services.ai.azure.com/api/projects/demo",
        agent_name="qprisma-video-agent",
    )

    with (
        patch.object(client, "_get_openai_client", return_value=fake_openai_client),
        patch("services.foundry_agent_client.logger.exception") as exception_mock,
    ):
        events = [
            event
            async for event in client.send_streaming_message(
                "Try again",
                media_id="vid_999\r\nforged",
            )
        ]

    assert events == [{"type": "error", "content": "stream failed"}]
    exception_mock.assert_called_once_with(
        "Foundry streaming failed",
        extra={"agent_name": "qprisma-video-agent"},
    )
