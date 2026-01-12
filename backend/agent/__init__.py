"""
QPrisma Video Agent
===================

LangGraph-inspired agentic system for intelligent video chat.
Uses Azure OpenAI function calling with a ReAct-style loop.

Architecture:
    User Message → Agent (LLM) → Tool Calls → Tool Execution → Agent → Response
                        ↑                           ↓
                        └───────────────────────────┘

Key Components:
- VideoAgentState: Typed state with messages, video context, tool results
- VideoAgent: Main agent class with StateGraph-style execution
- Tools: search_video, get_transcript, describe_scene, list_chapters, etc.
- Memory: Redis-backed conversation persistence
"""

from agent.state import VideoAgentState
from agent.video_agent import VideoAgent

__all__ = ["VideoAgent", "VideoAgentState"]
