"""
Chat and Search Routes

Handles conversational AI chat and video content search.
Uses VideoRAG-style hybrid search combining vector, fulltext, and graph signals.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_async_openai_client, get_current_user, get_graph_search_service
from core.exceptions import internal_error
from models.api_schemas import (
    ChatRequest,
    ChatResponse,
)
from models.user import User
from services.chat_service import ChatService

router = APIRouter(tags=["Chat & Search"])
logger = logging.getLogger(__name__)


# =============================================================================
# Routes
# =============================================================================


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, current_user: User = Depends(get_current_user)):
    """
    Conversational chat endpoint.

    If media_id is provided, uses RAG to include video context.
    Searches both visual content and audio transcriptions.
    """
    openai_client = get_async_openai_client()
    if not openai_client:
        raise HTTPException(status_code=503, detail="Azure OpenAI not configured")

    try:
        chat_service = ChatService(
            openai_client=openai_client,
            graph_search_service=get_graph_search_service(),
        )
        assistant_message, sources = await chat_service.chat(
            message=request.message,
            media_id=request.media_id,
            chat_history=request.chat_history,
        )
        return ChatResponse(response=assistant_message, sources=sources)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat request failed for media_id={request.media_id}: {e}", exc_info=True)
        raise internal_error() from e


# =============================================================================
# Agentic Chat Endpoint
# =============================================================================


from models.api_schemas import (
    AgentChatRequest,
    AgentChatResponse,
)


@router.post("/chat/agent", response_model=AgentChatResponse)
async def agent_chat(
    request: AgentChatRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Agentic chat endpoint powered by Azure AI Foundry Hosted Agent.

    Routes queries through the Foundry-hosted LangGraph VideoAgentGraph,
    which can search video content, navigate structure, explore the
    knowledge graph, find highlights, and compare moments.

    On first request for a session, the Responses API creates a new
    response.  The returned ``session_id`` carries the response ID so
    subsequent requests pass it as ``previous_response_id`` for
    conversation continuity.

    Response includes:
    - Rich sources with timestamps and thumbnails
    - Navigation actions for UI seeking
    - Suggested follow-up questions
    - Clip suggestions for export
    """
    from services.foundry_agent_client import get_foundry_agent_client

    try:
        user_id = str(current_user.id) if current_user else None

        # On first request session_id is None — send_message will create
        # a new response and return its ID.  On follow-ups the frontend
        # sends back the response ID it received previously, which is
        # passed as previous_response_id for conversation continuity.
        thread_id = request.session_id or None

        client = get_foundry_agent_client()
        result = await client.send_message(
            message=request.message,
            media_id=request.media_id,
            media_ids=request.get_effective_media_ids() or None,
            user_id=user_id,
            session_id=request.session_id,
            thread_id=thread_id,
        )

        # The Foundry response ID becomes the session_id so the
        # frontend can send it back for conversation continuity.
        real_session_id = result.get("thread_id", "")

        return AgentChatResponse(
            response=result.get("content", ""),
            sources=[],
            tool_calls_made=0,
            session_id=real_session_id,
            navigation_actions=[],
            suggested_questions=[],
            clip_suggestions=[],
            entities_mentioned=[],
        )

    except Exception as e:
        logger.error(f"Agent chat failed for media_id={request.media_id}: {e}", exc_info=True)
        raise internal_error() from e
