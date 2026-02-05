"""
LangGraph Video Agent
=====================

Video agent implemented using LangGraph StateGraph pattern.
Provides a declarative, composable agent with built-in streaming and checkpointing.

Architecture:
    START → call_model → tools_condition? → tools → update_context → call_model → ... → END
                              ↓ no                          ↑ error_handler (graceful degradation)
                             END

Features:
- Input/Output schema separation (hides internal state from API)
- Automatic context tracking for conversation memory
- Error handler node for graceful degradation
- Tool call counting for iteration management
- Enhanced prompts for detailed responses
- Graph relationship exploration
- Per-exception retry policies
- Multi-tenant security via user_id scoping

Best Practices Applied (LangGraph v1.0+):
- Uses prebuilt tools_condition for routing
- Uses ToolNode with handle_tool_errors for graceful error handling
- Uses START constant for modern entry point
- Input/Output schema separation
- Error handler node for graceful degradation
- Per-exception retry policies
- Supports graph visualization with get_graph()
"""

import json
import logging
import os
import traceback
from collections.abc import AsyncGenerator
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy
from langgraph.prebuilt import ToolNode

from agent.nodes.video_nodes import call_model, should_continue, update_context
from agent.nodes.base import error_handler_node
from agent.state.agent_state import (
    AgentState,
    AgentInputState,
    AgentOutputState,
    create_agent_state,
    should_retry_exception,
)
from agent.tools import SEARCH_TOOLS
from agent.utils.formatting import format_timestamp

logger = logging.getLogger(__name__)


# =============================================================================
# Metadata Extraction Helper
# =============================================================================


def extract_metadata_from_tool_result(
    tool_result: dict,
) -> dict[str, list]:
    """
    Extract structured metadata (sources, navigation, clips, entities)
    from a single tool result dict.

    Returns dict with keys: sources, navigation_actions, clip_suggestions, entities.
    """
    sources = []
    navigation_actions = []
    clip_suggestions = []
    entities = []

    # Extract sources from search results
    for r in tool_result.get("results", []):
        if isinstance(r, dict) and "timestamp" in r:
            sources.append({
                "timestamp": r.get("timestamp", 0),
                "timestamp_formatted": r.get("timestamp_formatted", ""),
                "type": r.get("type", "unknown"),
                "description": r.get("content", r.get("description", ""))[:150],
                "score": r.get("score", 0),
            })
            navigation_actions.append({
                "action": "jump_to",
                "label": f"Go to {r.get('timestamp_formatted', '')}",
                "timestamp": r.get("timestamp", 0),
            })

    # Extract from occurrences (find_entity)
    for occ in tool_result.get("occurrences", []):
        if isinstance(occ, dict) and "timestamp" in occ:
            sources.append({
                "timestamp": occ.get("timestamp", 0),
                "timestamp_formatted": occ.get("timestamp_formatted", ""),
                "type": occ.get("occurrence_type", "entity"),
                "description": occ.get("context", "")[:150],
                "score": occ.get("confidence", 0),
            })

    # Extract clip suggestions from highlights
    for h in tool_result.get("highlights", []):
        clip_suggestions.append({
            "action": "create_clip",
            "label": h.get("title", "Highlight"),
            "timestamp": h.get("start_time", 0),
            "end_timestamp": h.get("end_time", 0),
            "parameters": {
                "description": h.get("description", ""),
                "reason": h.get("highlight_reason", ""),
            },
        })

    # Extract from timeline
    for t in tool_result.get("timeline", [])[:10]:
        if isinstance(t, dict) and "timestamp" in t:
            sources.append({
                "timestamp": t.get("timestamp", 0),
                "timestamp_formatted": t.get("timestamp_formatted", ""),
                "type": t.get("appearance_type", "timeline"),
                "description": t.get("context", "")[:150] if t.get("context") else "",
                "score": 0,
            })

    # Extract from moments (compare_moments output)
    for m in tool_result.get("moments", []):
        if isinstance(m, dict) and "timestamp" in m:
            ts = m.get("timestamp", 0)
            ts_fmt = m.get("timestamp_formatted", format_timestamp(ts))
            desc = ""
            if "visual" in m and m["visual"].get("description"):
                desc = m["visual"]["description"][:150]
            sources.append({
                "timestamp": ts,
                "timestamp_formatted": ts_fmt,
                "type": "comparison",
                "description": desc,
                "score": 0,
            })
            navigation_actions.append({
                "action": "jump_to",
                "label": f"Go to {ts_fmt}",
                "timestamp": ts,
            })

    # Extract entities
    for e in tool_result.get("related_entities", []):
        entities.append({
            "name": e.get("name"),
            "type": e.get("type"),
            "relevance": e.get("relevance", 0),
        })

    return {
        "sources": sources,
        "navigation_actions": navigation_actions,
        "clip_suggestions": clip_suggestions,
        "entities": entities,
    }


def extract_metadata_from_messages(
    messages: list,
) -> dict[str, Any]:
    """
    Extract all metadata from a list of messages (typically from graph result).

    Returns dict with: tool_calls, sources, navigation_actions, clip_suggestions, entities.
    """
    tool_calls = 0
    sources = []
    navigation_actions = []
    clip_suggestions = []
    entities_mentioned = []

    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            tool_calls += len(msg.tool_calls)

        if isinstance(msg, ToolMessage):
            try:
                tool_result = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
                if isinstance(tool_result, dict):
                    meta = extract_metadata_from_tool_result(tool_result)
                    sources.extend(meta["sources"])
                    navigation_actions.extend(meta["navigation_actions"])
                    clip_suggestions.extend(meta["clip_suggestions"])
                    entities_mentioned.extend(meta["entities"])
            except (json.JSONDecodeError, TypeError):
                pass

    return {
        "tool_calls": tool_calls,
        "sources": sources,
        "navigation_actions": navigation_actions,
        "clip_suggestions": clip_suggestions,
        "entities_mentioned": entities_mentioned,
    }


def _generate_suggestions(query: str, sources: list, entities: list) -> list[dict]:
    """Generate suggested follow-up questions based on context."""
    suggestions = []
    query_lower = query.lower()

    # If we found timestamps, suggest exploring them
    if sources:
        first_source = sources[0]
        ts_fmt = first_source.get("timestamp_formatted", "")
        if ts_fmt:
            suggestions.append({
                "question": f"What happens right after {ts_fmt}?",
                "category": "deeper",
            })

    # If entities were found, suggest exploring them
    if entities:
        entity = entities[0]
        suggestions.append({
            "question": f"Show me the complete timeline of {entity.get('name', 'this entity')}",
            "category": "related",
        })

    # General suggestions based on query type
    if "what" in query_lower and "about" in query_lower:
        suggestions.append({
            "question": "What are the key highlights I can use for clips?",
            "category": "related",
        })
    elif "when" in query_lower or "where" in query_lower:
        suggestions.append({
            "question": "Are there any related moments to compare?",
            "category": "compare",
        })

    # Always add a "deeper" suggestion
    if len(suggestions) < 3:
        suggestions.append({
            "question": "What else should I know about this topic?",
            "category": "deeper",
        })

    return suggestions[:3]


# =============================================================================
# Custom Retry Policy (Per-Exception)
# =============================================================================


def create_smart_retry_policy(max_attempts: int = 3) -> RetryPolicy:
    """
    Create a retry policy that only retries transient errors.
    
    Per-exception retry - doesn't retry auth/validation errors.
    """
    return RetryPolicy(
        max_attempts=max_attempts,
        initial_interval=1.0,
        backoff_factor=2.0,
        retry_on=should_retry_exception,
    )


# =============================================================================
# Graph Builder
# =============================================================================


def create_video_agent_graph(checkpointer=None):
    """
    Create the video agent graph.

    Args:
        checkpointer: LangGraph checkpointer for persistence

    Returns a compiled StateGraph with:
    - call_model: Invokes LLM with tools
    - tools: Executes tool calls with error handling
    - update_context: Updates conversation context after tool execution
    - error_handler: Graceful degradation when tools fail repeatedly
    - Conditional routing with iteration limits

    Flow:
        START → call_model → should_continue?
                    ↓ tools          ↓ end
                  tools → update_context → call_model
                    ↓ error_handler
              error_handler → END
              
    Input/Output Schema Separation:
    - Input: AgentInputState (clean API interface)
    - Output: AgentOutputState (only relevant results)
    - Internal: AgentState (full state with bookkeeping)
    """
    # Use input/output schema separation for clean API boundaries
    workflow = StateGraph(
        AgentState,
        input_schema=AgentInputState,
        output_schema=AgentOutputState,
    )

    # Add nodes with smart retry policies (only retry transient errors)
    workflow.add_node(
        "call_model",
        call_model,
        retry_policy=create_smart_retry_policy(max_attempts=3),
    )
    workflow.add_node(
        "tools",
        ToolNode(SEARCH_TOOLS, handle_tool_errors=True),
        retry_policy=create_smart_retry_policy(max_attempts=2),
    )
    workflow.add_node("update_context", update_context)
    workflow.add_node("error_handler", error_handler_node)

    # Entry point
    workflow.add_edge(START, "call_model")

    # Conditional routing with iteration limits and error handling
    workflow.add_conditional_edges(
        "call_model",
        should_continue,
        {
            "tools": "tools",
            "error_handler": "error_handler",
            END: END,
        }
    )

    # Tools go to context update, then back to model
    workflow.add_edge("tools", "update_context")
    workflow.add_edge("update_context", "call_model")
    
    # Error handler ends the conversation gracefully
    workflow.add_edge("error_handler", END)

    # Compile with checkpointer
    if checkpointer is None:
        logger.warning(
            "No checkpointer provided, using in-memory MemorySaver. "
            "This is NOT suitable for production - use Redis or PostgreSQL checkpointer."
        )
        checkpointer = MemorySaver()

    return workflow.compile(checkpointer=checkpointer)


# =============================================================================
# Video Agent Class (High-level API)
# =============================================================================


class VideoAgentGraph:
    """
    High-level API for the video agent using LangGraph.

    Features:
    - Streaming responses with astream_events
    - Session persistence via checkpointer
    - Graph visualization with get_graph_diagram()
    """

    def __init__(
        self,
        model_deployment: str | None = None,
        checkpointer=None,
    ):
        self.model_deployment = model_deployment or os.getenv(
            "AZURE_OPENAI_DEPLOYMENT_GPT", "gpt-4o"
        )
        self.checkpointer = checkpointer
        self._graph = None

    @property
    def graph(self) -> StateGraph:
        """Get or create the compiled graph."""
        if self._graph is None:
            self._graph = create_video_agent_graph(self.checkpointer)
        return self._graph

    def get_graph_diagram(self, output_format: str = "mermaid") -> str:
        """Get a visual representation of the agent graph."""
        try:
            if output_format == "mermaid":
                return self.graph.get_graph().draw_mermaid()
            else:
                return self.graph.get_graph().draw_ascii()
        except Exception as e:
            logger.warning(f"Failed to generate graph diagram: {e}")
            return f"Graph visualization failed: {e}"

    def _build_messages(
        self, message: str, chat_history: list[dict] | None = None
    ) -> list:
        """Build LangChain message list from user input and chat history."""
        messages = []
        if chat_history:
            for msg in chat_history:
                if msg["role"] == "user":
                    messages.append(HumanMessage(content=msg["content"]))
                elif msg["role"] == "assistant":
                    messages.append(AIMessage(content=msg["content"]))
        messages.append(HumanMessage(content=message))
        return messages

    def _build_config(
        self, media_id: str | None, session_id: str | None
    ) -> RunnableConfig:
        """Build RunnableConfig for graph invocation."""
        return RunnableConfig(
            configurable={
                "thread_id": session_id or "default",
                "media_id": media_id,
                "model_deployment": self.model_deployment,
            }
        )

    async def run(
        self,
        message: str,
        media_id: str | None = None,
        chat_history: list[dict] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Run the agent on a user message.

        Returns:
            Dict with 'response', 'sources', 'tool_calls_made', and rich metadata
        """
        messages = self._build_messages(message, chat_history)
        state = create_agent_state(
            messages=messages,
            media_id=media_id,
            user_id=user_id,
            session_id=session_id,
        )
        config = self._build_config(media_id, session_id)

        logger.info(f"Agent starting - media_id={media_id}, message={message[:50]}...")

        try:
            result = await self.graph.ainvoke(state, config)

            # Extract response
            final_message = result["messages"][-1]
            response = final_message.content if hasattr(final_message, "content") else str(final_message)

            # Extract rich metadata using shared helper
            metadata = extract_metadata_from_messages(result["messages"])
            suggested_questions = _generate_suggestions(
                message, metadata["sources"], metadata["entities_mentioned"]
            )

            return {
                "response": response,
                "sources": metadata["sources"][:15],
                "tool_calls_made": metadata["tool_calls"],
                "navigation_actions": metadata["navigation_actions"][:10],
                "clip_suggestions": metadata["clip_suggestions"][:5],
                "entities_mentioned": metadata["entities_mentioned"][:10],
                "suggested_questions": suggested_questions,
            }

        except Exception as e:
            logger.error(f"Agent error: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {
                "response": f"I encountered an error: {str(e)}",
                "sources": [],
                "tool_calls_made": 0,
            }

    async def run_stream(
        self,
        message: str,
        media_id: str | None = None,
        chat_history: list[dict] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Run the agent with streaming responses.

        Yields events:
        - thinking: Agent is processing
        - tool_start: Starting a tool call
        - tool_end: Tool call completed
        - token: Streaming response token
        - sources, navigation, clips, entities: Rich metadata
        - done: Final response complete
        - error: Error occurred
        """
        messages = self._build_messages(message, chat_history)
        state = create_agent_state(
            messages=messages,
            media_id=media_id,
            user_id=user_id,
            session_id=session_id,
        )
        config = self._build_config(media_id, session_id)

        logger.info(f"Agent stream starting - media_id={media_id}")

        sources = []
        navigation_actions = []
        clip_suggestions = []
        entities_mentioned = []
        tool_calls_made = 0
        collected_response = ""

        try:
            async for event in self.graph.astream_events(state, config, version="v2"):
                event_type = event["event"]

                if event_type == "on_chat_model_start":
                    yield {"event": "thinking", "data": {"iteration": tool_calls_made}}

                elif event_type == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    if hasattr(chunk, "content") and chunk.content:
                        collected_response += chunk.content
                        yield {"event": "token", "data": {"token": chunk.content}}

                elif event_type == "on_tool_start":
                    tool_name = event["name"]
                    tool_input = event.get("data", {}).get("input", {})
                    input_summary = ""
                    if isinstance(tool_input, dict):
                        if "query" in tool_input:
                            input_summary = f"Searching: {tool_input['query'][:50]}..."
                        elif "entity_name" in tool_input:
                            input_summary = f"Finding: {tool_input['entity_name']}"
                        elif "timestamps" in tool_input:
                            input_summary = f"Comparing {len(tool_input['timestamps'])} moments"
                        elif "topic" in tool_input:
                            input_summary = f"Topic: {tool_input['topic'][:30]}..."
                    yield {
                        "event": "tool_start",
                        "data": {
                            "tool": tool_name,
                            "tool_call_id": event.get("run_id", ""),
                            "description": input_summary,
                        },
                    }

                elif event_type == "on_tool_end":
                    tool_name = event["name"]
                    output = event["data"].get("output", {})
                    tool_calls_made += 1
                    result_count = 0

                    if isinstance(output, str):
                        try:
                            output = json.loads(output)
                        except (json.JSONDecodeError, TypeError):
                            pass

                    if isinstance(output, dict):
                        meta = extract_metadata_from_tool_result(output)
                        result_count = (
                            len(meta["sources"])
                            + len(meta["clip_suggestions"])
                            + len(meta["entities"])
                        )
                        sources.extend(meta["sources"])
                        navigation_actions.extend(meta["navigation_actions"])
                        clip_suggestions.extend(meta["clip_suggestions"])
                        entities_mentioned.extend(meta["entities"])

                    yield {
                        "event": "tool_end",
                        "data": {
                            "tool": tool_name,
                            "tool_call_id": event.get("run_id", ""),
                            "success": not output.get("error") if isinstance(output, dict) else True,
                            "result_count": result_count,
                        },
                    }

                elif event_type == "on_chain_end" and event["name"] == "LangGraph":
                    if sources:
                        yield {"event": "sources", "data": {"sources": sources[:15]}}
                    if navigation_actions:
                        yield {"event": "navigation", "data": {"actions": navigation_actions[:10]}}
                    if clip_suggestions:
                        yield {"event": "clips", "data": {"suggestions": clip_suggestions[:5]}}
                    if entities_mentioned:
                        yield {"event": "entities", "data": {"entities": entities_mentioned[:10]}}

                    suggested_questions = _generate_suggestions(message, sources, entities_mentioned)

                    final_output = event["data"].get("output", {})
                    final_messages = final_output.get("messages", [])
                    if final_messages:
                        last_msg = final_messages[-1]
                        final_response = last_msg.content if hasattr(last_msg, "content") else collected_response
                    else:
                        final_response = collected_response

                    yield {
                        "event": "done",
                        "data": {
                            "response": final_response,
                            "sources": sources[:15],
                            "tool_calls_made": tool_calls_made,
                            "navigation_actions": navigation_actions[:10],
                            "clip_suggestions": clip_suggestions[:5],
                            "entities_mentioned": entities_mentioned[:10],
                            "suggested_questions": suggested_questions,
                        },
                    }

        except Exception as e:
            logger.error(f"Agent stream error: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            yield {"event": "error", "data": {"error": str(e) or repr(e)}}

    async def get_state_history(
        self,
        session_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get the state history for a session (useful for debugging)."""
        config = RunnableConfig(configurable={"thread_id": session_id})
        history = []

        try:
            async for state in self.graph.aget_state_history(config):
                history.append({
                    "config": state.config,
                    "values": state.values,
                    "next": state.next,
                    "created_at": state.created_at,
                })
                if len(history) >= limit:
                    break
        except Exception as e:
            logger.warning(f"Failed to get state history: {e}")

        return history

    async def resume_from_checkpoint(
        self,
        session_id: str,
        new_message: str | None = None,
    ) -> dict[str, Any]:
        """Resume agent execution from a checkpoint."""
        config = RunnableConfig(configurable={"thread_id": session_id})

        if new_message:
            await self.graph.aupdate_state(
                config,
                {"messages": [HumanMessage(content=new_message)]},
            )

        result = await self.graph.ainvoke(None, config)

        final_message = result["messages"][-1]
        response = final_message.content if hasattr(final_message, "content") else str(final_message)

        return {
            "response": response,
            "sources": result.get("sources", []),
            "resumed_from": session_id,
        }


# =============================================================================
# Factory Functions
# =============================================================================

_graph_instance: VideoAgentGraph | None = None


def get_video_agent_graph(checkpointer=None) -> VideoAgentGraph:
    """Get or create the video agent graph singleton."""
    global _graph_instance
    if _graph_instance is None:
        _graph_instance = VideoAgentGraph(checkpointer=checkpointer)
    return _graph_instance


def create_postgres_checkpointer():
    """
    Create PostgreSQL checkpointer from environment.
    
    Uses langgraph-checkpoint-postgres package for production persistence.
    """
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            logger.warning("DATABASE_URL not set, cannot create PostgreSQL checkpointer")
            return None
        
        saver = AsyncPostgresSaver.from_conn_string(database_url)
        logger.info("PostgreSQL checkpointer created successfully")
        return saver
    except ImportError as e:
        logger.warning(f"PostgreSQL checkpoint package not installed: {e}")
        return None
    except Exception as e:
        logger.warning(f"Failed to create PostgreSQL checkpointer: {e}")
        return None


def create_redis_checkpointer():
    """Create Redis checkpointer from environment.

    Uses langgraph-checkpoint-redis package which requires Redis Stack (with RediSearch).
    Falls back to None if Redis Stack is not available.
    See: https://github.com/redis-developer/langgraph-redis
    """
    try:
        from langgraph.checkpoint.redis.aio import AsyncRedisSaver

        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        saver = AsyncRedisSaver(redis_url=redis_url)
        logger.info("Async Redis checkpointer created successfully")
        return saver
    except ImportError as e:
        logger.warning(f"Redis checkpoint packages not installed: {e}")
        return None
    except Exception as e:
        logger.warning(f"Failed to create Redis checkpointer (Redis Stack may not be available): {e}")
        return None


def create_production_checkpointer():
    """
    Create the best available checkpointer for production.
    
    Cascade order: PostgreSQL > Redis > MemorySaver
    
    PostgreSQL is preferred for:
    - Durability and ACID compliance
    - Existing infrastructure (already used for app data)
    - Better querying capabilities
    
    Redis is used when:
    - PostgreSQL is not available
    - Low-latency requirements
    
    MemorySaver is a last resort (not production-ready).
    """
    # Try PostgreSQL first (most durable)
    checkpointer = create_postgres_checkpointer()
    if checkpointer is not None:
        logger.info("Using PostgreSQL checkpointer for production")
        return checkpointer
    
    # Fall back to Redis (fast, but less durable)
    checkpointer = create_redis_checkpointer()
    if checkpointer is not None:
        logger.info("Using Redis checkpointer (PostgreSQL unavailable)")
        return checkpointer
    
    # Last resort: MemorySaver (NOT production-ready)
    logger.warning(
        "No persistent checkpointer available! Using in-memory MemorySaver. "
        "This is NOT suitable for production - install langgraph-checkpoint-postgres "
        "or langgraph-checkpoint-redis and configure DATABASE_URL or REDIS_URL."
    )
    return MemorySaver()
