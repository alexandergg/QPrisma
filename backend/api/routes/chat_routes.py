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
        video_summary = ""
        video_topics = []

        if request.media_id:
            logger.info(f"Chat search: query='{request.message}', media_id={request.media_id}")
            
            # First, load video summary and topics from Neo4j
            try:
                search_service = get_graph_search_service()
                if not search_service.graph_service.is_connected:
                    search_service.graph_service.connect()
                
                if search_service.graph_service.is_connected:
                    with search_service.graph_service.get_session() as session:
                        result = session.run(
                            """
                            MATCH (v:Video)
                            WHERE v.video_id = $media_id OR v.id = $media_id
                            RETURN v.summary as summary, v.topics as topics
                            """,
                            media_id=request.media_id
                        )
                        record = result.single()
                        if record:
                            video_summary = record.get("summary") or ""
                            video_topics = record.get("topics") or []
                            if video_summary:
                                logger.info(f"Loaded video summary ({len(video_summary)} chars) and {len(video_topics)} topics from Neo4j")
            except Exception as e:
                logger.warning(f"Could not load video summary from Neo4j: {e}")
            
            try:
                # Use VideoRAG-style hybrid search
                search_service = get_graph_search_service()
                
                if not search_service.graph_service.is_connected:
                    search_service.graph_service.connect()
                
                if not search_service.graph_service.is_connected:
                    logger.warning("Neo4j not connected - cannot search video context")
                else:
                    # Hybrid search: vector + fulltext + graph + temporal
                    # Use more results for comprehensive context
                    search_response = search_service.hybrid_search(
                        query_text=request.message,
                        node_types=[NodeType.FRAME, NodeType.AUDIO_SEGMENT, NodeType.ENTITY],
                        video_id=request.media_id,
                        limit=20,
                        expansion_hops=2,
                        use_reranking=True,
                    )

                    logger.info(
                        f"Hybrid search: {search_response.total_results} results, "
                        f"vector_time={search_response.vector_search_time_ms:.0f}ms"
                    )

                    # Build structured context from results
                    visual_context = []
                    audio_context = []
                    entity_context = []

                    for result in search_response.results:
                        ts = result.content.get("timestamp")

                        if result.node_type == NodeType.FRAME:
                            desc = result.content.get("description", "")
                            if ts is not None and desc:
                                visual_context.append(f"[{ts:.1f}s] {desc[:400]}")
                                sources.append({
                                    "timestamp": float(ts),
                                    "type": "visual",
                                    "description": desc[:200],
                                    "score": result.combined_score,
                                })
                        elif result.node_type == NodeType.AUDIO_SEGMENT:
                            text = result.content.get("text", "")
                            if ts is not None and text:
                                audio_context.append(f"[{ts:.1f}s] \"{text[:300]}\"")
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
                                entity_context.append(f"{entity_type}: {name}")
                                sources.append({
                                    "timestamp": ts or 0,
                                    "type": "entity",
                                    "description": f"{entity_type}: {name}",
                                    "score": result.combined_score,
                                })

                    # Build structured context string - START WITH VIDEO SUMMARY
                    if video_summary:
                        context += "**VIDEO SUMMARY:**\n"
                        context += video_summary + "\n"
                        if video_topics:
                            context += f"\n**KEY TOPICS:** {', '.join(video_topics)}\n"

                    if visual_context:
                        context += "\n\n**VISUAL CONTENT (what's shown in the video):**\n"
                        context += "\n".join(visual_context[:10])

                    if audio_context:
                        context += "\n\n**AUDIO/SPEECH (what's said in the video):**\n"
                        context += "\n".join(audio_context[:10])

                    if entity_context:
                        context += "\n\n**ENTITIES DETECTED:**\n"
                        context += ", ".join(set(entity_context[:15]))

                    # Sort sources by timestamp
                    sources.sort(key=lambda x: x.get("timestamp", 0))

            except Exception as e:
                logger.warning(f"Error getting video context from Neo4j: {e}")

        # Prepare messages with enhanced system prompt
        system_prompt = """You are QPrisma, an AI assistant specialized in analyzing and explaining video content.

Your role is to help users understand what happens in their videos by using the context provided from video analysis.

## How to respond:
1. **Always cite timestamps** - Reference specific moments like [0:45] or [2:30] so users can navigate to them
2. **Start with the big picture** - Use the VIDEO SUMMARY to understand the overall content before diving into details
3. **Synthesize information** - Combine visual descriptions with audio/speech content for complete answers
4. **Be specific** - Use details from the context rather than generic descriptions
5. **Acknowledge limitations** - If the context doesn't contain relevant information, say so clearly
6. **Structure longer answers** - Use bullet points or sections for complex responses

## Context interpretation:
- **VIDEO SUMMARY** = High-level overview of what the entire video is about
- **KEY TOPICS** = Main subjects covered in the video
- **VISUAL CONTENT** = What is shown/seen in the video at each timestamp
- **AUDIO/SPEECH** = What is said/spoken in the video (transcript)
- **ENTITIES** = People, objects, brands, or concepts detected

When the user asks about the video, base your answer on the provided context. Use the VIDEO SUMMARY to give context for your answers. If you need to make inferences, make it clear you're interpreting the available information."""

        messages = [{"role": "system", "content": system_prompt}]

        # Add chat history if exists
        if request.chat_history:
            for msg in request.chat_history:
                messages.append(
                    {"role": msg.get("role", "user"), "content": msg.get("content", "")}
                )

        # Add current message with structured context
        if context:
            user_message = f"""User question: {request.message}

---
**RELEVANT VIDEO CONTEXT:**
{context}
---

Please answer the user's question based on the video context above."""
        else:
            user_message = request.message

        messages.append({"role": "user", "content": user_message})

        # Call Azure OpenAI
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_GPT", "gpt-4o")

        completion_params = {"model": deployment, "messages": messages}

        if "gpt-5" in deployment.lower():
            completion_params["max_completion_tokens"] = 800
        else:
            completion_params["temperature"] = 0.7
            completion_params["max_tokens"] = 800

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
