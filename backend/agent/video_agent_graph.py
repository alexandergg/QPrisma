"""
LangGraph Video Agent
=====================

Video agent implemented using LangGraph StateGraph pattern.
Provides a declarative, composable agent with built-in streaming and checkpointing.

Architecture:
    START → call_model → tools_condition? → tools → call_model → ... → END
                              ↓ no
                            END

Best Practices Applied:
- Uses prebuilt tools_condition for routing
- Uses ToolNode with handle_tool_errors for graceful error handling
- Uses START constant for modern entry point
- Supports graph visualization with get_graph()
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

from agent.graph_state import AgentState, create_agent_state, get_message_trimmer
from agent.graph_tools import SEARCH_TOOLS
from agent.prompts import NO_VIDEO_CONTEXT_PROMPT, SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# Message trimmer to prevent context overflow
_message_trimmer = get_message_trimmer(max_tokens=8000)


# =============================================================================
# Graph Nodes
# =============================================================================


def create_model(model_deployment: str | None = None) -> AzureChatOpenAI:
    """Create Azure OpenAI chat model."""
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


def get_system_message(state: AgentState) -> SystemMessage:
    """Build system message based on video context."""
    video_context = state.get("video_context")

    if video_context and video_context.get("media_id"):
        content = SYSTEM_PROMPT
        if video_context.get("title"):
            content += f"\n\nCurrent video: {video_context.get('title')}"
        if video_context.get("duration"):
            content += f" (Duration: {video_context.get('duration')}s)"
    else:
        content = NO_VIDEO_CONTEXT_PROMPT

    return SystemMessage(content=content)


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

    # Bind tools only if we have video context
    video_context = state.get("video_context")
    if video_context and video_context.get("media_id"):
        model = model.bind_tools(SEARCH_TOOLS)

    # Build messages with system prompt
    system_msg = get_system_message(state)

    # Apply message trimming to prevent context overflow
    trimmed_messages = _message_trimmer.invoke(list(state["messages"]))
    messages = [system_msg] + trimmed_messages

    # Invoke model
    response = await model.ainvoke(messages, config)

    return {"messages": [response]}


# =============================================================================
# Graph Builder
# =============================================================================


def create_video_agent_graph(checkpointer=None):
    """
    Create the video agent graph.

    Args:
        checkpointer: LangGraph checkpointer for persistence

    Returns a compiled StateGraph with:
    - call_model: Invokes LLM
    - tools: Executes tool calls with error handling
    - Conditional routing using tools_condition
    """
    # Create graph
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("call_model", call_model)
    # Use ToolNode with handle_tool_errors for graceful error handling
    workflow.add_node("tools", ToolNode(SEARCH_TOOLS, handle_tool_errors=True))

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
            Dict with 'response', 'sources', and 'tool_calls_made'
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

            # Count tool calls
            tool_calls = sum(
                1 for msg in result["messages"]
                if isinstance(msg, AIMessage) and msg.tool_calls
            )

            return {
                "response": response,
                "sources": result.get("sources", []),
                "tool_calls_made": tool_calls,
            }

        except Exception as e:
            logger.error(f"Agent error: {e}")
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

        Yields events compatible with the original StreamEvent format:
        - thinking: Agent is processing
        - tool_start: Starting a tool call
        - tool_end: Tool call completed
        - token: Streaming response token
        - sources: Sources found
        - done: Final response complete
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
                    yield {
                        "event": "tool_start",
                        "data": {"tool": tool_name, "tool_call_id": event.get("run_id", "")},
                    }

                elif event_type == "on_tool_end":
                    tool_name = event["name"]
                    output = event["data"].get("output", {})
                    tool_calls_made += 1

                    # Extract sources from search results
                    if tool_name == "search_video" and isinstance(output, dict):
                        for r in output.get("results", []):
                            sources.append({
                                "timestamp": r.get("timestamp", 0),
                                "type": r.get("type", "unknown"),
                                "description": r.get("content", "")[:100],
                                "score": r.get("score", 0),
                            })

                    yield {
                        "event": "tool_end",
                        "data": {
                            "tool": tool_name,
                            "tool_call_id": event.get("run_id", ""),
                            "success": not output.get("error") if isinstance(output, dict) else True,
                        },
                    }

                elif event_type == "on_chain_end" and event["name"] == "LangGraph":
                    # Final result
                    if sources:
                        yield {"event": "sources", "data": {"sources": sources}}

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
                            "sources": sources,
                            "tool_calls_made": tool_calls_made,
                        },
                    }

        except Exception as e:
            logger.error(f"Agent stream error: {e}")
            yield {"event": "error", "data": {"error": str(e)}}

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

    async def resume_from_checkpoint(
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
    """Create Redis checkpointer from environment."""
    try:
        from langgraph.checkpoint.redis import RedisSaver

        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        return RedisSaver.from_conn_string(redis_url)
    except Exception as e:
        logger.warning(f"Failed to create Redis checkpointer: {e}. Using memory saver.")
        return MemorySaver()
