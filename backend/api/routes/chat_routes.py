"""
Chat and Search Routes

Handles conversational AI chat and video content search.
Uses VideoRAG-style hybrid search combining vector, fulltext, and graph signals.
"""

import logging
import os

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_current_user, get_graph_search_service, get_openai_client
from models.api_schemas import (
    ChatRequest,
    ChatResponse,
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from models.graph_models import NodeType
from models.user import User

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
                    search_response = await search_service.hybrid_search(
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

        completion_params["max_completion_tokens"] = 800

        completion_params["temperature"] = 1

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
        logger.error(f"Search error: {e}")
        raise HTTPException(status_code=500, detail=f"Search error: {str(e)}")


# =============================================================================
# Agentic Chat Endpoint
# =============================================================================


from models.api_schemas import AgentChatRequest, AgentChatResponse, VideoSource, NavigationAction, SuggestedQuestion


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

    from agent import create_redis_checkpointer, get_video_agent_graph

    try:
        # Create agent with Redis checkpointer
        checkpointer = create_redis_checkpointer()
        agent = get_video_agent_graph(checkpointer=checkpointer)

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
        logger.error(f"Agent chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")
