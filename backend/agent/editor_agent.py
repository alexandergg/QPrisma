"""
Editor Agent
=============

Specialized agent for video editing through natural conversation (Chat-to-Edit).
Extends the base VideoAgent with editor-specific tools and context.
"""

import json
import logging
import os
from collections.abc import AsyncGenerator
from typing import Any

from openai import AzureOpenAI

from agent.prompts import EDITOR_NO_PROJECT_PROMPT, build_editor_prompt
from agent.state import AgentConfig, VideoAgentState, create_initial_state
from agent.tools import EDITOR_TOOLS, SEARCH_TOOLS
from agent.tools.base import format_timestamp
from services.database_service import get_database_service

logger = logging.getLogger(__name__)


class EditorAgentConfig(AgentConfig):
    """Configuration for the editor agent."""

    # Editor-specific settings
    default_subtitle_style: str = "hormozi"
    auto_confirm_clips: bool = False  # If True, create clips without confirmation
    max_auto_clips: int = 10


class EditorAgent:
    """
    AI agent for video editing through natural conversation.

    Features:
    - Create, modify, delete clips via chat
    - AI-powered clip suggestions with viral scores
    - Subtitle management with popular styles
    - Integrated search from VideoRAG

    The agent maintains context about:
    - Current project and its clips
    - Source video information
    - User preferences
    """

    def __init__(
        self,
        client: AzureOpenAI | None = None,
        config: EditorAgentConfig | None = None,
    ):
        """Initialize the editor agent."""
        self.client = client or self._create_client()
        self.config = config or EditorAgentConfig()

        if self.config.model_deployment is None:
            self.config.model_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_GPT", "gpt-4o")

        # Combine search and editor tools
        all_tools = SEARCH_TOOLS + EDITOR_TOOLS
        self.tools = {tool.name: tool for tool in all_tools}
        self.tool_definitions = [tool.definition for tool in all_tools]

    def _create_client(self) -> AzureOpenAI:
        """Create Azure OpenAI client from environment."""
        return AzureOpenAI(
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        )

    # =========================================================================
    # Context Building
    # =========================================================================

    def _get_project_context(self, project_id: str | None) -> dict[str, Any]:
        """Get current project context for the agent."""
        if not project_id:
            return {}

        db = get_database_service()
        project = db.get_project_with_clips(project_id)

        if not project:
            return {}

        # Get source video info
        media = db.get_media(project.source_media_id)
        video_duration = 0
        video_title = "Unknown"

        if media:
            video_title = media.original_filename or media.blob_name
            if media.video_metadata:
                video_duration = media.video_metadata.get("duration", 0)

        # Build clips list
        clips = project.clips or []
        total_clips_duration = sum(c.end_time - c.start_time for c in clips)

        clips_list = ""
        for i, clip in enumerate(clips):
            subtitle_info = f" [📝 {clip.subtitle_style}]" if clip.subtitles_enabled else ""
            viral_info = f" ⭐{int(clip.viral_score)}" if clip.viral_score else ""
            # Include clip ID for agent to use with modify_clip tool
            clips_list += f"{i + 1}. [{format_timestamp(clip.start_time)} - {format_timestamp(clip.end_time)}] {clip.title or 'Untitled'}{viral_info}{subtitle_info} (id: {clip.id})\n"

        return {
            "project_id": project.id,
            "project_name": project.name,
            "source_media_id": project.source_media_id,
            "video_title": video_title,
            "video_duration": video_duration,
            "video_duration_formatted": format_timestamp(video_duration),
            "clips_count": len(clips),
            "total_clips_duration": total_clips_duration,
            "total_clips_duration_formatted": format_timestamp(total_clips_duration),
            "clips_list": clips_list,
            "clips": [
                {
                    "id": c.id,
                    "order": c.order,
                    "start_time": c.start_time,
                    "end_time": c.end_time,
                    "title": c.title,
                    "subtitle_style": c.subtitle_style if c.subtitles_enabled else None,
                }
                for c in clips
            ],
        }

    def _build_system_prompt(self, project_context: dict[str, Any]) -> str:
        """Build the system prompt with current project context."""
        if not project_context:
            return EDITOR_NO_PROJECT_PROMPT

        return build_editor_prompt(
            project_name=project_context.get("project_name", "Unnamed Project"),
            video_title=project_context.get("video_title", "Unknown"),
            video_duration=project_context.get("video_duration_formatted", "0:00"),
            clips_count=project_context.get("clips_count", 0),
            total_clips_duration=project_context.get("total_clips_duration_formatted", "0:00"),
            clips_list=project_context.get("clips_list", ""),
        )

    # =========================================================================
    # Main Entry Points
    # =========================================================================

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
            Dict with 'response', 'clips_updated', 'project_context'
        """
        # Get project context
        project_context = self._get_project_context(project_id)

        # Use media_id from project if not provided
        if not media_id and project_context:
            media_id = project_context.get("source_media_id")

        # Create initial state
        state = create_initial_state(
            message=message,
            media_id=media_id,
            chat_history=chat_history,
            user_id=user_id,
            session_id=session_id,
        )

        # Add editor-specific context
        state["project_context"] = project_context
        state["project_id"] = project_id

        logger.info(f"Editor agent starting - project_id={project_id}, message={message[:50]}...")

        # Run the agent loop
        state = await self._run_loop(state)

        # Get updated project context
        updated_context = self._get_project_context(project_id) if project_id else {}

        return {
            "response": state.get("final_response", "I couldn't generate a response."),
            "project_context": updated_context,
            "clips_updated": updated_context.get("clips_count", 0) != project_context.get("clips_count", 0),
            "tool_calls_made": state.get("iteration_count", 0),
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

        Yields events as the agent processes:
        - thinking: Agent is processing
        - tool_start: Starting a tool call
        - tool_end: Tool call completed
        - token: Streaming response token
        - clips_updated: Clips were modified
        - done: Final response complete
        - error: Error occurred
        """
        # Get project context
        project_context = self._get_project_context(project_id)

        if not media_id and project_context:
            media_id = project_context.get("source_media_id")

        # Create initial state
        state = create_initial_state(
            message=message,
            media_id=media_id,
            chat_history=chat_history,
            user_id=user_id,
            session_id=session_id,
        )

        state["project_context"] = project_context
        state["project_id"] = project_id

        logger.info(f"Editor agent stream starting - project_id={project_id}")

        try:
            async for event in self._run_loop_stream(state):
                yield event

                # Check if clips were updated after tool calls
                if event.get("event") == "tool_end":
                    tool_name = event.get("data", {}).get("tool")
                    if tool_name in ["create_clip", "modify_clip", "delete_clip",
                                     "reorder_clips", "add_suggested_clips",
                                     "add_subtitles", "change_subtitle_style", "remove_subtitles"]:
                        # Emit clips updated event
                        updated_context = self._get_project_context(project_id)
                        yield {
                            "event": "clips_updated",
                            "data": {
                                "clips_count": updated_context.get("clips_count", 0),
                                "clips": updated_context.get("clips", []),
                            },
                        }

        except Exception as e:
            logger.error(f"Editor agent stream error: {e}")
            yield {
                "event": "error",
                "data": {"error": str(e)},
            }

    # =========================================================================
    # Agent Loop
    # =========================================================================

    async def _run_loop(self, state: VideoAgentState) -> VideoAgentState:
        """Main agent loop."""
        max_iterations = state.get("max_iterations", self.config.max_iterations)

        while state.get("should_continue", True):
            iteration = state.get("iteration_count", 0)

            if iteration >= max_iterations:
                logger.warning(f"Max iterations ({max_iterations}) reached")
                state["final_response"] = self._build_fallback_response(state)
                state["should_continue"] = False
                break

            # Call the model
            state = await self._call_model(state)

            # Check for tool calls
            pending_calls = state.get("pending_tool_calls", [])

            if pending_calls:
                state = await self._execute_tools(state)
                state["iteration_count"] = iteration + 1
            else:
                state["should_continue"] = False

        return state

    async def _run_loop_stream(
        self, state: VideoAgentState
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Streaming version of the agent loop."""
        max_iterations = state.get("max_iterations", self.config.max_iterations)

        while state.get("should_continue", True):
            iteration = state.get("iteration_count", 0)

            if iteration >= max_iterations:
                logger.warning(f"Max iterations ({max_iterations}) reached")
                yield {
                    "event": "done",
                    "data": {
                        "response": self._build_fallback_response(state),
                        "tool_calls_made": iteration,
                    },
                }
                return

            pending_calls = state.get("pending_tool_calls", [])

            if pending_calls:
                # Execute tools
                for tool_call in pending_calls:
                    func_name = tool_call["function"]["name"]

                    yield {
                        "event": "tool_start",
                        "data": {
                            "tool": func_name,
                            "tool_call_id": tool_call["id"],
                        },
                    }

                    try:
                        func_args = json.loads(tool_call["function"]["arguments"])
                    except json.JSONDecodeError:
                        func_args = {}

                    tool = self.tools.get(func_name)
                    media_id = state.get("video_context", {}).get("media_id") if state.get("video_context") else None
                    project_id = state.get("project_id")

                    if tool:
                        # Pass project_id to editor tools
                        if func_name in ["create_clip", "list_clips", "reorder_clips",
                                         "generate_auto_clips", "add_suggested_clips"]:
                            func_args["project_id"] = project_id

                        result = await tool(media_id=media_id, **func_args)

                        state["messages"].append({
                            "role": "tool",
                            "content": json.dumps(result, default=str),
                            "tool_call_id": tool_call["id"],
                            "name": func_name,
                        })

                        yield {
                            "event": "tool_end",
                            "data": {
                                "tool": func_name,
                                "tool_call_id": tool_call["id"],
                                "success": not result.get("error") if isinstance(result, dict) else True,
                                "result_summary": self._summarize_tool_result(func_name, result),
                            },
                        }
                    else:
                        state["messages"].append({
                            "role": "tool",
                            "content": json.dumps({"error": f"Unknown tool: {func_name}"}),
                            "tool_call_id": tool_call["id"],
                            "name": func_name,
                        })

                        yield {
                            "event": "tool_end",
                            "data": {
                                "tool": func_name,
                                "tool_call_id": tool_call["id"],
                                "success": False,
                            },
                        }

                state["pending_tool_calls"] = []
                state["iteration_count"] = iteration + 1

            # Call the model
            yield {"event": "thinking", "data": {"iteration": iteration}}

            async for event in self._call_model_stream(state):
                if event["event"] == "tool_calls":
                    state["pending_tool_calls"] = event["data"]["tool_calls"]
                    state["messages"].append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": event["data"]["tool_calls"],
                    })
                elif event["event"] == "token":
                    yield event
                elif event["event"] == "response_complete":
                    state["should_continue"] = False
                    state["messages"].append({
                        "role": "assistant",
                        "content": event["data"]["content"],
                    })

                    # Get final project context
                    project_id = state.get("project_id")
                    final_context = self._get_project_context(project_id) if project_id else {}

                    yield {
                        "event": "done",
                        "data": {
                            "response": event["data"]["content"],
                            "project_context": final_context,
                            "tool_calls_made": state.get("iteration_count", 0),
                        },
                    }
                    return

    def _summarize_tool_result(self, tool_name: str, result: dict) -> str:
        """Create a brief summary of tool result for UI."""
        if isinstance(result, dict):
            if result.get("error"):
                return f"Error: {result['error']}"
            if result.get("message"):
                return result["message"]
            if result.get("success"):
                return "Success"
        return "Completed"

    # =========================================================================
    # Model Calling
    # =========================================================================

    async def _call_model(self, state: VideoAgentState) -> VideoAgentState:
        """Call the LLM."""
        messages = self._build_messages(state)

        try:
            completion_params = {
                "model": self.config.model_deployment,
                "messages": messages,
                "tools": self.tool_definitions,
                "tool_choice": "auto",
            }

            if "gpt-5" in self.config.model_deployment.lower():
                completion_params["max_completion_tokens"] = self.config.max_tokens
            else:
                completion_params["temperature"] = self.config.temperature
                completion_params["max_tokens"] = self.config.max_tokens

            response = self.client.chat.completions.create(**completion_params)
            assistant_message = response.choices[0].message

            if assistant_message.tool_calls:
                tool_calls = []
                for tc in assistant_message.tool_calls:
                    tool_calls.append({
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    })

                state["pending_tool_calls"] = tool_calls
                state["messages"].append({
                    "role": "assistant",
                    "content": assistant_message.content,
                    "tool_calls": tool_calls,
                })
            else:
                state["final_response"] = assistant_message.content
                state["pending_tool_calls"] = []
                state["messages"].append({
                    "role": "assistant",
                    "content": assistant_message.content,
                })

        except Exception as e:
            logger.error(f"Model call failed: {e}")
            state["final_response"] = f"I encountered an error: {str(e)}"
            state["should_continue"] = False

        return state

    async def _call_model_stream(
        self, state: VideoAgentState
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Call the LLM with streaming."""
        messages = self._build_messages(state)

        try:
            completion_params = {
                "model": self.config.model_deployment,
                "messages": messages,
                "tools": self.tool_definitions,
                "tool_choice": "auto",
                "stream": True,
            }

            if "gpt-5" in self.config.model_deployment.lower():
                completion_params["max_completion_tokens"] = self.config.max_tokens
            else:
                completion_params["temperature"] = self.config.temperature
                completion_params["max_tokens"] = self.config.max_tokens

            stream = self.client.chat.completions.create(**completion_params)

            collected_content = ""
            tool_calls_data = {}

            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None

                if delta is None:
                    continue

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_data:
                            tool_calls_data[idx] = {
                                "id": "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }

                        if tc.id:
                            tool_calls_data[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_calls_data[idx]["function"]["name"] = tc.function.name
                            if tc.function.arguments:
                                tool_calls_data[idx]["function"]["arguments"] += tc.function.arguments

                if delta.content:
                    collected_content += delta.content
                    yield {
                        "event": "token",
                        "data": {"token": delta.content},
                    }

                if chunk.choices[0].finish_reason:
                    if chunk.choices[0].finish_reason == "tool_calls":
                        yield {
                            "event": "tool_calls",
                            "data": {
                                "tool_calls": list(tool_calls_data.values()),
                            },
                        }
                    else:
                        yield {
                            "event": "response_complete",
                            "data": {"content": collected_content},
                        }

        except Exception as e:
            logger.error(f"Model stream error: {e}")
            yield {
                "event": "error",
                "data": {"error": str(e)},
            }

    async def _execute_tools(self, state: VideoAgentState) -> VideoAgentState:
        """Execute pending tool calls."""
        pending_calls = state.get("pending_tool_calls", [])
        media_id = state.get("video_context", {}).get("media_id") if state.get("video_context") else None
        project_id = state.get("project_id")

        for tool_call in pending_calls:
            func_name = tool_call["function"]["name"]

            try:
                func_args = json.loads(tool_call["function"]["arguments"])
            except json.JSONDecodeError:
                func_args = {}

            tool = self.tools.get(func_name)

            if tool:
                # Pass project_id to editor tools
                if func_name in ["create_clip", "list_clips", "reorder_clips",
                                 "generate_auto_clips", "add_suggested_clips"]:
                    func_args["project_id"] = project_id

                result = await tool(media_id=media_id, **func_args)

                state["messages"].append({
                    "role": "tool",
                    "content": json.dumps(result, default=str),
                    "tool_call_id": tool_call["id"],
                    "name": func_name,
                })
            else:
                state["messages"].append({
                    "role": "tool",
                    "content": json.dumps({"error": f"Unknown tool: {func_name}"}),
                    "tool_call_id": tool_call["id"],
                    "name": func_name,
                })

        state["pending_tool_calls"] = []
        return state

    # =========================================================================
    # Message Building
    # =========================================================================

    def _build_messages(self, state: VideoAgentState) -> list[dict]:
        """Build messages array for the LLM call."""
        messages = []

        # System prompt with project context
        project_context = state.get("project_context", {})
        system_content = self._build_system_prompt(project_context)
        messages.append({"role": "system", "content": system_content})

        # Conversation history
        for msg in state.get("messages", []):
            formatted_msg = {"role": msg["role"]}

            if msg.get("content") is not None:
                formatted_msg["content"] = msg["content"]

            if msg.get("tool_calls"):
                formatted_msg["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": tc["type"],
                        "function": tc["function"],
                    }
                    for tc in msg["tool_calls"]
                ]

            if msg.get("tool_call_id"):
                formatted_msg["tool_call_id"] = msg["tool_call_id"]

            if msg.get("name"):
                formatted_msg["name"] = msg["name"]

            messages.append(formatted_msg)

        return messages

    def _build_fallback_response(self, state: VideoAgentState) -> str:
        """Build fallback response when max iterations reached."""
        return "I've been working on your request but couldn't complete it. Please try a simpler command or break it into steps."


# Factory function
_editor_agent_instance: EditorAgent | None = None


def get_editor_agent() -> EditorAgent:
    """Get or create the editor agent singleton."""
    global _editor_agent_instance
    if _editor_agent_instance is None:
        _editor_agent_instance = EditorAgent()
    return _editor_agent_instance
