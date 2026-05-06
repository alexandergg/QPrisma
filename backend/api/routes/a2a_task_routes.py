"""
A2A Task Routes
===============

Task management endpoints: get, list, cancel, subscribe.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse

from api.dependencies import get_current_user
from api.rate_limit import limiter
from api.routes.a2a_agent_cards import get_executor
from api.routes.a2a_security import task_belongs_to_user, task_not_found
from models.a2a_models import (
    ListTasksResponse,
    StreamResponse,
    Task,
    TaskState,
    TaskStatusUpdateEvent,
    UnsupportedOperationError,
)
from models.user import User

task_router = APIRouter(tags=["A2A Protocol"])
logger = logging.getLogger(__name__)


@task_router.get("/a2a/tasks/{task_id}", response_model=Task)
@limiter.limit("120/minute")
async def get_task(
    request: Request,
    task_id: str,
    response: Response,
    current_user: Annotated[User, Depends(get_current_user)],
    historyLength: int | None = Query(None, description="Max messages to include in history"),
):
    """
    Get the current state of a task.

    Returns the task with status, artifacts, and optionally history.
    """
    executor = get_executor("video")
    task = await executor.get_task(task_id, history_length=historyLength)

    if not task:
        raise task_not_found(task_id)

    if not task_belongs_to_user(task, current_user):
        raise task_not_found(task_id)

    return task


@task_router.get("/a2a/tasks", response_model=ListTasksResponse)
@limiter.limit("60/minute")
async def list_tasks(
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_current_user)],
    contextId: str | None = Query(None, description="Filter by context ID"),
    status: TaskState | None = Query(None, description="Filter by status"),
    pageSize: int = Query(50, ge=1, le=100, description="Max tasks to return"),
    pageToken: str | None = Query(None, description="Pagination token"),
    historyLength: int | None = Query(None, description="Max messages per task history"),
    includeArtifacts: bool = Query(False, description="Include artifacts in response"),
):
    """
    List tasks with optional filtering and pagination.

    Returns tasks sorted by last update time (most recent first).
    """
    executor = get_executor("video")

    tasks, total = await executor.list_tasks(
        context_id=contextId,
        status=status,
        page_size=pageSize,
        include_artifacts=includeArtifacts,
        user_id=None if current_user.is_superuser else current_user.id,
    )

    return ListTasksResponse(
        tasks=tasks,
        nextPageToken="",  # Simplified pagination for now
        pageSize=pageSize,
        totalSize=total,
    )


@task_router.post("/a2a/tasks/{task_id}:cancel", response_model=Task)
@limiter.limit("30/minute")
async def cancel_task(
    request: Request,
    task_id: str,
    response: Response,
    current_user: Annotated[User, Depends(get_current_user)],
):
    """
    Cancel an ongoing task.

    Returns the updated task with canceled status, or error if not cancellable.
    """
    executor = get_executor("video")
    existing = await executor.get_task(task_id)
    if not existing or not task_belongs_to_user(existing, current_user):
        raise task_not_found(task_id)

    task = await executor.cancel_task(task_id)

    if not task:
        raise HTTPException(
            status_code=409,
            detail={
                "type": "https://a2a-protocol.org/errors/task-not-cancelable",
                "title": "Task Not Cancelable",
                "status": 409,
                "detail": f"Task '{task_id}' is not in a cancelable state",
                "taskId": task_id,
            },
        )

    return task


@task_router.post("/a2a/tasks/{task_id}:subscribe")
@limiter.limit("60/minute")
async def subscribe_to_task(
    request: Request,
    task_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
):
    """
    Subscribe to task updates via SSE.

    Returns a stream of TaskStatusUpdateEvent and TaskArtifactUpdateEvent.
    Only works for tasks not in terminal state.
    """
    executor = get_executor("video")
    task = await executor.get_task(task_id)

    if not task:
        raise task_not_found(task_id)

    if not task_belongs_to_user(task, current_user):
        raise task_not_found(task_id)

    # Check if task is in terminal state
    terminal_states = {
        TaskState.COMPLETED,
        TaskState.FAILED,
        TaskState.CANCELED,
        TaskState.REJECTED,
    }

    if task.status.state in terminal_states:
        raise HTTPException(
            status_code=400,
            detail=UnsupportedOperationError(
                detail=f"Cannot subscribe to task '{task_id}' - already in terminal state: {task.status.state}",
                taskId=task_id,
            ).model_dump(),
        )

    async def generate_updates():
        """Generate SSE updates for the task."""
        # First, yield current task state
        response = StreamResponse(task=task)
        yield f"data: {response.model_dump_json(exclude_none=True)}\n\n"

        # For now, we don't have a real subscription mechanism
        # In production, this would use a durable event stream or similar
        # This is a placeholder that returns the final state
        current = await executor.get_task(task_id)
        if current and current.status.state != task.status.state:
            response = StreamResponse(
                statusUpdate=TaskStatusUpdateEvent(
                    taskId=current.id,
                    contextId=current.contextId,
                    status=current.status,
                )
            )
            yield f"data: {response.model_dump_json(exclude_none=True)}\n\n"

    return StreamingResponse(
        generate_updates(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
