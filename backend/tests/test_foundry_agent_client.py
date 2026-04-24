"""Tests for services/foundry_agent_client.py."""

from __future__ import annotations

import types
from unittest.mock import patch

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
            "input": [
                {
                    "role": "user",
                    "content": (
                        '[QPRISMA_CONTEXT:{"media_id":"vid_123","user_id":"user_456",'
                        '"session_id":"conv_abc"}]\nWhat happens first?'
                    ),
                }
            ],
            "conversation": "conv_abc",
        }
    ]
