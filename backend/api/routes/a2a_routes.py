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

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_current_user_optional
from api.routes.a2a_agent_cards import (
    get_editor_agent_card,
    get_executor,  # noqa: F401 — re-exported for backward compat (test patches)
    get_video_agent_card,
)
from api.routes.a2a_message_routes import message_router
from api.routes.a2a_task_routes import task_router
from models.a2a_models import (
    AgentCard,
    AgentSkill,
)
from models.user import User

router = APIRouter(tags=["A2A Protocol"])
logger = logging.getLogger(__name__)

# Include sub-routers
router.include_router(message_router)
router.include_router(task_router)


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
