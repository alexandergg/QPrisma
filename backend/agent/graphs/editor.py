"""
LangGraph Editor Agent
======================

Specialized agent for video editing through natural conversation (Chat-to-Edit).
Extends the video agent with editor-specific tools and context.

Features:
- Human-in-the-loop: Uses interrupt() for granular confirmation of destructive tools
- Input/Output schema separation for clean API boundaries
- Error handler node for graceful degradation
- tools_condition: Modern LangGraph conditional routing
- handle_tool_errors: Graceful error handling for tools
- Graph visualization: get_graph_diagram() method
- Per-exception retry policies
"""

import logging
import os
from collections.abc import AsyncGenerator
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from agent.nodes.editor_nodes import call_editor_model, get_project_context, should_continue_editor
from agent.nodes.base import error_handler_node
from agent.state.agent_state import (
    AgentState,
    AgentInputState,
    AgentOutputState,
    create_agent_state,
)
from agent.tools import EDITOR_TOOLS, SEARCH_TOOLS
from agent.graphs.video import create_smart_retry_policy

logger = logging.getLogger(__name__)

# Tools that modify clips (for human-in-the-loop support)
DESTRUCTIVE_TOOLS = {
    "create_clip", "modify_clip", "delete_clip", "reorder_clips",
    "add_suggested_clips", "add_subtitles", "change_subtitle_style", "remove_subtitles",
    "export_clip", "export_all_clips",
}

# Read-only tools that don't need confirmation
SAFE_TOOLS = {
    "list_clips", "generate_auto_clips", "list_subtitle_styles", 
    "get_export_status", "list_export_presets",
}


# =============================================================================
# Custom Tool Node with Granular Interrupts (LangGraph v1.0+ Best Practice)
# =============================================================================


async def tools_with_interrupt(state: AgentState, config: RunnableConfig) -> dict:
    """
    Tool execution node with granular interrupt() for destructive tools.
    
    This replaces interrupt_before=["tools"] with selective interruption:
    - Safe tools (list_clips, etc.) execute immediately
    - Destructive tools (create_clip, delete_clip) use interrupt() for confirmation
    
    The interrupt() function is the LangGraph v1.0+ way to handle HITL,
    allowing per-tool-call decisions instead of all-or-nothing.
    """
    from langgraph.types import interrupt
    
    messages = state.get("messages", [])
    if not messages:
        return {"messages": []}
    
    last_message = messages[-1]
    if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
        return {"messages": []}
    
    # Check if any tool calls require confirmation
    needs_confirmation = []
    safe_calls = []
    
    for tool_call in last_message.tool_calls:
        tool_name = tool_call.get("name", "")
        if tool_name in DESTRUCTIVE_TOOLS:
            needs_confirmation.append(tool_call)
        else:
            safe_calls.append(tool_call)
    
    # If there are destructive tools, interrupt for confirmation
    if needs_confirmation:
        # Build confirmation message
        tool_descriptions = []
        for tc in needs_confirmation:
            name = tc.get("name", "unknown")
            args = tc.get("args", {})
            if name == "create_clip":
                desc = f"Create clip from {args.get('start_time', '?')}s to {args.get('end_time', '?')}s"
            elif name == "delete_clip":
                desc = f"Delete clip {args.get('clip_id', 'unknown')}"
            elif name == "modify_clip":
                desc = f"Modify clip {args.get('clip_id', 'unknown')}"
            else:
                desc = f"{name} with {args}"
            tool_descriptions.append(desc)
        
        confirmation_msg = (
            "I'm about to perform the following action(s):\n"
            + "\n".join(f"  • {d}" for d in tool_descriptions)
            + "\n\nWould you like me to proceed?"
        )
        
        # Use interrupt() - this is the LangGraph v1.0+ HITL pattern
        # The graph will pause here and resume when the user responds
        user_response = interrupt({"message": confirmation_msg, "pending_tools": needs_confirmation})
        
        # If user didn't confirm, skip the destructive tools
        if not user_response.get("confirmed", False):
            from langchain_core.messages import ToolMessage
            
            cancelled_messages = []
            for tc in needs_confirmation:
                cancelled_messages.append(ToolMessage(
                    content='{"cancelled": true, "message": "Operation cancelled by user."}',
                    tool_call_id=tc.get("id", ""),
                    name=tc.get("name", ""),
                ))
            return {"messages": cancelled_messages}
    
    # Execute all approved tools
    all_tools = SEARCH_TOOLS + EDITOR_TOOLS
    tool_node = ToolNode(all_tools, handle_tool_errors=True)
    
    return await tool_node.ainvoke(state, config)


# =============================================================================
# Graph Builder
# =============================================================================


def create_editor_agent_graph(
    checkpointer=None,
    interrupt_before_clips: bool = False,
):
    """
    Create the editor agent graph.

    Args:
        checkpointer: LangGraph checkpointer for persistence
        interrupt_before_clips: If True, use granular interrupt() for destructive tools
                               (recommended for production)

    Returns a compiled StateGraph with search and editor tools.
    
    Architecture:
        START → call_model → should_continue?
                    ↓ tools          ↓ end
                  tools → call_model
                    ↓ error_handler
              error_handler → END
    
    Input/Output Schema Separation:
    - Input: AgentInputState (clean API interface)
    - Output: AgentOutputState (only relevant results)
    """
    all_tools = SEARCH_TOOLS + EDITOR_TOOLS

    # Use input/output schema separation
    workflow = StateGraph(
        AgentState,
        input_schema=AgentInputState,
        output_schema=AgentOutputState,
    )

    # Add nodes with smart retry policies
    workflow.add_node(
        "call_model",
        call_editor_model,
        retry_policy=create_smart_retry_policy(max_attempts=3),
    )
    
    # Use granular interrupt tool node or standard ToolNode
    if interrupt_before_clips:
        workflow.add_node("tools", tools_with_interrupt)
    else:
        workflow.add_node(
            "tools",
            ToolNode(all_tools, handle_tool_errors=True),
            retry_policy=create_smart_retry_policy(max_attempts=2),
        )
    
    workflow.add_node("error_handler", error_handler_node)

    workflow.add_edge(START, "call_model")

    # Use custom should_continue_editor for iteration limits and error handling
    workflow.add_conditional_edges(
        "call_model",
        should_continue_editor,
        {
            "tools": "tools",
            "error_handler": "error_handler",
            END: END,
        }
    )

    workflow.add_edge("tools", "call_model")
    workflow.add_edge("error_handler", END)

    if checkpointer is None:
        logger.warning(
            "No checkpointer provided, using in-memory MemorySaver. "
            "This is NOT suitable for production - use Redis or PostgreSQL checkpointer."
        )
        checkpointer = MemorySaver()

    return workflow.compile(checkpointer=checkpointer)


# =============================================================================
# Editor Agent Class (High-level API)
# =============================================================================


class EditorAgentGraph:
    """
    High-level API for the editor agent using LangGraph.

    Provides backward-compatible interface with the original EditorAgent.

    Features:
    - Streaming responses with astream_events
    - Session persistence via checkpointer
    - Graph visualization with get_graph_diagram()
    - State history with get_state_history()
    """

    def __init__(
        self,
        model_deployment: str | None = None,
        checkpointer=None,
    ):
        """Initialize the editor agent."""
        self.model_deployment = model_deployment or os.getenv(
            "AZURE_OPENAI_DEPLOYMENT_GPT", "gpt-4o"
        )
        self.checkpointer = checkpointer
        self._graph = None

    @property
    def graph(self) -> StateGraph:
        """Get or create the compiled graph."""
        if self._graph is None:
            self._graph = create_editor_agent_graph(self.checkpointer)
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
        project_id: str | None = None,
        media_id: str | None = None,
        chat_history: list[dict] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Run the editor agent on a user message.

        Args:
            message: User's message
            project_id: Editor project ID
            media_id: Source video ID (can be inferred from project)
            chat_history: Previous conversation messages
            user_id: User identifier
            session_id: Session identifier

        Returns:
            Dict with 'response', 'project_context', 'clips_updated'
        """
        # Get project context
        project_context = get_project_context(project_id)

        # Use media_id from project if not provided
        if not media_id and project_context:
            media_id = project_context.get("source_media_id")

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
            project_id=project_id,
            project_context=project_context,
            user_id=user_id,
            session_id=session_id,
        )

        # Build config
        config = RunnableConfig(
            configurable={
                "thread_id": session_id or "default",
                "media_id": media_id,
                "project_id": project_id,
                "model_deployment": self.model_deployment,
            }
        )

        logger.info(f"Editor agent starting - project_id={project_id}")

        try:
            result = await self.graph.ainvoke(state, config)

            # Get updated context
            updated_context = get_project_context(project_id)

            # Extract response
            final_message = result["messages"][-1]
            response = final_message.content if hasattr(final_message, "content") else str(final_message)

            # Count tool calls
            tool_calls = sum(
                1 for msg in result["messages"]
                if isinstance(msg, AIMessage) and msg.tool_calls
            )

            # Check if clips changed
            initial_count = project_context.get("clips_count", 0) if project_context else 0
            updated_count = updated_context.get("clips_count", 0) if updated_context else 0

            return {
                "response": response,
                "project_context": updated_context,
                "clips_updated": updated_count != initial_count,
                "tool_calls_made": tool_calls,
            }

        except Exception as e:
            logger.error(f"Editor agent error: {e}")
            return {
                "response": f"I encountered an error: {str(e)}",
                "project_context": project_context,
                "clips_updated": False,
                "tool_calls_made": 0,
            }

    async def run_stream(
        self,
        message: str,
        project_id: str | None = None,
        media_id: str | None = None,
        chat_history: list[dict] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Run the editor agent with streaming responses.

        Yields events compatible with the original format.
        """
        # Get project context
        project_context = get_project_context(project_id)

        if not media_id and project_context:
            media_id = project_context.get("source_media_id")

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
            project_id=project_id,
            project_context=project_context,
            user_id=user_id,
            session_id=session_id,
        )

        # Build config
        config = RunnableConfig(
            configurable={
                "thread_id": session_id or "default",
                "media_id": media_id,
                "project_id": project_id,
                "model_deployment": self.model_deployment,
            }
        )

        logger.info(f"Editor agent stream starting - project_id={project_id}")

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
                    yield {
                        "event": "tool_start",
                        "data": {"tool": tool_name, "tool_call_id": event.get("run_id", "")},
                    }

                elif event_type == "on_tool_end":
                    tool_name = event["name"]
                    output = event["data"].get("output", {})
                    tool_calls_made += 1

                    yield {
                        "event": "tool_end",
                        "data": {
                            "tool": tool_name,
                            "tool_call_id": event.get("run_id", ""),
                            "success": not output.get("error") if isinstance(output, dict) else True,
                            "result_summary": self._summarize_result(tool_name, output),
                        },
                    }

                    # Emit clips_updated for editor tools
                    if tool_name in DESTRUCTIVE_TOOLS:
                        updated_context = get_project_context(project_id)
                        if updated_context:
                            yield {
                                "event": "clips_updated",
                                "data": {
                                    "clips_count": updated_context.get("clips_count", 0),
                                    "clips": updated_context.get("clips", []),
                                },
                            }

                elif event_type == "on_chain_end" and event["name"] == "LangGraph":
                    final_output = event["data"].get("output", {})
                    final_messages = final_output.get("messages", [])

                    if final_messages:
                        last_msg = final_messages[-1]
                        final_response = last_msg.content if hasattr(last_msg, "content") else collected_response
                    else:
                        final_response = collected_response

                    updated_context = get_project_context(project_id)

                    yield {
                        "event": "done",
                        "data": {
                            "response": final_response,
                            "project_context": updated_context,
                            "tool_calls_made": tool_calls_made,
                        },
                    }

        except Exception as e:
            logger.error(f"Editor agent stream error: {e}")
            yield {"event": "error", "data": {"error": str(e)}}

    def _summarize_result(self, tool_name: str, result: dict) -> str:
        """Create brief summary of tool result."""
        if isinstance(result, dict):
            if result.get("error"):
                return f"Error: {result['error']}"
            if result.get("message"):
                return result["message"]
            if result.get("success"):
                return "Success"
        return "Completed"

    async def get_state_history(
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

    async def confirm_and_continue(
        self,
        session_id: str,
        confirmed: bool = True,
    ) -> dict[str, Any]:
        """
        Continue execution after an interrupt (human-in-the-loop).

        Used when interrupt_before_clips is enabled.

        Args:
            session_id: The session/thread ID
            confirmed: Whether to proceed with the pending tool call

        Returns:
            Agent response after continuation
        """
        config = RunnableConfig(configurable={"thread_id": session_id})

        if not confirmed:
            # Cancel by updating state to remove pending tool calls
            await self.graph.aupdate_state(config, {"messages": []})
            return {"response": "Operation cancelled.", "clips_updated": False}

        # Continue execution
        result = await self.graph.ainvoke(None, config)

        final_message = result["messages"][-1]
        response = final_message.content if hasattr(final_message, "content") else ""

        return {
            "response": response,
            "project_context": get_project_context(config.get("configurable", {}).get("project_id")),
            "clips_updated": True,
        }


# =============================================================================
# Factory Functions
# =============================================================================

_editor_graph_instance: EditorAgentGraph | None = None


def get_editor_agent_graph(checkpointer=None) -> EditorAgentGraph:
    """Get or create the editor agent graph singleton."""
    global _editor_graph_instance
    if _editor_graph_instance is None:
        _editor_graph_instance = EditorAgentGraph(checkpointer=checkpointer)
    return _editor_graph_instance
