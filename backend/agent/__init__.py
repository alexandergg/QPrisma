"""
QPrisma Video Agent
===================

LangGraph-based agentic system for intelligent video chat.
Uses Azure OpenAI with LangGraph StateGraph for declarative agent orchestration.

Architecture (LangGraph v1.0+):
    START -> call_model -> has_tool_calls? -> tools -> update_context -> call_model -> ... -> END
                              | no                         ^ error_handler (graceful degradation)
                             END

Key Components:
- AgentState: LangGraph typed state with Annotated message reducer
- AgentInputState/AgentOutputState: Input/Output schema separation (hides internal state)
- VideoAgentGraph: Main video agent using LangGraph StateGraph
- Tools: LangGraph @tool decorated functions with dynamic binding
- Memory: In-process LangGraph checkpointer with Foundry-managed hosted history
- Error Handling: Graceful degradation with error_handler node

Best Practices Applied (LangGraph v1.0+):
1. Input/Output Schema Separation - Clean API boundaries
2. Error Handler Node - Graceful degradation
3. interrupt() for HITL - Granular tool confirmation
4. Per-Exception Retry Policies - Smart retries
5. Multi-Tenant Security - user_id scoping
6. Graph Execution Tests - Full path coverage
7. Dynamic Tool Binding - Focused tool subsets
8. Shared Checkpointer Factory - Process-local runtime state
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS: dict[str, str] = {
    # Agent classes
    "VideoAgentGraph": "agent.graphs.video",
    # State types
    "AgentState": "agent.state.agent_state",
    "AgentInputState": "agent.state.agent_state",
    "AgentOutputState": "agent.state.agent_state",
    # Factory functions
    "create_agent_state": "agent.state.agent_state",
    "get_video_agent_graph": "agent.graphs.video",
    # Checkpointer
    "get_shared_checkpointer": "agent.graphs.video",
    # Retry policies
    "create_smart_retry_policy": "agent.graphs.video",
    "should_retry_exception": "agent.state.agent_state",
    "RetryableError": "agent.state.agent_state",
    "NonRetryableError": "agent.state.agent_state",
    # Utilities
    "get_message_trimmer": "agent.state.agent_state",
    "error_handler_node": "agent.nodes.base",
    "select_tools_for_query": "agent.nodes.base",
}

__all__ = [
    # Agent classes
    "VideoAgentGraph",
    # State types
    "AgentState",
    "AgentInputState",
    "AgentOutputState",
    # Factory functions
    "create_agent_state",
    "get_video_agent_graph",
    # Checkpointer
    "get_shared_checkpointer",
    # Retry policies
    "create_smart_retry_policy",
    "should_retry_exception",
    "RetryableError",
    "NonRetryableError",
    # Utilities
    "get_message_trimmer",
    "error_handler_node",
    "select_tools_for_query",
]


def __getattr__(name: str) -> Any:
    """Resolve package-level convenience exports without eager dependency imports."""
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted([*globals(), *__all__])
