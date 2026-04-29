"""
A2A route security helpers.

Centralizes owner metadata handling so A2A tasks are always persisted with
server-derived user context instead of client-supplied identity claims.
"""

from collections.abc import Iterator
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from api.dependencies import get_media_or_404
from models.a2a_models import SendMessageRequest, Task, TaskNotFoundError
from models.user import User


def _iter_media_ids(metadata: dict) -> Iterator[str]:
    media_id = metadata.get("media_id")
    if isinstance(media_id, str) and media_id:
        yield media_id

    media_ids = metadata.get("media_ids")
    if isinstance(media_ids, str) and media_ids:
        yield media_ids
    elif isinstance(media_ids, list):
        for item in media_ids:
            if isinstance(item, str) and item:
                yield item


def sanitize_message_request(body: SendMessageRequest, current_user: User) -> None:
    """
    Validate user-owned media references and persist trusted owner metadata.

    Mutates the request body because FastAPI has already parsed the payload and
    the executor expects the same object instance.
    """
    message_metadata = dict(body.message.metadata or {})

    for media_id in set(_iter_media_ids(message_metadata)):
        get_media_or_404(media_id, current_user)

    message_metadata["user_id"] = current_user.id
    body.message.metadata = message_metadata

    request_metadata = dict(body.metadata or {})
    request_metadata["user_id"] = current_user.id

    for key in ("media_id", "media_ids"):
        request_metadata.pop(key, None)
        if key in message_metadata:
            request_metadata[key] = message_metadata[key]

    body.metadata = request_metadata


def _is_client_generated_context_id(context_id: str) -> bool:
    try:
        UUID(context_id)
        return True
    except (TypeError, ValueError):
        return False


async def authorize_message_continuation(
    executor: Any,
    body: SendMessageRequest,
    current_user: User,
) -> None:
    """
    Verify task/conversation continuation identifiers before dispatch.

    New client-generated UUID context IDs are allowed because the executor will
    create a fresh Foundry conversation for them. Existing task IDs and Foundry
    conversation IDs must already belong to the current user.
    """
    task_id = body.message.taskId
    if task_id:
        task = await executor.get_task(task_id)
        if not task or not task_belongs_to_user(task, current_user):
            raise task_not_found(task_id)

    context_id = body.message.contextId
    if not context_id or _is_client_generated_context_id(context_id):
        return

    tasks, total = await executor.list_tasks(
        context_id=context_id,
        page_size=1,
        user_id=None if current_user.is_superuser else current_user.id,
    )
    if total < 1 or not any(task_belongs_to_user(task, current_user) for task in tasks):
        raise task_not_found(context_id)


def task_belongs_to_user(task: Task, current_user: User) -> bool:
    """Return whether the authenticated user may access the task."""
    if current_user.is_superuser:
        return True
    return (task.metadata or {}).get("user_id") == current_user.id


def task_not_found(task_id: str) -> HTTPException:
    """Return a 404 that does not reveal whether a task exists for another user."""
    return HTTPException(
        status_code=404,
        detail=TaskNotFoundError(
            detail=f"Task with ID '{task_id}' not found",
            taskId=task_id,
        ).model_dump(mode="json"),
    )
