"""
Base Agent Nodes
================

Shared node implementations for LangGraph agents.
DRY pattern - unifies common code between video_nodes and editor_nodes.

Features:
- Configurable model creation with caching
- Shared message trimming and context management
- Error handling with graceful degradation
- Tool iteration management
- Structured logging with correlation IDs
- Prometheus-style metrics
"""

import os
import re
import time
from functools import lru_cache
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import AzureChatOpenAI
from langgraph.graph import END

from agent.state.agent_state import (
    AgentState,
    truncate_tool_message_content,
    get_message_trimmer,
    should_retry_exception,
)
from agent.utils.observability import (
    get_logger,
    get_request_context,
    extract_request_id_from_config,
    Metrics,
)

logger = get_logger(__name__)

# Shared message trimmer instance
_message_trimmer = get_message_trimmer(max_tokens=80000)

# Iteration limits
DEFAULT_MAX_TOOL_ITERATIONS = 5
DEFAULT_WARN_TOOL_ITERATIONS = 3
EDITOR_MAX_TOOL_ITERATIONS = 8
EDITOR_WARN_TOOL_ITERATIONS = 6

# Error thresholds for graceful degradation
MAX_CONSECUTIVE_ERRORS = 3


# =============================================================================
# Model Creation (Cached)
# =============================================================================


@lru_cache(maxsize=8)
def create_model(
    model_deployment: str | None = None,
    temperature: float = 1,
    streaming: bool = True,
) -> AzureChatOpenAI:
    """
    Create Azure OpenAI chat model (cached by deployment + params).
    
    Args:
        model_deployment: Azure deployment name
        temperature: Model temperature
        streaming: Enable streaming responses
        
    Returns:
        Configured AzureChatOpenAI instance
    """
    deployment = model_deployment or os.getenv("AZURE_OPENAI_DEPLOYMENT_GPT", "gpt-4o")

    return AzureChatOpenAI(
        azure_deployment=deployment,
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-04-01-preview"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        temperature=temperature,
        streaming=streaming,
    )


# =============================================================================
# Context Extraction
# =============================================================================


def extract_topics_from_messages(messages: list) -> list[str]:
    """
    Extract key topics/entities from conversation for context memory.
    
    Used to maintain awareness of what has been discussed.
    """
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


# =============================================================================
# Shared Node Logic
# =============================================================================


async def base_call_model(
    state: AgentState,
    config: RunnableConfig,
    tools: list,
    system_message: SystemMessage,
    max_iterations: int = DEFAULT_MAX_TOOL_ITERATIONS,
    warn_iterations: int = DEFAULT_WARN_TOOL_ITERATIONS,
    temperature: float = 1,
) -> dict:
    """
    Base implementation for calling the LLM.
    
    Shared logic between video and editor agents:
    - Message trimming to prevent context overflow
    - Tool binding with iteration management
    - Error tracking for graceful degradation
    - Structured logging with correlation IDs
    - Prometheus metrics collection
    
    Args:
        state: Current agent state
        config: Runnable configuration
        tools: List of tools to bind
        system_message: System prompt message
        max_iterations: Maximum tool calls before stopping
        warn_iterations: Tool calls at which to warn about limit
        temperature: Model temperature
        
    Returns:
        State update dict with messages and tracking info
    """
    start_time = time.time()
    request_id = extract_request_id_from_config(config) or "unknown"
    
    # Get model from config or create default
    model_deployment = config.get("configurable", {}).get("model_deployment")
    model = create_model(model_deployment, temperature=temperature)

    # Check tool call count for iteration management
    tool_calls_count = state.get("tool_calls_count", 0)
    approaching_limit = tool_calls_count >= warn_iterations
    consecutive_errors = state.get("consecutive_errors", 0)
    
    logger.info(
        "base_call_model: checking tools",
        tools_provided=len(tools) if tools else 0,
        tool_names=[t.name for t in tools] if tools else [],
        tool_calls_count=tool_calls_count,
        approaching_limit=approaching_limit,
        consecutive_errors=consecutive_errors,
    )

    # If approaching limit or too many errors, don't bind tools
    should_bind_tools = (
        tools 
        and not approaching_limit 
        and consecutive_errors < MAX_CONSECUTIVE_ERRORS
    )
    
    if should_bind_tools:
        model = model.bind_tools(tools)
        logger.debug(
            "Tools bound to model",
            tool_count=len(tools),
            iteration=tool_calls_count,
        )
    elif approaching_limit:
        logger.info(
            "Not binding tools - approaching iteration limit",
            tool_calls_count=tool_calls_count,
            max_iterations=max_iterations,
        )
    elif consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
        logger.warning(
            "Not binding tools - error threshold reached",
            consecutive_errors=consecutive_errors,
        )

    # Truncate tool messages to prevent large results from overflowing context
    truncated_messages = [
        truncate_tool_message_content(msg) for msg in state["messages"]
    ]

    # Apply message trimming to prevent context overflow
    trimmed_messages = _message_trimmer.invoke(truncated_messages)
    messages = [system_message] + trimmed_messages
    
    # If approaching limit or had errors, add a hint to summarize
    if approaching_limit or consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
        partial_results = state.get("partial_results", [])
        
        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS and partial_results:
            hint_content = (
                "IMPORTANT: Some tools encountered errors, but you have partial results. "
                f"Provide your best response based on the {len(partial_results)} results gathered. "
                "Be transparent about any limitations due to errors."
            )
        else:
            hint_content = (
                "IMPORTANT: You have gathered enough information. "
                "Do NOT make any more tool calls. "
                "Provide your final comprehensive response NOW based on the information you've collected."
            )
        
        hint = SystemMessage(content=hint_content)
        messages.append(hint)
    
    # Log context size for debugging
    total_chars = sum(len(str(m.content)) for m in messages if m.content)
    estimated_tokens = total_chars // 4
    logger.info(
        "Calling LLM",
        message_count=len(messages),
        estimated_tokens=estimated_tokens,
        tool_calls_count=tool_calls_count,
        model=model_deployment or "default",
    )

    try:
        # Invoke model
        response = await model.ainvoke(messages, config)
        
        duration_ms = (time.time() - start_time) * 1000

        # Update tool call count if this is a tool call
        new_tool_calls = 0
        if hasattr(response, "tool_calls") and response.tool_calls:
            new_tool_calls = len(response.tool_calls)
            tool_calls_count += new_tool_calls

        # Record metrics
        Metrics.record_node_execution("call_model", duration_ms / 1000)
        
        logger.info(
            "LLM call completed",
            duration_ms=round(duration_ms, 2),
            new_tool_calls=new_tool_calls,
            total_tool_calls=tool_calls_count,
            has_content=bool(response.content),
        )

        return {
            "messages": [response],
            "tool_calls_count": tool_calls_count,
            "consecutive_errors": 0,  # Reset on success
        }
        
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        logger.error(
            "LLM call failed",
            error=str(e),
            duration_ms=round(duration_ms, 2),
            tool_calls_count=tool_calls_count,
        )
        
        # Record error metrics
        Metrics.inc_counter(Metrics.GRAPH_ERRORS_TOTAL, {"node": "call_model"})
        
        # Check if we should retry
        if should_retry_exception(e):
            raise  # Let retry policy handle it
        
        # Non-retryable error - create error response
        error_msg = AIMessage(content=(
            f"I encountered an issue while processing your request: {str(e)}. "
            "Let me try to help with what I know."
        ))
        
        return {
            "messages": [error_msg],
            "tool_calls_count": tool_calls_count,
            "consecutive_errors": consecutive_errors + 1,
            "last_error": str(e),
        }


def base_should_continue(
    state: AgentState,
    max_iterations: int = DEFAULT_MAX_TOOL_ITERATIONS,
) -> Literal["tools", "error_handler", "__end__"]:
    """
    Base implementation for routing decision.
    
    Returns:
        "tools": If there are tool calls to execute
        "error_handler": If we've hit error threshold but have partial results
        "__end__": If no tool calls or max iterations exceeded
    """
    messages = state.get("messages", [])
    tool_calls_count = state.get("tool_calls_count", 0)
    consecutive_errors = state.get("consecutive_errors", 0)

    if not messages:
        return END

    last_message = messages[-1]

    # Check for tool calls
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        # Check iteration limit
        if tool_calls_count >= max_iterations:
            logger.warning(f"Reached max tool iterations ({max_iterations}), forcing end")
            return END
            
        # Check error threshold - route to error handler if we have partial results
        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            partial_results = state.get("partial_results", [])
            if partial_results:
                logger.info("Error threshold reached with partial results, routing to error handler")
                return "error_handler"
            return END
            
        return "tools"

    return END


async def update_context_node(state: AgentState, config: RunnableConfig) -> dict:
    """
    Update conversation context after tool execution.
    
    Extracts key topics and entities from the conversation
    to maintain context awareness across turns.
    Also tracks partial results for error recovery.
    """
    messages = state.get("messages", [])
    
    if not messages:
        return {}

    # Extract topics from recent messages
    current_context = state.get("conversation_context", [])
    new_topics = extract_topics_from_messages(messages[-2:])
    updated_context = list(set(current_context + new_topics))[-10:]
    
    # Track successful tool results for error recovery
    partial_results = state.get("partial_results", [])
    
    # Check last message for tool results
    if messages:
        last_msg = messages[-1]
        if isinstance(last_msg, ToolMessage):
            try:
                import json
                content = last_msg.content if isinstance(last_msg.content, str) else str(last_msg.content)
                result = json.loads(content) if content.startswith("{") else {"raw": content}
                
                # Only track successful results
                if not result.get("error"):
                    partial_results.append({
                        "tool": getattr(last_msg, "name", "unknown"),
                        "summary": content[:200],
                    })
                    # Keep last 10 partial results
                    partial_results = partial_results[-10:]
            except (json.JSONDecodeError, TypeError):
                pass
    
    return {
        "conversation_context": updated_context,
        "partial_results": partial_results,
    }


# =============================================================================
# Error Handler Node (Graceful Degradation)
# =============================================================================


async def error_handler_node(state: AgentState, config: RunnableConfig) -> dict:
    """
    Handle errors gracefully by providing a partial response.
    
    This node is triggered when:
    - Multiple consecutive tool errors occur
    - We have partial results that can still be useful
    
    Instead of crashing, it generates a helpful response
    acknowledging the limitations.
    """
    partial_results = state.get("partial_results", [])
    last_error = state.get("last_error", "unknown error")
    consecutive_errors = state.get("consecutive_errors", 0)
    
    # Log error recovery
    logger.warning(
        "Error handler triggered - recovering gracefully",
        consecutive_errors=consecutive_errors,
        partial_results_count=len(partial_results),
        last_error=last_error,
    )
    
    # Record recovery metric
    Metrics.inc_counter(Metrics.ERROR_RECOVERIES, {
        "has_partial_results": str(bool(partial_results)).lower(),
    })
    
    # Build a graceful response
    if partial_results:
        result_summary = "\n".join([
            f"- {r.get('tool', 'unknown')}: {r.get('summary', '')[:100]}..."
            for r in partial_results[:5]
        ])
        
        content = (
            f"I encountered some issues while searching ({last_error}), "
            f"but here's what I found so far:\n\n{result_summary}\n\n"
            "Would you like me to try a different approach?"
        )
    else:
        content = (
            f"I encountered an issue while processing your request: {last_error}. "
            "Could you please try rephrasing your question, or let me know if there's "
            "a specific aspect of the video you'd like me to focus on?"
        )
    
    response = AIMessage(content=content)
    
    logger.info(
        "Error handler completed - generated recovery response",
        response_length=len(content),
    )
    
    return {
        "messages": [response],
        "consecutive_errors": 0,  # Reset after handling
        "last_error": None,
    }


# =============================================================================
# Dynamic Tool Binding (P1 Improvement)
# =============================================================================


def select_tools_for_query(
    query: str,
    all_tools: list,
    max_tools: int = 8,
) -> list:
    """
    Dynamically select a focused subset of tools based on the query.
    
    Research shows binding 5-8 focused tools per turn improves
    LLM tool selection accuracy significantly.
    
    Args:
        query: User's query
        all_tools: All available tools
        max_tools: Maximum tools to bind
        
    Returns:
        Focused subset of tools
    """
    query_lower = query.lower()
    
    # Tool categories with keywords
    search_keywords = ["find", "search", "where", "when", "what", "show", "locate"]
    entity_keywords = ["who", "person", "people", "name", "character"]
    structure_keywords = ["chapter", "section", "part", "outline", "summary"]
    compare_keywords = ["compare", "difference", "similar", "versus", "vs"]
    edit_keywords = ["clip", "cut", "trim", "create", "add", "remove", "delete", "export"]
    subtitle_keywords = ["subtitle", "caption", "text", "transcri"]
    
    # Categorize tools
    search_tools = []
    entity_tools = []
    structure_tools = []
    compare_tools = []
    edit_tools = []
    subtitle_tools = []
    other_tools = []
    
    for tool in all_tools:
        tool_name = tool.name.lower()
        tool_desc = (tool.description or "").lower()
        
        if any(kw in tool_name or kw in tool_desc for kw in edit_keywords):
            edit_tools.append(tool)
        elif any(kw in tool_name or kw in tool_desc for kw in subtitle_keywords):
            subtitle_tools.append(tool)
        elif any(kw in tool_name or kw in tool_desc for kw in compare_keywords):
            compare_tools.append(tool)
        elif any(kw in tool_name or kw in tool_desc for kw in entity_keywords):
            entity_tools.append(tool)
        elif any(kw in tool_name or kw in tool_desc for kw in structure_keywords):
            structure_tools.append(tool)
        elif any(kw in tool_name or kw in tool_desc for kw in search_keywords):
            search_tools.append(tool)
        else:
            other_tools.append(tool)
    
    # Select based on query intent
    selected = []
    
    if any(kw in query_lower for kw in edit_keywords):
        selected.extend(edit_tools[:4])
        selected.extend(search_tools[:2])  # Often need to search first
    elif any(kw in query_lower for kw in subtitle_keywords):
        selected.extend(subtitle_tools[:3])
        selected.extend(edit_tools[:2])
    elif any(kw in query_lower for kw in compare_keywords):
        selected.extend(compare_tools[:2])
        selected.extend(search_tools[:3])
    elif any(kw in query_lower for kw in entity_keywords):
        selected.extend(entity_tools[:3])
        selected.extend(search_tools[:2])
    elif any(kw in query_lower for kw in structure_keywords):
        selected.extend(structure_tools[:3])
        selected.extend(search_tools[:2])
    else:
        # Default: prioritize search
        selected.extend(search_tools[:4])
        selected.extend(entity_tools[:2])
    
    # Fill remaining slots
    remaining = max_tools - len(selected)
    if remaining > 0:
        for tool in other_tools + search_tools + entity_tools:
            if tool not in selected:
                selected.append(tool)
                if len(selected) >= max_tools:
                    break
    
    return selected[:max_tools]
