"""
Chat and Search Routes

Handles conversational AI chat and video content search.
Uses VideoRAG-style hybrid search combining vector, fulltext, and graph signals.
"""

import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import get_current_user, get_graph_search_service, get_openai_client
from models.graph_models import NodeType
from models.user import User

router = APIRouter(tags=["Chat & Search"])
logger = logging.getLogger(__name__)


# =============================================================================
# Request/Response Models
# =============================================================================


class ChatMessage(BaseModel):
    """A single chat message."""

    role: str = Field(..., pattern="^(user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    """Chat request with optional video context."""

    message: str
    media_id: str | None = None
    chat_history: list[dict] | None = None


class ChatResponse(BaseModel):
    """Chat response with sources."""

    response: str
    sources: list[dict] = Field(default_factory=list)


class SearchRequest(BaseModel):
    """Video content search request."""

    query: str
    media_id: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class SearchResult(BaseModel):
    """A single search result."""

    timestamp: float
    content: str
    score: float
    type: str = "visual"  # visual or audio


class SearchResponse(BaseModel):
    """Search response with results."""

    query: str
    results: list[SearchResult]
    total: int


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
    openai_client = get_openai_client()
    if not openai_client:
        raise HTTPException(status_code=503, detail="Azure OpenAI not configured")

    try:
        # Build context from video if media_id provided
        context = ""
        sources = []

        if request.media_id:
            logger.info(f"Chat search: query='{request.message}', media_id={request.media_id}")
            try:
                # Use VideoRAG-style hybrid search
                search_service = get_graph_search_service()

                # Ensure Neo4j connection
                if not search_service.graph_service.is_connected:
                    search_service.graph_service.connect()

                if not search_service.graph_service.is_connected:
                    logger.warning("Neo4j not connected - cannot search video context")
                else:
                    # Hybrid search: vector + fulltext + graph + temporal
                    search_response = search_service.hybrid_search(
                        query_text=request.message,
                        node_types=[NodeType.FRAME, NodeType.AUDIO_SEGMENT, NodeType.ENTITY],
                        video_id=request.media_id,
                        limit=10,
                        expansion_hops=1,
                        use_reranking=True,
                    )

                    logger.info(
                        f"Hybrid search: {search_response.total_results} results, "
                        f"vector_time={search_response.vector_search_time_ms:.0f}ms"
                    )

                    # Build context from results
                    for result in search_response.results:
                        ts = result.content.get("timestamp")

                        if result.node_type == NodeType.FRAME:
                            desc = result.content.get("description", "")
                            if ts is not None and desc:
                                context += f"- [@ {ts:.1f}s - visual]: {desc[:300]}\n"
                                sources.append({
                                    "timestamp": float(ts),
                                    "type": "visual",
                                    "description": desc[:200],
                                    "score": result.combined_score,
                                })
                        elif result.node_type == NodeType.AUDIO_SEGMENT:
                            text = result.content.get("text", "")
                            if ts is not None and text:
                                context += f'- [@ {ts:.1f}s - audio]: "{text[:300]}"\n'
                                sources.append({
                                    "timestamp": float(ts),
                                    "type": "audio",
                                    "description": text[:200],
                                    "score": result.combined_score,
                                })
                        elif result.node_type == NodeType.ENTITY:
                            name = result.content.get("name", "")
                            entity_type = result.content.get("type", "entity")
                            if name:
                                context += f"- [entity - {entity_type}]: {name}\n"
                                sources.append({
                                    "timestamp": ts or 0,
                                    "type": "entity",
                                    "description": f"{entity_type}: {name}",
                                    "score": result.combined_score,
                                })

                    # Sort sources by timestamp
                    sources.sort(key=lambda x: x.get("timestamp", 0))

            except Exception as e:
                logger.warning(f"Error getting video context from Neo4j: {e}")

        # Prepare messages with system prompt
        system_prompt = """You are an AI assistant helping users understand and navigate video content.
When answering questions about the video:
- Reference specific timestamps when discussing content
- Be concise but informative
- If the context doesn't contain relevant information, say so
- Help users find specific moments they're looking for
- Summarize content clearly when asked about what happens"""

        messages = [{"role": "system", "content": system_prompt}]

        # Add chat history if exists
        if request.chat_history:
            for msg in request.chat_history:
                messages.append(
                    {"role": msg.get("role", "user"), "content": msg.get("content", "")}
                )

        # Add current message with context
        user_message = request.message
        if context:
            user_message += context

        messages.append({"role": "user", "content": user_message})

        # Call Azure OpenAI
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_GPT", "gpt-4o")

        completion_params = {"model": deployment, "messages": messages}

        if "gpt-5" in deployment.lower():
            completion_params["max_completion_tokens"] = 500
        else:
            completion_params["temperature"] = 0.7
            completion_params["max_tokens"] = 500

        response = openai_client.chat.completions.create(**completion_params)
        assistant_message = response.choices[0].message.content

        return ChatResponse(response=assistant_message, sources=sources)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")


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
        search_response = search_service.hybrid_search(
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
        logger.error(f"Search error: {e}")
        raise HTTPException(status_code=500, detail=f"Search error: {str(e)}")


# =============================================================================
# Agentic Chat Endpoint
# =============================================================================


class AgentChatRequest(BaseModel):
    """Request for agentic chat with tool calling."""

    message: str
    media_id: str | None = None
    chat_history: list[dict] | None = None
    session_id: str | None = None


class AgentChatResponse(BaseModel):
    """Response from agentic chat."""

    response: str
    sources: list[dict] = Field(default_factory=list)
    tool_calls_made: int = 0
    session_id: str | None = None


@router.post("/chat/agent", response_model=AgentChatResponse)
async def agent_chat(
    request: AgentChatRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Agentic chat endpoint with intelligent tool calling.

    This endpoint uses a ReAct-style agent that can:
    - Search video content semantically
    - Get transcripts and scene descriptions
    - Navigate video structure (chapters, scenes)
    - Explore the knowledge graph for relationships
    - Make multiple tool calls to gather comprehensive information

    The agent automatically decides which tools to use based on the user's question.
    """
    from agent.video_agent import get_video_agent
    from agent.memory import get_agent_memory
    import uuid

    try:
        agent = get_video_agent()

        # Handle session
        session_id = request.session_id
        memory = None
        chat_history = request.chat_history

        if session_id:
            # Load existing session
            memory = get_agent_memory()
            session = memory.get_session(session_id)

            if session:
                # Get history from memory if not provided
                if not chat_history:
                    stored_messages = memory.get_messages(session_id, limit=20)
                    chat_history = [
                        {"role": m["role"], "content": m["content"]}
                        for m in stored_messages
                        if m["role"] in ("user", "assistant") and m.get("content")
                    ]

                # Update session with current media_id if provided
                if request.media_id:
                    memory.update_session(session_id, media_id=request.media_id)
            else:
                # Create new session
                memory.create_session(
                    session_id=session_id,
                    user_id=str(current_user.id) if current_user else None,
                    media_id=request.media_id,
                )
        else:
            # Generate new session ID
            session_id = str(uuid.uuid4())
            memory = get_agent_memory()
            memory.create_session(
                session_id=session_id,
                user_id=str(current_user.id) if current_user else None,
                media_id=request.media_id,
            )

        # Run the agent
        result = await agent.run(
            message=request.message,
            media_id=request.media_id,
            chat_history=chat_history,
            user_id=str(current_user.id) if current_user else None,
            session_id=session_id,
        )

        # Save messages to memory
        if memory:
            memory.add_message(session_id, "user", request.message)
            memory.add_message(session_id, "assistant", result["response"])

        return AgentChatResponse(
            response=result["response"],
            sources=result.get("sources", []),
            tool_calls_made=result.get("tool_calls_made", 0),
            session_id=session_id,
        )

    except Exception as e:
        logger.error(f"Agent chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")


@router.post("/chat/agent/stream")
async def agent_chat_stream(
    request: AgentChatRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Streaming agentic chat endpoint using Server-Sent Events (SSE).

    Events emitted:
    - thinking: Agent is processing (with iteration number)
    - tool_start: Starting a tool call (with tool name)
    - tool_end: Tool call completed (with success status)
    - token: Streaming response token
    - sources: Sources found during search
    - done: Final response complete
    - error: Error occurred

    Use with EventSource or fetch with ReadableStream on the client.
    """
    from fastapi.responses import StreamingResponse
    from agent.video_agent import get_video_agent
    from agent.memory import get_agent_memory
    import uuid

    async def event_generator():
        try:
            agent = get_video_agent()

            # Handle session
            session_id = request.session_id or str(uuid.uuid4())
            memory = get_agent_memory()
            chat_history = request.chat_history

            # Load or create session
            session = memory.get_session(session_id)
            if session:
                if not chat_history:
                    stored_messages = memory.get_messages(session_id, limit=20)
                    chat_history = [
                        {"role": m["role"], "content": m["content"]}
                        for m in stored_messages
                        if m["role"] in ("user", "assistant") and m.get("content")
                    ]
                if request.media_id:
                    memory.update_session(session_id, media_id=request.media_id)
            else:
                memory.create_session(
                    session_id=session_id,
                    user_id=str(current_user.id) if current_user else None,
                    media_id=request.media_id,
                )

            # Emit session ID first
            import json
            yield f"data: {json.dumps({'event': 'session', 'data': {'session_id': session_id}})}\n\n"

            # Save user message
            memory.add_message(session_id, "user", request.message)

            # Stream agent responses
            final_response = ""
            async for event in agent.run_stream(
                message=request.message,
                media_id=request.media_id,
                chat_history=chat_history,
                user_id=str(current_user.id) if current_user else None,
                session_id=session_id,
            ):
                yield f"data: {json.dumps(event)}\n\n"

                # Capture final response for memory
                if event.get("event") == "done":
                    final_response = event.get("data", {}).get("response", "")

            # Save assistant message
            if final_response:
                memory.add_message(session_id, "assistant", final_response)

        except Exception as e:
            logger.error(f"Agent stream error: {e}", exc_info=True)
            import json
            yield f"data: {json.dumps({'event': 'error', 'data': {'error': str(e)}})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
