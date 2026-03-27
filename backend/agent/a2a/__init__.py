"""
A2A Agent Protocol Package
==========================

Bridges LangGraph agents with the A2A (Agent-to-Agent) protocol.
Handles task lifecycle, streaming, and artifact generation.

This package wraps the existing VideoAgentGraph
to expose it as an A2A-compliant server.

Reference: https://a2a-protocol.org/latest/specification/
"""

from agent.a2a.executor import A2AAgentExecutor
from agent.a2a.factories import get_video_a2a_executor
from agent.a2a.task_store import (
    PersistentTaskStore,
    TaskStore,
    get_task_store,
)

__all__ = [
    "A2AAgentExecutor",
    "PersistentTaskStore",
    "TaskStore",
    "get_task_store",
    "get_video_a2a_executor",
]
