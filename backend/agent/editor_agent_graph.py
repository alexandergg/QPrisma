"""
LangGraph Editor Agent
======================

Specialized agent for video editing through natural conversation (Chat-to-Edit).
Extends the video agent with editor-specific tools and context.

Features:
- Human-in-the-loop: Uses interrupt_before for clip confirmation
- tools_condition: Modern LangGraph conditional routing
- handle_tool_errors: Graceful error handling for tools
- Graph visualization: get_graph_diagram() method
"""

import logging
import os
from collections.abc import AsyncGenerator
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import AzureChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from agent.graph_editor_tools import EDITOR_TOOLS
from agent.graph_state import AgentState, ProjectContext, create_agent_state, get_message_trimmer
from agent.graph_tools import SEARCH_TOOLS
from agent.prompts import EDITOR_NO_PROJECT_PROMPT, build_editor_prompt
from agent.tools.base import format_timestamp

logger = logging.getLogger(__name__)

# Message trimmer to prevent context overflow
_message_trimmer = get_message_trimmer(max_tokens=8000)

# Tools that modify clips (for human-in-the-loop support)
CLIP_MODIFICATION_TOOLS = {
    "create_clip", "modify_clip", "delete_clip", "reorder_clips",
    "add_suggested_clips", "add_subtitles", "change_subtitle_style", "remove_subtitles",
}


# =============================================================================
# Context Building
# =============================================================================


def get_project_context(project_id: str | None) -> ProjectContext | None:
    """Get current project context for the agent."""
    if not project_id:
        return None

    try:
        from services.database_service import get_database_service

        db = get_database_service()
        project = db.get_project_with_clips(project_id)

        if not project:
            return None

        # Get source video info
        media = db.get_media(project.source_media_id)
        video_duration = 0
        video_title = "Unknown"

        if media:
            video_title = media.original_filename or media.blob_name
            if media.video_metadata:
                video_duration = media.video_metadata.get("duration", 0)

        clips = project.clips or []

        return ProjectContext(
            project_id=project.id,
            project_name=project.name,
            source_media_id=project.source_media_id,
            video_title=video_title,
            video_duration=video_duration,
            clips_count=len(clips),
            clips=[
                {
                    "id": c.id,
                    "order": c.order,
                    "start_time": c.start_time,
                    "end_time": c.end_time,
                    "title": c.title,
                    "subtitle_style": c.subtitle_style if c.subtitles_enabled else None,
                    "viral_score": c.viral_score,
                }
                for c in clips
            ],
        )

    except Exception as e:
        logger.error(f"Failed to get project context: {e}")
        return None


def build_editor_system_message(project_context: ProjectContext | None) -> SystemMessage:
    """Build editor system message with project context."""
    if not project_context:
        return SystemMessage(content=EDITOR_NO_PROJECT_PROMPT)

    # Build clips list string
    clips_list = ""
    for i, clip in enumerate(project_context.get("clips", [])):
        subtitle_info = f" [📝 {clip.get('subtitle_style')}]" if clip.get("subtitle_style") else ""
        viral_info = f" ⭐{int(clip.get('viral_score', 0))}" if clip.get("viral_score") else ""
        clips_list += (
            f"{i + 1}. [{format_timestamp(clip['start_time'])} - {format_timestamp(clip['end_time'])}] "
            f"{clip.get('title') or 'Untitled'}{viral_info}{subtitle_info} (id: {clip['id']})\n"
        )

    total_duration = sum(
        c["end_time"] - c["start_time"] for c in project_context.get("clips", [])
    )

    content = build_editor_prompt(
        project_name=project_context.get("project_name", "Unnamed Project"),
        video_title=project_context.get("video_title", "Unknown"),
        video_duration=format_timestamp(project_context.get("video_duration", 0)),
        clips_count=project_context.get("clips_count", 0),
        total_clips_duration=format_timestamp(total_duration),
        clips_list=clips_list,
    )

    return SystemMessage(content=content)


# =============================================================================
# Graph Nodes
# =============================================================================


def create_editor_model(model_deployment: str | None = None) -> AzureChatOpenAI:
    """Create Azure OpenAI chat model for editor."""
    deployment = model_deployment or os.getenv("AZURE_OPENAI_DEPLOYMENT_GPT", "gpt-4o")

    return AzureChatOpenAI(
        azure_deployment=deployment,
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        temperature=0.7,
        max_tokens=1000,
        streaming=True,
    )


async def call_editor_model(state: AgentState, config: RunnableConfig) -> dict:
    """
    Call the LLM node for editor agent.

    Binds both search tools and editor tools.
    Uses message trimming to prevent context window overflow.
    """
    model_deployment = config.get("configurable", {}).get("model_deployment")
    model = create_editor_model(model_deployment)

    # Combine search and editor tools
    all_tools = SEARCH_TOOLS + EDITOR_TOOLS
    model = model.bind_tools(all_tools)

    # Build messages with editor system prompt
    project_context = state.get("project_context")
    system_msg = build_editor_system_message(project_context)

    # Apply message trimming to prevent context overflow
    trimmed_messages = _message_trimmer.invoke(list(state["messages"]))
    messages = [system_msg] + trimmed_messages

    # Invoke model
    response = await model.ainvoke(messages, config)

    return {"messages": [response]}


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
        interrupt_before_clips: If True, interrupt before clip modification tools
                               for human-in-the-loop confirmation

    Returns a compiled StateGraph with search and editor tools.
    """
    # Combine all tools
    all_tools = SEARCH_TOOLS + EDITOR_TOOLS

    # Create graph
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("call_model", call_editor_model)
    # Use ToolNode with handle_tool_errors for graceful error handling
    workflow.add_node("tools", ToolNode(all_tools, handle_tool_errors=True))

    # Use START constant for entry point (modern pattern)
    workflow.add_edge(START, "call_model")

    # Use tools_condition from prebuilt (cleaner than custom function)
    workflow.add_conditional_edges(
        "call_model",
        tools_condition,
    )

    # Tools always go back to model
    workflow.add_edge("tools", "call_model")

    # Compile with checkpointer
    if checkpointer is None:
        checkpointer = MemorySaver()

    # Optional: interrupt before clip modification for human confirmation
    interrupt_before = ["tools"] if interrupt_before_clips else None

    return workflow.compile(
        checkpointer=checkpointer,
        interrupt_before=interrupt_before,
    )


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
                    if tool_name in CLIP_MODIFICATION_TOOLS:
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
