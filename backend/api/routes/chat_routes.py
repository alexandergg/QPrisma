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
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from models.graph_models import NodeType
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


@router.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest, current_user: User = Depends(get_current_user)):
    """
    Search video content using VideoRAG-style hybrid search.

    Combines vector similarity, fulltext matching, graph proximity, and temporal relevance.
    Searches visual descriptions, audio transcriptions, and entities.
    """
    try:
        search_service = get_graph_search_service()

        # Ensure Neo4j connection
        if not search_service.graph_service.is_connected:
            search_service.graph_service.connect()

        # Hybrid search
        search_response = await search_service.hybrid_search(
            query_text=request.query,
            node_types=[NodeType.FRAME, NodeType.AUDIO_SEGMENT, NodeType.ENTITY],
            video_id=request.media_id,
            limit=request.limit,
            expansion_hops=1,
            use_reranking=True,
        )

        # Format results
        results = []
        for r in search_response.results:
            ts = r.content.get("timestamp", 0)

            if r.node_type == NodeType.FRAME:
                content = r.content.get("description", "")[:500]
                result_type = "visual"
            elif r.node_type == NodeType.AUDIO_SEGMENT:
                content = r.content.get("text", "")[:500]
                result_type = "audio"
            elif r.node_type == NodeType.ENTITY:
                name = r.content.get("name", "")
                entity_type = r.content.get("type", "entity")
                content = f"{entity_type}: {name}"
                result_type = "entity"
            else:
                content = str(r.content)[:500]
                result_type = "other"

            results.append(
                SearchResult(
                    timestamp=ts or 0,
                    content=content,
                    score=r.combined_score,
                    type=result_type,
                )
            )

        # Sort by score (already sorted by hybrid_search)
        return SearchResponse(
            query=request.query,
            results=results,
            total=search_response.total_results,
        )

    except Exception as e:
        logger.error(f"Hybrid search failed for query={request.query!r}: {e}", exc_info=True)
        raise internal_error() from e


# =============================================================================
# Agentic Chat Endpoint
# =============================================================================


from models.api_schemas import (
    AgentChatRequest,
    AgentChatResponse,
    NavigationAction,
    SuggestedQuestion,
    VideoSource,
)


@router.post("/chat/agent", response_model=AgentChatResponse)
async def agent_chat(
    request: AgentChatRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Agentic chat endpoint with intelligent tool calling (LangGraph).

    This endpoint uses a LangGraph StateGraph agent that can:
    - Search video content semantically
    - Get transcripts and scene descriptions
    - Navigate video structure (chapters, scenes)
    - Explore the knowledge graph for relationships
    - Make multiple tool calls to gather comprehensive information
    - Find highlights and suggest clips
    - Compare moments and track entities

    The agent automatically decides which tools to use based on the user's question.
    Uses Redis checkpointing for conversation persistence.

    Response includes:
    - Rich sources with timestamps and thumbnails
    - Navigation actions for UI seeking
    - Suggested follow-up questions
    - Clip suggestions for export
    """
    import uuid

    from agent import get_video_agent_graph

    try:
        # Get singleton agent (async — initializes checkpointer on first call)
        agent = await get_video_agent_graph()

        # Generate session ID if not provided
        session_id = request.session_id or str(uuid.uuid4())

        # Run the agent (LangGraph handles session via thread_id)
        result = await agent.run(
            message=request.message,
            media_id=request.media_id,
            media_ids=request.get_effective_media_ids() or None,
            chat_history=request.chat_history,
            user_id=str(current_user.id) if current_user else None,
            session_id=session_id,
        )

        # Build structured response with all metadata
        sources = [
            VideoSource(
                timestamp=s.get("timestamp", 0),
                timestamp_formatted=s.get("timestamp_formatted", ""),
                type=s.get("type", "unknown"),
                description=s.get("description", ""),
                score=s.get("score", 0),
                thumbnail_url=s.get("thumbnail_url"),
                frame_id=s.get("frame_id"),
            )
            for s in result.get("sources", [])
        ]

        navigation_actions = [
            NavigationAction(
                action=n.get("action", "jump_to"),
                label=n.get("label", ""),
                timestamp=n.get("timestamp"),
                end_timestamp=n.get("end_timestamp"),
                parameters=n.get("parameters"),
            )
            for n in result.get("navigation_actions", [])
        ]

        suggested_questions = [
            SuggestedQuestion(
                question=q.get("question", ""),
                category=q.get("category", "related"),
            )
            for q in result.get("suggested_questions", [])
        ]

        clip_suggestions = [
            NavigationAction(
                action=c.get("action", "create_clip"),
                label=c.get("label", ""),
                timestamp=c.get("timestamp"),
                end_timestamp=c.get("end_timestamp"),
                parameters=c.get("parameters"),
            )
            for c in result.get("clip_suggestions", [])
        ]

        return AgentChatResponse(
            response=result["response"],
            sources=sources,
            tool_calls_made=result.get("tool_calls_made", 0),
            session_id=session_id,
            navigation_actions=navigation_actions,
            suggested_questions=suggested_questions,
            clip_suggestions=clip_suggestions,
            entities_mentioned=result.get("entities_mentioned", []),
        )

    except Exception as e:
        logger.error(f"Agent chat failed for media_id={request.media_id}: {e}", exc_info=True)
        raise internal_error() from e
