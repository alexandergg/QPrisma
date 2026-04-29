from unittest.mock import patch

import pytest
from agent.a2a.executor import EMPTY_RESPONSE_ERROR, A2AAgentExecutor
from agent.a2a.task_store import TaskStore

from models.a2a_models import Message, Part, Role, SendMessageRequest, TaskState


class EmptyFoundryClient:
    async def create_conversation(self) -> str:
        return "conv_test"

    async def send_message(self, **_kwargs) -> dict[str, str]:
        return {"content": "   ", "thread_id": "resp_test", "conversation_id": "conv_test"}

    async def send_streaming_message(self, **_kwargs):
        yield {"type": "done", "content": ""}


def _request() -> SendMessageRequest:
    return SendMessageRequest(
        message=Message(
            role=Role.USER,
            parts=[Part(text="Summarize this video")],
            metadata={"media_id": "media-1", "user_id": "user-1"},
        ),
        metadata={"media_id": "media-1", "user_id": "user-1"},
    )


@pytest.mark.unit
async def test_blocking_message_fails_when_foundry_returns_empty_response():
    with patch("agent.a2a.executor.get_task_store", return_value=TaskStore()):
        executor = A2AAgentExecutor()
    executor._get_foundry_client = lambda: EmptyFoundryClient()

    task = await executor.send_message(_request())

    assert task.status.state == TaskState.FAILED
    assert not task.artifacts
    assert task.status.message is not None
    assert EMPTY_RESPONSE_ERROR in task.status.message.parts[0].text


@pytest.mark.unit
async def test_streaming_message_fails_when_foundry_returns_empty_response():
    with patch("agent.a2a.executor.get_task_store", return_value=TaskStore()):
        executor = A2AAgentExecutor()
    executor._get_foundry_client = lambda: EmptyFoundryClient()

    events = [event async for event in executor.send_streaming_message(_request())]

    final_status = events[-1].statusUpdate.status
    assert final_status.state == TaskState.FAILED
    assert final_status.message is not None
    assert EMPTY_RESPONSE_ERROR in final_status.message.parts[0].text
