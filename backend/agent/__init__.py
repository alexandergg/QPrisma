"""
QPrisma Video Agent
===================

LangGraph-based agentic system for intelligent video chat and editing.
Uses Azure OpenAI with LangGraph StateGraph for declarative agent orchestration.

Architecture (LangGraph):
    START → call_model → has_tool_calls? → tools → call_model → ... → END
                              ↓ no
                            END

Key Components:
- AgentState: LangGraph typed state with Annotated message reducer
- VideoAgentGraph: Main video agent using LangGraph StateGraph
- EditorAgentGraph: Editor agent for Chat-to-Edit functionality
- Tools: LangGraph @tool decorated functions
- Memory: Redis checkpointer for conversation persistence

Legacy Components (deprecated, use LangGraph versions):
- VideoAgent: Original manual ReAct implementation
- EditorAgent: Original editor implementation
- VideoAgentState: Original state definition
"""

# LangGraph implementations (recommended)
# Legacy implementations (for backward compatibility)
from agent.editor_agent import EditorAgent, get_editor_agent
from agent.editor_agent_graph import EditorAgentGraph, get_editor_agent_graph
from agent.graph_state import AgentState, create_agent_state, get_message_trimmer
from agent.state import VideoAgentState
from agent.video_agent import VideoAgent, get_video_agent
from agent.video_agent_graph import (
    VideoAgentGraph,
    create_redis_checkpointer,
    get_video_agent_graph,
)

__all__ = [
    # LangGraph (recommended)
    "VideoAgentGraph",
    "EditorAgentGraph",
    "AgentState",
    "create_agent_state",
    "get_video_agent_graph",
    "get_editor_agent_graph",
    "create_redis_checkpointer",
    "get_message_trimmer",
    # Legacy (backward compatibility)
    "VideoAgent",
    "EditorAgent",
    "VideoAgentState",
    "get_video_agent",
    "get_editor_agent",
]
