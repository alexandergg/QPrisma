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
- Memory: Production checkpointer factory (PostgreSQL > Redis > Memory)
- Error Handling: Graceful degradation with error_handler node

Best Practices Applied (LangGraph v1.0+):
1. Input/Output Schema Separation - Clean API boundaries
2. Error Handler Node - Graceful degradation
3. interrupt() for HITL - Granular tool confirmation
4. Per-Exception Retry Policies - Smart retries
5. Multi-Tenant Security - user_id scoping
6. Graph Execution Tests - Full path coverage
7. Dynamic Tool Binding - Focused tool subsets
8. Production Checkpointer Factory - Cascade fallback
"""

# LangGraph implementations (recommended)
from agent.graphs.video import (
    VideoAgentGraph,
    create_smart_retry_policy,
    get_shared_checkpointer,
    get_video_agent_graph,
)
from agent.nodes.base import (
    error_handler_node,
    select_tools_for_query,
)
from agent.state.agent_state import (
    AgentInputState,
    AgentOutputState,
    AgentState,
    NonRetryableError,
    RetryableError,
    create_agent_state,
    get_message_trimmer,
    should_retry_exception,
)

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
