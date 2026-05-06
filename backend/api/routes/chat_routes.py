"""Chat routes backed by VideoRAG-style context retrieval."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_async_openai_client, get_current_user, get_graph_search_service
from core.exceptions import internal_error
from core.legacy_usage import record_legacy_usage
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


@router.post("/chat", response_model=ChatResponse, deprecated=True)
async def chat(request: ChatRequest, current_user: User = Depends(get_current_user)):
    """
    Classic RAG chat compatibility endpoint.

    The canonical hosted-agent chat API is A2A (`/a2a/message:stream`).
    This endpoint remains for clients that still need direct VideoRAG responses.
    """
    openai_client = get_async_openai_client()
    if not openai_client:
        raise HTTPException(status_code=503, detail="Azure OpenAI not configured")

    record_legacy_usage(
        logger,
        feature="classic_chat_endpoint",
        labels={"media_context": bool(request.media_id)},
    )

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
