"""
A2A Protocol Routes
===================

FastAPI routes implementing the Agent-to-Agent (A2A) protocol.
Provides HTTP+JSON/REST binding for A2A operations.

Endpoints:
- GET  /.well-known/agent-card.json - Agent discovery (public)
- POST /a2a/message:send            - Send message (creates/continues task)
- POST /a2a/message:stream          - Send message with SSE streaming
- GET  /a2a/tasks/{id}              - Get task status
- GET  /a2a/tasks                   - List tasks
- POST /a2a/tasks/{id}:cancel       - Cancel task
- POST /a2a/tasks/{id}:subscribe    - Subscribe to task updates (SSE)
- GET  /a2a/extendedAgentCard       - Get extended agent card (authenticated)

Reference: https://a2a-protocol.org/latest/specification/
"""

import json
import logging
import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from api.dependencies import get_current_user_optional
from agent.a2a_executor import (
    A2AAgentExecutor,
    get_editor_a2a_executor,
    get_video_a2a_executor,
)
from models.a2a_models import (
    AgentCard,
    AgentCapabilities,
    AgentInterface,
    AgentProvider,
    AgentSkill,
    CancelTaskRequest,
    GetTaskRequest,
    ListTasksRequest,
    ListTasksResponse,
    Message,
    Part,
    Role,
    SendMessageRequest,
    SendMessageResponse,
    StreamResponse,
    Task,
    TaskNotFoundError,
    TaskState,
    UnsupportedOperationError,
)
from models.user import User

router = APIRouter(tags=["A2A Protocol"])
logger = logging.getLogger(__name__)


# =============================================================================
# Agent Card Definitions
# =============================================================================


def get_base_url() -> str:
    """Get the base URL for the A2A server."""
    return os.getenv("A2A_BASE_URL", os.getenv("API_BASE_URL", "http://localhost:8000"))


def get_video_agent_card() -> AgentCard:
    """Build the AgentCard for the Video Agent."""
    base_url = get_base_url()
    
    return AgentCard(
        name="QPrisma Video Agent",
        description=(
            "An intelligent video analysis agent that helps users explore and understand "
            "video content. Capable of searching through visual content, audio transcriptions, "
            "detected entities, and relationships in videos. Provides timestamped answers "
            "with source citations for easy navigation."
        ),
        supportedInterfaces=[
            AgentInterface(
                url=f"{base_url}/a2a",
                protocolBinding="HTTP+JSON",
                protocolVersion="1.0",
            ),
        ],
        provider=AgentProvider(
            organization="QPrisma",
            url="https://github.com/alexandergg/QPrisma",
        ),
        version="1.0.0",
        documentationUrl="https://github.com/alexandergg/QPrisma/blob/main/API_DOCUMENTATION.md",
        capabilities=AgentCapabilities(
            streaming=True,
            pushNotifications=False,
            extendedAgentCard=True,
        ),
        defaultInputModes=["text/plain", "application/json"],
        defaultOutputModes=["text/plain", "application/json"],
        skills=[
            AgentSkill(
                id="video-search",
                name="Video Content Search",
                description=(
                    "Search through video content including visual scenes, audio transcriptions, "
                    "and detected entities. Uses hybrid search combining vector similarity, "
                    "full-text matching, and knowledge graph traversal."
                ),
                tags=["video", "search", "multimedia", "rag"],
                examples=[
                    "Find where the presenter discusses machine learning",
                    "Show me all scenes with the CEO",
                    "When does the chart appear?",
                    "What topics are covered in this video?",
                ],
            ),
            AgentSkill(
                id="video-qa",
                name="Video Question Answering",
                description=(
                    "Answer questions about video content with timestamped citations. "
                    "Synthesizes information from visual descriptions, speech transcripts, "
                    "and detected entities to provide comprehensive answers."
                ),
                tags=["qa", "video", "analysis", "comprehension"],
                examples=[
                    "What is the main topic of this video?",
                    "Summarize what happens in the first 5 minutes",
                    "Who are the speakers in this video?",
                    "What products are mentioned?",
                ],
            ),
            AgentSkill(
                id="entity-discovery",
                name="Entity Discovery",
                description=(
                    "Find and track entities (people, objects, brands, concepts) "
                    "throughout the video. Shows when and where entities appear."
                ),
                tags=["entities", "tracking", "detection", "ner"],
                examples=[
                    "List all people mentioned in this video",
                    "When does Apple appear in the video?",
                    "Track all mentions of the product name",
                ],
            ),
            AgentSkill(
                id="highlight-discovery",
                name="Highlight Discovery",
                description=(
                    "Find key moments, highlights, and viral-worthy segments in videos. "
                    "Identifies engaging content based on visual, audio, and semantic analysis."
                ),
                tags=["highlights", "clips", "viral", "engagement"],
                examples=[
                    "Find the most engaging moments",
                    "What are the key highlights?",
                    "Show me viral-worthy clips",
                ],
            ),
        ],
        iconUrl=f"{base_url}/static/qprisma-icon.png",
    )


def get_editor_agent_card() -> AgentCard:
    """Build the AgentCard for the Editor Agent."""
    base_url = get_base_url()
    
    return AgentCard(
        name="QPrisma Editor Agent",
        description=(
            "A conversational video editing agent (Chat-to-Edit). Create and modify "
            "video clips through natural language. Supports clip creation, subtitle "
            "styling, reordering, and project management."
        ),
        supportedInterfaces=[
            AgentInterface(
                url=f"{base_url}/a2a/editor",
                protocolBinding="HTTP+JSON",
                protocolVersion="1.0",
            ),
        ],
        provider=AgentProvider(
            organization="QPrisma",
            url="https://github.com/alexandergg/QPrisma",
        ),
        version="1.0.0",
        documentationUrl="https://github.com/alexandergg/QPrisma/blob/main/API_DOCUMENTATION.md",
        capabilities=AgentCapabilities(
            streaming=True,
            pushNotifications=False,
            extendedAgentCard=True,
        ),
        defaultInputModes=["text/plain", "application/json"],
        defaultOutputModes=["text/plain", "application/json"],
        skills=[
            AgentSkill(
                id="clip-creation",
                name="Clip Creation",
                description=(
                    "Create video clips from timestamps or search results. "
                    "Automatically finds relevant segments based on content queries."
                ),
                tags=["clips", "editing", "creation"],
                examples=[
                    "Create a clip from 1:30 to 2:45",
                    "Make a clip of when they discuss pricing",
                    "Extract the intro section as a clip",
                ],
            ),
            AgentSkill(
                id="clip-modification",
                name="Clip Modification",
                description=(
                    "Modify existing clips - change timing, add/remove subtitles, "
                    "update styling, and reorder within the project."
                ),
                tags=["editing", "modification", "subtitles"],
                examples=[
                    "Add subtitles to clip 1",
                    "Change the style of subtitles to bold white",
                    "Extend clip 2 by 5 seconds",
                    "Move clip 3 to the beginning",
                ],
            ),
            AgentSkill(
                id="highlight-clips",
                name="Auto-Generate Highlight Clips",
                description=(
                    "Automatically generate clips from video highlights and "
                    "viral-worthy moments detected in the video."
                ),
                tags=["highlights", "automation", "clips"],
                examples=[
                    "Create clips from the top highlights",
                    "Generate clips for social media",
                    "Make clips from the most engaging moments",
                ],
            ),
            AgentSkill(
                id="project-management",
                name="Project Management",
                description=(
                    "Manage editing projects - list clips, get project status, "
                    "export configurations, and organize content."
                ),
                tags=["project", "management", "export"],
                examples=[
                    "Show me all clips in this project",
                    "What's the total duration of all clips?",
                    "Prepare this project for export",
                ],
            ),
        ],
        iconUrl=f"{base_url}/static/qprisma-editor-icon.png",
    )


# =============================================================================
# Agent Card Discovery Endpoints
# =============================================================================


@router.get("/.well-known/agent-card.json", response_model=AgentCard)
async def get_agent_card():
    """
    Agent Card discovery endpoint.
    
    Returns the public AgentCard for the Video Agent.
    This is the standard well-known URI for A2A agent discovery.
    """
    return get_video_agent_card()


@router.get("/a2a/agent-card.json", response_model=AgentCard)
async def get_video_agent_card_endpoint():
    """Get the Video Agent's agent card."""
    return get_video_agent_card()


@router.get("/a2a/editor/agent-card.json", response_model=AgentCard)
async def get_editor_agent_card_endpoint():
    """Get the Editor Agent's agent card."""
    return get_editor_agent_card()


@router.get("/a2a/extendedAgentCard", response_model=AgentCard)
async def get_extended_agent_card(
    current_user: Annotated[User | None, Depends(get_current_user_optional)] = None,
):
    """
    Get the extended agent card (authenticated).
    
    Returns additional capabilities and skills available to authenticated users.
    """
    if not current_user:
        raise HTTPException(
            status_code=401,
            detail="Authentication required for extended agent card",
        )
    
    card = get_video_agent_card()
    
    # Add additional authenticated-only skills
    card.skills.append(
        AgentSkill(
            id="batch-processing",
            name="Batch Video Processing",
            description="Process multiple videos in batch. Available to authenticated users only.",
            tags=["batch", "processing", "authenticated"],
            examples=[
                "Process all videos in my library",
                "Analyze the last 10 uploaded videos",
            ],
        )
    )
    
    return card


# =============================================================================
# Message Operations
# =============================================================================


def get_executor(agent_type: str = "video") -> A2AAgentExecutor:
    """Get the appropriate A2A executor based on agent type."""
    if agent_type == "editor":
        return get_editor_a2a_executor()
    return get_video_a2a_executor()


@router.post("/a2a/message:send", response_model=SendMessageResponse)
async def send_message(
    request: SendMessageRequest,
    current_user: Annotated[User | None, Depends(get_current_user_optional)] = None,
):
    """
    Send a message to the Video Agent.
    
    Creates a new task or continues an existing one based on taskId/contextId.
    Returns either a Task object or a direct Message response.
    """
    executor = get_executor("video")
    
    # Add user context to metadata
    if current_user and request.message.metadata:
        request.message.metadata["user_id"] = current_user.id
    elif current_user:
        request.message.metadata = {"user_id": current_user.id}
    
    result = await executor.send_message(request)
    
    if isinstance(result, Task):
        return SendMessageResponse(task=result)
    else:
        return SendMessageResponse(message=result)


@router.post("/a2a/editor/message:send", response_model=SendMessageResponse)
async def send_editor_message(
    request: SendMessageRequest,
    current_user: Annotated[User | None, Depends(get_current_user_optional)] = None,
):
    """
    Send a message to the Editor Agent.
    
    Creates a new task or continues an existing one based on taskId/contextId.
    """
    executor = get_executor("editor")
    
    if current_user and request.message.metadata:
        request.message.metadata["user_id"] = current_user.id
    elif current_user:
        request.message.metadata = {"user_id": current_user.id}
    
    result = await executor.send_message(request)
    
    if isinstance(result, Task):
        return SendMessageResponse(task=result)
    else:
        return SendMessageResponse(message=result)


@router.post("/a2a/message:stream")
async def send_streaming_message(
    request: SendMessageRequest,
    current_user: Annotated[User | None, Depends(get_current_user_optional)] = None,
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
    
    if current_user and request.message.metadata:
        request.message.metadata["user_id"] = current_user.id
    elif current_user:
        request.message.metadata = {"user_id": current_user.id}

    async def generate_sse():
        """Generate SSE events from streaming response."""
        try:
            async for response in executor.send_streaming_message(request):
                # Serialize to JSON
                data = response.model_dump_json(exclude_none=True)
                yield f"data: {data}\n\n"
        except Exception as e:
            logger.error(f"SSE streaming error: {e}")
            error_response = StreamResponse(
                statusUpdate=TaskStatusUpdateEvent(
                    taskId="error",
                    contextId="error",
                    status=TaskStatus(
                        state=TaskState.FAILED,
                        message=Message(
                            role=Role.AGENT,
                            parts=[Part(text=f"Streaming error: {str(e)}")],
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


@router.post("/a2a/editor/message:stream")
async def send_editor_streaming_message(
    request: SendMessageRequest,
    current_user: Annotated[User | None, Depends(get_current_user_optional)] = None,
):
    """Send a message to the Editor Agent with streaming response (SSE)."""
    executor = get_executor("editor")
    
    if current_user and request.message.metadata:
        request.message.metadata["user_id"] = current_user.id
    elif current_user:
        request.message.metadata = {"user_id": current_user.id}

    async def generate_sse():
        try:
            async for response in executor.send_streaming_message(request):
                data = response.model_dump_json(exclude_none=True)
                yield f"data: {data}\n\n"
        except Exception as e:
            logger.error(f"Editor SSE streaming error: {e}")
            yield f"data: {{\"error\": \"{str(e)}\"}}\n\n"

    return StreamingResponse(
        generate_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# =============================================================================
# Task Operations
# =============================================================================


@router.get("/a2a/tasks/{task_id}", response_model=Task)
async def get_task(
    task_id: str,
    historyLength: int | None = Query(None, description="Max messages to include in history"),
    current_user: Annotated[User | None, Depends(get_current_user_optional)] = None,
):
    """
    Get the current state of a task.
    
    Returns the task with status, artifacts, and optionally history.
    """
    executor = get_executor("video")
    task = await executor.get_task(task_id, history_length=historyLength)
    
    if not task:
        raise HTTPException(
            status_code=404,
            detail=TaskNotFoundError(
                detail=f"Task with ID '{task_id}' not found",
                taskId=task_id,
            ).model_dump(),
        )
    
    return task


@router.get("/a2a/tasks", response_model=ListTasksResponse)
async def list_tasks(
    contextId: str | None = Query(None, description="Filter by context ID"),
    status: TaskState | None = Query(None, description="Filter by status"),
    pageSize: int = Query(50, ge=1, le=100, description="Max tasks to return"),
    pageToken: str | None = Query(None, description="Pagination token"),
    historyLength: int | None = Query(None, description="Max messages per task history"),
    includeArtifacts: bool = Query(False, description="Include artifacts in response"),
    current_user: Annotated[User | None, Depends(get_current_user_optional)] = None,
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
    )
    
    return ListTasksResponse(
        tasks=tasks,
        nextPageToken="",  # Simplified pagination for now
        pageSize=pageSize,
        totalSize=total,
    )


@router.post("/a2a/tasks/{task_id}:cancel", response_model=Task)
async def cancel_task(
    task_id: str,
    current_user: Annotated[User | None, Depends(get_current_user_optional)] = None,
):
    """
    Cancel an ongoing task.
    
    Returns the updated task with canceled status, or error if not cancellable.
    """
    executor = get_executor("video")
    task = await executor.cancel_task(task_id)
    
    if not task:
        # Check if task exists
        existing = await executor.get_task(task_id)
        if not existing:
            raise HTTPException(
                status_code=404,
                detail=TaskNotFoundError(
                    detail=f"Task with ID '{task_id}' not found",
                    taskId=task_id,
                ).model_dump(),
            )
        else:
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


@router.post("/a2a/tasks/{task_id}:subscribe")
async def subscribe_to_task(
    task_id: str,
    current_user: Annotated[User | None, Depends(get_current_user_optional)] = None,
):
    """
    Subscribe to task updates via SSE.
    
    Returns a stream of TaskStatusUpdateEvent and TaskArtifactUpdateEvent.
    Only works for tasks not in terminal state.
    """
    executor = get_executor("video")
    task = await executor.get_task(task_id)
    
    if not task:
        raise HTTPException(
            status_code=404,
            detail=TaskNotFoundError(
                detail=f"Task with ID '{task_id}' not found",
                taskId=task_id,
            ).model_dump(),
        )
    
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
        # In production, this would use Redis pub/sub or similar
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


# =============================================================================
# Health Check
# =============================================================================


@router.get("/a2a/health")
async def a2a_health():
    """Health check for A2A endpoints."""
    return {
        "status": "healthy",
        "protocol": "A2A",
        "version": "1.0",
        "agents": ["video", "editor"],
    }


# Need to import TaskStatus for the SSE error handler
from models.a2a_models import TaskStatus
