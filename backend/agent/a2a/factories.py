"""
A2A Factory Functions
=====================

Singleton factories for A2A agent executors.
"""

from agent.a2a.executor import A2AAgentExecutor

_video_executor: A2AAgentExecutor | None = None


def get_video_a2a_executor() -> A2AAgentExecutor:
    """Get the singleton video agent A2A executor."""
    global _video_executor
    if _video_executor is None:
        _video_executor = A2AAgentExecutor()
    return _video_executor
