"""Chat routes backed by VideoRAG-style context retrieval."""

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
