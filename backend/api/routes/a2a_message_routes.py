"""
A2A Message Routes
==================

Send and streaming message endpoints for the Video agent.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse

from agent.utils.observability import set_conversation_id, set_otel_user_id
from api.dependencies import get_current_user
from api.openapi_responses import (
    AUTH_RESPONSES,
    RATE_LIMIT_RESPONSES,
    SSE_STREAM_RESPONSE,
    merge_responses,
)
from api.rate_limit import limiter
from api.routes.a2a_agent_cards import get_executor
from api.routes.a2a_security import authorize_message_continuation, sanitize_message_request
from models.a2a_models import (
    Message,
    Part,
    Role,
    SendMessageRequest,
    SendMessageResponse,
    StreamResponse,
    Task,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from models.user import User

message_router = APIRouter(tags=["A2A Protocol"])
logger = logging.getLogger(__name__)


def _set_otel_context(
    context_id: str | None,
    user: User,
) -> None:
    """Set OpenTelemetry context vars for trace correlation."""
    if context_id:
        set_conversation_id(context_id)
    if user and user.id:
        set_otel_user_id(user.id)


@message_router.post("/a2a/message:send", response_model=SendMessageResponse)
@limiter.limit("60/minute")
async def send_message(
    request: Request,
    body: SendMessageRequest,
    response: Response,
    current_user: Annotated[User, Depends(get_current_user)],
):
    """
    Send a message to the Video Agent.

    Creates a new task or continues an existing one based on taskId/contextId.
    Returns either a Task object or a direct Message response.
    """
    executor = get_executor("video")

    sanitize_message_request(body, current_user)
    await authorize_message_continuation(executor, body, current_user)

    # Set OTel context for trace grouping
    _set_otel_context(body.message.contextId, current_user)

    result = await executor.send_message(body)

    if isinstance(result, Task):
        return SendMessageResponse(task=result)
    else:
        return SendMessageResponse(message=result)


@message_router.post(
    "/a2a/message:stream",
    summary="Send a message with streaming A2A events",
    description=(
        "Authenticated A2A message endpoint returning Server-Sent Events. Each SSE `data:` "
        "line contains a JSON-encoded `StreamResponse` payload."
    ),
    responses=merge_responses(SSE_STREAM_RESPONSE, AUTH_RESPONSES, RATE_LIMIT_RESPONSES),
)
@limiter.limit("60/minute")
async def send_streaming_message(
    request: Request,
    body: SendMessageRequest,
    current_user: Annotated[User, Depends(get_current_user)],
):
    """
    Send a message with streaming response (SSE).

    Returns a Server-Sent Events stream with:
    - Initial Task object
    - TaskStatusUpdateEvent for status changes
    - TaskArtifactUpdateEvent for response chunks
    - Final status update when complete
    """
    executor = get_executor("video")

    sanitize_message_request(body, current_user)
    await authorize_message_continuation(executor, body, current_user)

    # Set OTel context for trace grouping
    _set_otel_context(body.message.contextId, current_user)

    # Diagnostic: log media_id presence for debugging video selection issues
    msg_meta = body.message.metadata or {}
    if "media_id" not in msg_meta:
        logger.warning(
            "Streaming request has no media_id in message.metadata. "
            "Agent will fall back to checkpoint or NO_VIDEO_CONTEXT_PROMPT. "
            "metadata_keys=%s, contextId=%s",
            list(msg_meta.keys()),
            body.message.contextId,
        )
    else:
        logger.info(
            "Streaming request media_id=%s contextId=%s",
            msg_meta.get("media_id"),
            body.message.contextId,
        )

    async def generate_sse():
        """Generate SSE events from streaming response."""
        try:
            async for response in executor.send_streaming_message(body):
                # Serialize to JSON
                data = response.model_dump_json(exclude_none=True)
                yield f"data: {data}\n\n"
        except Exception as e:
            logger.error("SSE streaming error: %s", e)
            error_response = StreamResponse(
                statusUpdate=TaskStatusUpdateEvent(
                    taskId="error",
                    contextId="error",
                    status=TaskStatus(
                        state=TaskState.FAILED,
                        message=Message(
                            role=Role.AGENT,
                            parts=[Part(text="An internal error occurred")],
                        ),
                    ),
                )
            )
            yield f"data: {error_response.model_dump_json(exclude_none=True)}\n\n"

    return StreamingResponse(
        generate_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
