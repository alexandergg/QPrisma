"""
LangGraph Video Agent
=====================

Video agent implemented using LangGraph StateGraph pattern.
Provides a declarative, composable agent with built-in streaming and checkpointing.

Architecture:
    START → call_model → tools_condition? → tools → update_context → call_model → ... → END
                              ↓ no
                            END

Features:
- Automatic context tracking for conversation memory
- Tool call counting for iteration management
- Enhanced prompts for detailed responses
- Graph relationship exploration

Best Practices Applied:
- Uses prebuilt tools_condition for routing
- Uses ToolNode with handle_tool_errors for graceful error handling
- Uses START constant for modern entry point
- Supports graph visualization with get_graph()
"""

import logging
import os
import re
from collections.abc import AsyncGenerator
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import AzureChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from agent.graph_state import (
    AgentState,
    MAX_TOOL_RESULT_CHARS,
    _truncate_tool_message_content,
    create_agent_state,
    get_message_trimmer,
)
from agent.graph_tools import SEARCH_TOOLS
from agent.prompts import NO_VIDEO_CONTEXT_PROMPT, SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# Message trimmer to prevent context overflow - use conservative limit
_message_trimmer = get_message_trimmer(max_tokens=80000)

# Maximum tool iterations to prevent infinite loops
MAX_TOOL_ITERATIONS = 5  # Reduced from 8 - most queries should complete in 3-4 calls
WARN_TOOL_ITERATIONS = 3  # Warn the model to start summarizing


# =============================================================================
# Graph Nodes
# =============================================================================


def create_model(model_deployment: str | None = None) -> AzureChatOpenAI:
    """Create Azure OpenAI chat model."""
    deployment = model_deployment or os.getenv("AZURE_OPENAI_DEPLOYMENT_GPT", "gpt-4o")

    return AzureChatOpenAI(
        azure_deployment=deployment,
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-04-01-preview"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        streaming=True,
    )


def get_system_message(state: AgentState) -> SystemMessage:
    """Build system message based on video context and conversation history."""
    video_context = state.get("video_context")
    media_id = state.get("media_id")
    conversation_context = state.get("conversation_context", [])

    # Check if we have video context (either from video_context dict or media_id field)
    has_video = (video_context and video_context.get("media_id")) or media_id

    if has_video:
        content = SYSTEM_PROMPT
        if video_context and video_context.get("title"):
            content += f"\n\n**Current Video:** {video_context.get('title')}"
        if video_context and video_context.get("duration"):
            from agent.tools.base import format_timestamp
            duration = video_context.get("duration")
            content += f" (Duration: {format_timestamp(duration)})"
        
        # Add conversation context for memory
        if conversation_context:
            content += f"\n\n**Previous Topics Discussed:** {', '.join(conversation_context[-5:])}"
    else:
        content = NO_VIDEO_CONTEXT_PROMPT

    return SystemMessage(content=content)


def extract_topics_from_messages(messages: list) -> list[str]:
    """Extract key topics/entities from conversation for context memory."""
    topics = set()
    
    for msg in messages:
        if isinstance(msg, HumanMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            # Extract quoted phrases
            quotes = re.findall(r'"([^"]+)"', content)
            topics.update(quotes)
            # Extract capitalized words (potential entities)
            caps = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', content)
            topics.update(caps)
        elif isinstance(msg, ToolMessage):
            # Extract from tool results
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            # Look for entity names in results
            entity_matches = re.findall(r'"name":\s*"([^"]+)"', content)
            topics.update(entity_matches)
    
    return list(topics)[:10]  # Keep last 10 topics


async def call_model(state: AgentState, config: RunnableConfig) -> dict:
    """
    Call the LLM node.

    Invokes the model with current messages and available tools.
    Uses message trimming to prevent context window overflow.
    Returns updated messages with AI response.
    """
    # Get model from config or create default
    model_deployment = config.get("configurable", {}).get("model_deployment")
    model = create_model(model_deployment)

    # Check tool call count for iteration management
    tool_calls_count = state.get("tool_calls_count", 0)
    approaching_limit = tool_calls_count >= WARN_TOOL_ITERATIONS

    # Bind tools only if we have video context AND not at limit
    video_context = state.get("video_context")
    media_id = state.get("media_id")
    has_video = (video_context and video_context.get("media_id")) or media_id
    
    # If approaching limit, don't bind tools to force a final response
    if has_video and not approaching_limit:
        model = model.bind_tools(SEARCH_TOOLS)
    elif approaching_limit:
        logger.info(f"Tool calls at {tool_calls_count}, not binding tools to encourage final response")

    # Build messages with system prompt
    system_msg = get_system_message(state)

    # Truncate tool messages to prevent large results from overflowing context
    truncated_messages = [
        _truncate_tool_message_content(msg) for msg in state["messages"]
    ]

    # Apply message trimming to prevent context overflow
    trimmed_messages = _message_trimmer.invoke(truncated_messages)
    messages = [system_msg] + trimmed_messages
    
    # If approaching limit, add a hint to summarize
    if approaching_limit:
        from langchain_core.messages import SystemMessage as SysMsg
        hint = SysMsg(content=(
            "IMPORTANT: You have gathered enough information. "
            "Do NOT make any more tool calls. "
            "Provide your final comprehensive response NOW based on the information you've collected."
        ))
        messages.append(hint)
    
    # Log context size for debugging
    total_chars = sum(len(str(m.content)) for m in messages if m.content)
    logger.info(f"Calling model with {len(messages)} messages (~{total_chars // 4} tokens)")

    # Invoke model
    response = await model.ainvoke(messages, config)

    # Update tool call count if this is a tool call
    if hasattr(response, "tool_calls") and response.tool_calls:
        tool_calls_count += len(response.tool_calls)

    return {
        "messages": [response],
        "tool_calls_count": tool_calls_count,
    }


async def update_context(state: AgentState, config: RunnableConfig) -> dict:
    """
    Update conversation context after tool execution.
    
    Extracts key topics and entities from the conversation
    to maintain context awareness across turns.
    """
    messages = state.get("messages", [])
    existing_context = state.get("conversation_context", [])
    
    # Extract new topics from recent messages
    recent_messages = messages[-5:] if len(messages) > 5 else messages
    new_topics = extract_topics_from_messages(recent_messages)
    
    # Merge with existing context, keeping unique items
    combined = list(dict.fromkeys(existing_context + new_topics))
    
    return {
        "conversation_context": combined[-15:],  # Keep last 15 topics
    }


def should_continue(state: AgentState) -> str:
    """
    Determine if the agent should continue or end.
    
    Checks:
    1. If there are tool calls to execute
    2. If we've exceeded max iterations
    """
    messages = state.get("messages", [])
    tool_calls_count = state.get("tool_calls_count", 0)
    
    if not messages:
        return END
    
    last_message = messages[-1]
    
    # Check for tool calls
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        # Check iteration limit
        if tool_calls_count >= MAX_TOOL_ITERATIONS:
            logger.warning(f"Reached max tool iterations ({MAX_TOOL_ITERATIONS}), forcing end")
            return END
        return "tools"
    
    return END


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
    - Conditional routing with iteration limits
    
    Flow:
        START → call_model → should_continue?
                    ↓ tools          ↓ end
                  tools → update_context → call_model
    """
    # Create graph
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("call_model", call_model)
    # Use ToolNode with handle_tool_errors for graceful error handling
    workflow.add_node("tools", ToolNode(SEARCH_TOOLS, handle_tool_errors=True))
    # Context update node for conversation memory
    workflow.add_node("update_context", update_context)

    # Use START constant for entry point (modern pattern)
    workflow.add_edge(START, "call_model")

    # Use custom should_continue for iteration limits
    workflow.add_conditional_edges(
        "call_model",
        should_continue,
        {
            "tools": "tools",
            END: END,
        }
    )

    # Tools go to context update, then back to model
    workflow.add_edge("tools", "update_context")
    workflow.add_edge("update_context", "call_model")

    # Compile with checkpointer
    if checkpointer is None:
        checkpointer = MemorySaver()

    return workflow.compile(checkpointer=checkpointer)


# =============================================================================
# Video Agent Class (High-level API)
# =============================================================================


class VideoAgentGraph:
    """
    High-level API for the video agent using LangGraph.

    Provides backward-compatible interface with the original VideoAgent.

    Features:
    - Streaming responses with astream_events
    - Session persistence via checkpointer
    - Graph visualization with get_graph_image()
    """

    def __init__(
        self,
        model_deployment: str | None = None,
        checkpointer=None,
    ):
        """
        Initialize the video agent.

        Args:
            model_deployment: Azure OpenAI deployment name
            checkpointer: LangGraph checkpointer for persistence
        """
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
        """
        Get a visual representation of the agent graph.

        Args:
            output_format: "mermaid" for Mermaid diagram, "ascii" for ASCII art

        Returns:
            String representation of the graph
        """
        try:
            if output_format == "mermaid":
                return self.graph.get_graph().draw_mermaid()
            else:
                return self.graph.get_graph().draw_ascii()
        except Exception as e:
            logger.warning(f"Failed to generate graph diagram: {e}")
            return f"Graph visualization failed: {e}"

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

        Args:
            message: User's message
            media_id: Optional video ID for context
            chat_history: Previous conversation messages
            user_id: User identifier
            session_id: Session identifier for checkpointing

        Returns:
            Dict with 'response', 'sources', 'tool_calls_made', and rich metadata
        """
        # Build messages
        messages = []
        if chat_history:
            for msg in chat_history:
                if msg["role"] == "user":
                    messages.append(HumanMessage(content=msg["content"]))
                elif msg["role"] == "assistant":
                    messages.append(AIMessage(content=msg["content"]))

        messages.append(HumanMessage(content=message))

        # Create initial state
        state = create_agent_state(
            messages=messages,
            media_id=media_id,
            user_id=user_id,
            session_id=session_id,
        )

        # Build config
        config = RunnableConfig(
            configurable={
                "thread_id": session_id or "default",
                "media_id": media_id,
                "model_deployment": self.model_deployment,
            }
        )

        logger.info(f"Agent starting - media_id={media_id}, message={message[:50]}...")

        # Run graph
        try:
            result = await self.graph.ainvoke(state, config)

            # Extract response
            final_message = result["messages"][-1]
            response = final_message.content if hasattr(final_message, "content") else str(final_message)

            # Count tool calls and extract rich metadata
            tool_calls = 0
            sources = []
            navigation_actions = []
            clip_suggestions = []
            entities_mentioned = []
            
            for msg in result["messages"]:
                if isinstance(msg, AIMessage) and msg.tool_calls:
                    tool_calls += len(msg.tool_calls)
                
                # Extract from ToolMessages
                if hasattr(msg, "name") and hasattr(msg, "content"):
                    try:
                        import json
                        tool_result = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
                        
                        if isinstance(tool_result, dict):
                            # Extract sources from search results
                            if "results" in tool_result:
                                for r in tool_result.get("results", []):
                                    if isinstance(r, dict) and "timestamp" in r:
                                        sources.append({
                                            "timestamp": r.get("timestamp", 0),
                                            "timestamp_formatted": r.get("timestamp_formatted", ""),
                                            "type": r.get("type", "unknown"),
                                            "description": r.get("content", r.get("description", ""))[:150],
                                            "score": r.get("score", 0),
                                        })
                                        # Create navigation action for each result
                                        navigation_actions.append({
                                            "action": "jump_to",
                                            "label": f"Go to {r.get('timestamp_formatted', '')}",
                                            "timestamp": r.get("timestamp", 0),
                                        })
                            
                            # Extract from occurrences (find_entity)
                            if "occurrences" in tool_result:
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
                            if "highlights" in tool_result:
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
                            if "timeline" in tool_result:
                                for t in tool_result.get("timeline", [])[:5]:
                                    if isinstance(t, dict) and "timestamp" in t:
                                        sources.append({
                                            "timestamp": t.get("timestamp", 0),
                                            "timestamp_formatted": t.get("timestamp_formatted", ""),
                                            "type": t.get("appearance_type", "timeline"),
                                            "description": t.get("context", "")[:150] if t.get("context") else "",
                                            "score": 0,
                                        })
                            
                            # Extract from moments (compare_moments output)
                            if "moments" in tool_result:
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
                            if "related_entities" in tool_result:
                                for e in tool_result.get("related_entities", []):
                                    entities_mentioned.append({
                                        "name": e.get("name"),
                                        "type": e.get("type"),
                                        "relevance": e.get("relevance", 0),
                                    })
                    except (json.JSONDecodeError, TypeError):
                        pass

            # Generate suggested follow-up questions based on query type
            suggested_questions = _generate_suggestions(message, sources, entities_mentioned)

            return {
                "response": response,
                "sources": sources[:15],  # Limit sources
                "tool_calls_made": tool_calls,
                "navigation_actions": navigation_actions[:10],
                "clip_suggestions": clip_suggestions[:5],
                "entities_mentioned": entities_mentioned[:10],
                "suggested_questions": suggested_questions,
            }

        except Exception as e:
            import traceback
            logger.error(f"Agent error: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {
                "response": f"I encountered an error: {str(e)}",
                "sources": [],
                "tool_calls_made": 0,
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


# Add run_stream method to VideoAgentGraph class
# This is done via monkey-patching because the method body was accidentally
# defined outside the class during code generation
async def _video_agent_run_stream(
    self,
    message: str,
    media_id: str | None = None,
    chat_history: list[dict] | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """
    Run the agent with streaming responses.

    Yields events compatible with the original StreamEvent format:
    - thinking: Agent is processing
    - tool_start: Starting a tool call (includes tool name and inputs)
    - tool_end: Tool call completed (includes success and result count)
    - token: Streaming response token
    - sources: Sources found during search
    - navigation: Navigation actions available
    - clips: Clip suggestions found
    - entities: Entities mentioned
    - done: Final response complete with all metadata
    - error: Error occurred
    """
    # Build messages
    messages = []
    if chat_history:
        for msg in chat_history:
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                messages.append(AIMessage(content=msg["content"]))

    messages.append(HumanMessage(content=message))

    # Create initial state
    state = create_agent_state(
        messages=messages,
        media_id=media_id,
        user_id=user_id,
        session_id=session_id,
    )

    # Build config
    config = RunnableConfig(
        configurable={
            "thread_id": session_id or "default",
            "media_id": media_id,
            "model_deployment": self.model_deployment,
        }
    )

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

            # Handle different event types
            if event_type == "on_chat_model_start":
                yield {"event": "thinking", "data": {"iteration": tool_calls_made}}

            elif event_type == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if hasattr(chunk, "content") and chunk.content:
                    collected_response += chunk.content
                    yield {"event": "token", "data": {"token": chunk.content}}

            elif event_type == "on_tool_start":
                tool_name = event["name"]
                # Try to extract tool inputs for richer UI feedback
                tool_input = event.get("data", {}).get("input", {})
                input_summary = ""
                if isinstance(tool_input, dict):
                    # Summarize the input for display
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

                # Parse output if it's a string (JSON)
                if isinstance(output, str):
                    try:
                        output = json.loads(output)
                    except (json.JSONDecodeError, TypeError):
                        pass

                if isinstance(output, dict):
                    # Extract sources from search results
                    if "results" in output:
                        for r in output.get("results", []):
                            if isinstance(r, dict) and "timestamp" in r:
                                result_count += 1
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
                    if "occurrences" in output:
                        for occ in output.get("occurrences", []):
                            if isinstance(occ, dict) and "timestamp" in occ:
                                result_count += 1
                                sources.append({
                                    "timestamp": occ.get("timestamp", 0),
                                    "timestamp_formatted": occ.get("timestamp_formatted", ""),
                                    "type": occ.get("occurrence_type", "entity"),
                                    "description": occ.get("context", "")[:150],
                                    "score": occ.get("confidence", 0),
                                })

                    # Extract clip suggestions from highlights
                    if "highlights" in output:
                        for h in output.get("highlights", []):
                            result_count += 1
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
                    if "timeline" in output:
                        for t in output.get("timeline", [])[:10]:
                            if isinstance(t, dict) and "timestamp" in t:
                                result_count += 1
                                sources.append({
                                    "timestamp": t.get("timestamp", 0),
                                    "timestamp_formatted": t.get("timestamp_formatted", ""),
                                    "type": t.get("appearance_type", "timeline"),
                                    "description": t.get("context", "")[:150] if t.get("context") else "",
                                    "score": 0,
                                })

                    # Extract from moments (compare_moments output)
                    if "moments" in output:
                        for m in output.get("moments", []):
                            if isinstance(m, dict) and "timestamp" in m:
                                result_count += 1
                                ts = m.get("timestamp", 0)
                                ts_fmt = m.get("timestamp_formatted", "")
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
                    if "related_entities" in output:
                        for e in output.get("related_entities", []):
                            entities_mentioned.append({
                                "name": e.get("name"),
                                "type": e.get("type"),
                                "relevance": e.get("relevance", 0),
                            })

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
                # Emit rich metadata events before final done
                if sources:
                    yield {"event": "sources", "data": {"sources": sources[:15]}}

                if navigation_actions:
                    yield {"event": "navigation", "data": {"actions": navigation_actions[:10]}}

                if clip_suggestions:
                    yield {"event": "clips", "data": {"suggestions": clip_suggestions[:5]}}

                if entities_mentioned:
                    yield {"event": "entities", "data": {"entities": entities_mentioned[:10]}}

                # Generate suggested questions
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
        import traceback
        logger.error(f"Agent stream error: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        yield {"event": "error", "data": {"error": str(e) or repr(e)}}


async def _video_agent_get_state_history(
    self,
    session_id: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Get the state history for a session (useful for debugging).

    Args:
        session_id: The session/thread ID
        limit: Maximum number of states to return

    Returns:
        List of state snapshots
    """
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


async def _video_agent_resume_from_checkpoint(
    self,
    session_id: str,
    new_message: str | None = None,
) -> dict[str, Any]:
    """
    Resume agent execution from a checkpoint.

    Args:
        session_id: The session/thread ID to resume
        new_message: Optional new message to add before resuming

    Returns:
        Agent response
    """
    config = RunnableConfig(configurable={"thread_id": session_id})

    if new_message:
        # Add new message to state
        await self.graph.aupdate_state(
            config,
            {"messages": [HumanMessage(content=new_message)]},
        )

    # Resume execution
    result = await self.graph.ainvoke(None, config)

    final_message = result["messages"][-1]
    response = final_message.content if hasattr(final_message, "content") else str(final_message)

    return {
        "response": response,
        "sources": result.get("sources", []),
        "resumed_from": session_id,
    }


# Attach the streaming methods to VideoAgentGraph class
VideoAgentGraph.run_stream = _video_agent_run_stream
VideoAgentGraph.get_state_history = _video_agent_get_state_history
VideoAgentGraph.resume_from_checkpoint = _video_agent_resume_from_checkpoint


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


def create_redis_checkpointer():
    """Create Redis checkpointer from environment.
    
    Uses langgraph-checkpoint-redis package which requires Redis Stack (with RediSearch).
    Falls back to MemorySaver if Redis Stack is not available.
    See: https://github.com/redis-developer/langgraph-redis
    """
    try:
        from langgraph.checkpoint.redis.aio import AsyncRedisSaver

        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        # AsyncRedisSaver for async graph execution
        saver = AsyncRedisSaver(redis_url=redis_url)
        # Note: setup() will be called on first use
        logger.info("Async Redis checkpointer created successfully")
        return saver
    except ImportError as e:
        logger.warning(f"Redis checkpoint packages not installed: {e}. Using memory saver.")
        return MemorySaver()
    except Exception as e:
        logger.warning(f"Failed to create Redis checkpointer (Redis Stack may not be available): {e}. Using memory saver.")
        return MemorySaver()
