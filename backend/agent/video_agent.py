"""
Video Agent
===========

Main agent class implementing a ReAct-style loop for video understanding.
Inspired by LangGraph's StateGraph pattern but using Azure OpenAI function calling.

Architecture:
    START → call_model → (has_tool_calls?) → execute_tools → call_model → ... → END
                ↓ no
              END

The agent:
1. Receives user message + video context
2. Calls LLM with available tools
3. If LLM requests tool calls, executes them
4. Repeats until LLM provides final response or max iterations reached
"""

import json
import logging
import os
from collections.abc import AsyncGenerator
from typing import Any

from openai import AzureOpenAI

# Token limits for context management
MAX_CONTEXT_TOKENS = 100000  # Leave headroom below 128k limit
MAX_TOOL_RESULT_CHARS = 8000  # ~2000 tokens per tool result
MAX_TOOL_RESULT_TOKENS = 2000
CHARS_PER_TOKEN = 4  # Rough estimate for token counting

from agent.prompts import NO_VIDEO_CONTEXT_PROMPT, SYSTEM_PROMPT
from agent.state import (
    AgentConfig,
    VideoAgentState,
    create_initial_state,
)
from agent.tools import ALL_TOOLS, TOOL_DEFINITIONS

logger = logging.getLogger(__name__)


def estimate_tokens(text: str | None) -> int:
    """Estimate token count from text. Rough estimate: ~4 chars per token."""
    if not text:
        return 0
    return len(text) // CHARS_PER_TOKEN


def truncate_tool_result(result: Any, max_chars: int = MAX_TOOL_RESULT_CHARS) -> str:
    """
    Truncate tool result to prevent context overflow.
    
    Preserves structure while limiting size:
    - For search results: keep first N results
    - For transcripts: truncate text
    - For descriptions: truncate content
    """
    result_str = json.dumps(result, default=str)
    
    if len(result_str) <= max_chars:
        return result_str
    
    # Try to intelligently truncate based on content type
    if isinstance(result, dict):
        # Handle search results
        if "results" in result and isinstance(result["results"], list):
            truncated = result.copy()
            results = result["results"]
            # Keep reducing results until we fit
            while len(results) > 1:
                results = results[:len(results) // 2 + 1]
                truncated["results"] = results
                truncated["_truncated"] = True
                truncated["_original_count"] = len(result["results"])
                result_str = json.dumps(truncated, default=str)
                if len(result_str) <= max_chars:
                    break
            return result_str[:max_chars]
        
        # Handle transcripts
        if "full_transcript" in result:
            truncated = result.copy()
            transcript = result["full_transcript"]
            if len(transcript) > max_chars // 2:
                truncated["full_transcript"] = transcript[:max_chars // 2] + "... [truncated]"
                truncated["_truncated"] = True
            # Also truncate segments
            if "segments" in truncated and len(truncated["segments"]) > 10:
                truncated["segments"] = truncated["segments"][:10]
                truncated["_segments_truncated"] = True
            result_str = json.dumps(truncated, default=str)
            return result_str[:max_chars]
        
        # Handle scene descriptions
        if "frames" in result and isinstance(result["frames"], list):
            truncated = result.copy()
            truncated["frames"] = result["frames"][:5]
            truncated["_truncated"] = True
            result_str = json.dumps(truncated, default=str)
            return result_str[:max_chars]
    
    # Fallback: simple truncation
    return result_str[:max_chars] + '..."}'


def estimate_messages_tokens(messages: list[dict]) -> int:
    """Estimate total tokens in message list."""
    total = 0
    for msg in messages:
        # Role and structure overhead
        total += 10
        if msg.get("content"):
            total += estimate_tokens(msg["content"])
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                total += estimate_tokens(json.dumps(tc, default=str))
    return total


# Event types for streaming
class StreamEvent:
    """Event types for agent streaming."""

    THINKING = "thinking"  # Agent is processing
    TOOL_START = "tool_start"  # Starting a tool call
    TOOL_END = "tool_end"  # Tool call completed
    TOKEN = "token"  # Streaming token
    SOURCES = "sources"  # Sources found
    DONE = "done"  # Final response complete
    ERROR = "error"  # Error occurred


class VideoAgent:
    """
    Intelligent video agent with tool calling capabilities.

    Implements a ReAct-style loop:
    - Reason: LLM analyzes the request and decides what to do
    - Act: Execute tools to gather information
    - Repeat until response is ready
    """

    def __init__(
        self,
        client: AzureOpenAI | None = None,
        config: AgentConfig | None = None,
    ):
        """
        Initialize the video agent.

        Args:
            client: Azure OpenAI client (created if not provided)
            config: Agent configuration
        """
        self.client = client or self._create_client()
        self.config = config or AgentConfig()

        # Set model deployment from env if not specified
        if self.config.model_deployment is None:
            self.config.model_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_GPT", "gpt-4o")

        # Build tool lookup
        self.tools = {tool.name: tool for tool in ALL_TOOLS}
        self.tool_definitions = TOOL_DEFINITIONS

    def _create_client(self) -> AzureOpenAI:
        """Create Azure OpenAI client from environment."""
        return AzureOpenAI(
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        )

    # =========================================================================
    # Main Entry Point
    # =========================================================================

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
            session_id: Session identifier

        Returns:
            Dict with 'response', 'sources', and 'tool_calls_made'
        """
        # Create initial state
        state = create_initial_state(
            message=message,
            media_id=media_id,
            chat_history=chat_history,
            user_id=user_id,
            session_id=session_id,
        )

        logger.info(f"Agent starting - media_id={media_id}, message={message[:50]}...")

        # Run the agent loop
        state = await self._run_loop(state)

        return {
            "response": state.get("final_response", "I couldn't generate a response."),
            "sources": state.get("sources", []),
            "tool_calls_made": state.get("iteration_count", 0),
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

        Yields events as the agent processes:
        - thinking: Agent is processing
        - tool_start: Starting a tool call
        - tool_end: Tool call completed with results
        - token: Streaming response token
        - sources: Sources found
        - done: Final response complete
        - error: Error occurred
        """
        # Create initial state
        state = create_initial_state(
            message=message,
            media_id=media_id,
            chat_history=chat_history,
            user_id=user_id,
            session_id=session_id,
        )

        logger.info(f"Agent stream starting - media_id={media_id}")

        try:
            # Run the streaming loop
            async for event in self._run_loop_stream(state):
                yield event
        except Exception as e:
            logger.error(f"Agent stream error: {e}")
            yield {
                "event": StreamEvent.ERROR,
                "data": {"error": str(e)},
            }

    async def _run_loop_stream(
        self, state: VideoAgentState
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Streaming version of the agent loop.
        """
        max_iterations = state.get("max_iterations", self.config.max_iterations)
        sources = []

        while state.get("should_continue", True):
            iteration = state.get("iteration_count", 0)

            if iteration >= max_iterations:
                logger.warning(f"Max iterations ({max_iterations}) reached")
                yield {
                    "event": StreamEvent.DONE,
                    "data": {
                        "response": self._build_fallback_response(state),
                        "sources": sources,
                        "tool_calls_made": iteration,
                    },
                }
                return

            # Check if we have pending tool calls from previous iteration
            pending_calls = state.get("pending_tool_calls", [])

            if pending_calls:
                # Execute tools with streaming events
                for tool_call in pending_calls:
                    func_name = tool_call["function"]["name"]

                    # Emit tool start
                    yield {
                        "event": StreamEvent.TOOL_START,
                        "data": {
                            "tool": func_name,
                            "tool_call_id": tool_call["id"],
                        },
                    }

                    # Execute the tool
                    try:
                        func_args = json.loads(tool_call["function"]["arguments"])
                    except json.JSONDecodeError:
                        func_args = {}

                    tool = self.tools.get(func_name)
                    media_id = state.get("video_context", {}).get("media_id") if state.get("video_context") else None

                    if tool:
                        result = await tool(media_id=media_id, **func_args)

                        # Add tool message to conversation with truncation
                        truncated_content = truncate_tool_result(result)
                        state["messages"].append({
                            "role": "tool",
                            "content": truncated_content,
                            "tool_call_id": tool_call["id"],
                            "name": func_name,
                        })

                        # Extract sources from search results
                        if func_name == "search_video" and isinstance(result, dict):
                            for r in result.get("results", []):
                                sources.append({
                                    "timestamp": r.get("timestamp", 0),
                                    "type": r.get("type", "unknown"),
                                    "description": r.get("content", "")[:100],
                                    "score": r.get("score", 0),
                                })

                        # Emit tool end
                        yield {
                            "event": StreamEvent.TOOL_END,
                            "data": {
                                "tool": func_name,
                                "tool_call_id": tool_call["id"],
                                "success": not result.get("error") if isinstance(result, dict) else True,
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
                            "event": StreamEvent.TOOL_END,
                            "data": {
                                "tool": func_name,
                                "tool_call_id": tool_call["id"],
                                "success": False,
                                "error": f"Unknown tool: {func_name}",
                            },
                        }

                state["pending_tool_calls"] = []
                state["iteration_count"] = iteration + 1

            # Call the model with streaming
            yield {"event": StreamEvent.THINKING, "data": {"iteration": iteration}}

            async for event in self._call_model_stream(state):
                if event["event"] == "tool_calls":
                    # Model requested tool calls
                    state["pending_tool_calls"] = event["data"]["tool_calls"]
                    state["messages"].append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": event["data"]["tool_calls"],
                    })
                elif event["event"] == StreamEvent.TOKEN:
                    yield event
                elif event["event"] == "response_complete":
                    # Final response
                    state["should_continue"] = False
                    state["messages"].append({
                        "role": "assistant",
                        "content": event["data"]["content"],
                    })

                    # Emit sources if any
                    if sources:
                        yield {
                            "event": StreamEvent.SOURCES,
                            "data": {"sources": sources},
                        }

                    yield {
                        "event": StreamEvent.DONE,
                        "data": {
                            "response": event["data"]["content"],
                            "sources": sources,
                            "tool_calls_made": state.get("iteration_count", 0),
                        },
                    }
                    return

    async def _call_model_stream(
        self, state: VideoAgentState
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Call the LLM with streaming response.
        """
        messages = self._build_messages(state)
        media_id = state.get("video_context", {}).get("media_id") if state.get("video_context") else None

        try:
            # Prepare completion parameters
            completion_params = {
                "model": self.config.model_deployment,
                "messages": messages,
                "stream": True,
            }

            # Add tools only if we have video context
            if media_id:
                completion_params["tools"] = self.tool_definitions
                completion_params["tool_choice"] = "auto"

            # Handle model-specific parameters
            if "gpt-5" in self.config.model_deployment.lower():
                completion_params["max_completion_tokens"] = self.config.max_tokens
            else:
                completion_params["temperature"] = self.config.temperature
                completion_params["max_tokens"] = self.config.max_tokens

            # Make the streaming API call
            stream = self.client.chat.completions.create(**completion_params)

            collected_content = ""
            tool_calls_data = {}  # Accumulate tool calls

            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None

                if delta is None:
                    continue

                # Handle tool calls
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

                # Handle content
                if delta.content:
                    collected_content += delta.content
                    yield {
                        "event": StreamEvent.TOKEN,
                        "data": {"token": delta.content},
                    }

                # Check finish reason
                if chunk.choices[0].finish_reason:
                    if chunk.choices[0].finish_reason == "tool_calls":
                        # Return tool calls
                        yield {
                            "event": "tool_calls",
                            "data": {
                                "tool_calls": list(tool_calls_data.values()),
                            },
                        }
                    else:
                        # Response complete
                        yield {
                            "event": "response_complete",
                            "data": {"content": collected_content},
                        }

        except Exception as e:
            logger.error(f"Model stream error: {e}")
            yield {
                "event": StreamEvent.ERROR,
                "data": {"error": str(e)},
            }

    # =========================================================================
    # Agent Loop (ReAct Pattern) - Non-streaming version
    # =========================================================================

    async def _run_loop(self, state: VideoAgentState) -> VideoAgentState:
        """
        Main agent loop.

        Continues until:
        - LLM provides a response without tool calls
        - Max iterations reached
        - Error occurs
        """
        max_iterations = state.get("max_iterations", self.config.max_iterations)

        while state.get("should_continue", True):
            iteration = state.get("iteration_count", 0)

            if iteration >= max_iterations:
                logger.warning(f"Max iterations ({max_iterations}) reached")
                state["final_response"] = self._build_fallback_response(state)
                state["should_continue"] = False
                break

            # Step 1: Call the model
            state = await self._call_model(state)

            # Step 2: Check if we have tool calls
            pending_calls = state.get("pending_tool_calls", [])

            if pending_calls:
                # Execute tools
                state = await self._execute_tools(state)
                state["iteration_count"] = iteration + 1
            else:
                # No tool calls = we have a final response
                state["should_continue"] = False

        return state

    async def _call_model(self, state: VideoAgentState) -> VideoAgentState:
        """
        Call the LLM to get next action or final response.
        """
        messages = self._build_messages(state)
        media_id = state.get("video_context", {}).get("media_id") if state.get("video_context") else None

        try:
            # Prepare completion parameters
            completion_params = {
                "model": self.config.model_deployment,
                "messages": messages,
            }

            # Add tools only if we have video context
            if media_id:
                completion_params["tools"] = self.tool_definitions
                completion_params["tool_choice"] = "auto"

            # Handle model-specific parameters
            if "gpt-5" in self.config.model_deployment.lower():
                completion_params["max_completion_tokens"] = self.config.max_tokens
            else:
                completion_params["temperature"] = self.config.temperature
                completion_params["max_tokens"] = self.config.max_tokens

            # Make the API call
            response = self.client.chat.completions.create(**completion_params)
            assistant_message = response.choices[0].message

            # Check for tool calls
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

                # Add assistant message with tool calls to history
                state["messages"].append({
                    "role": "assistant",
                    "content": assistant_message.content,
                    "tool_calls": tool_calls,
                })

                logger.info(f"LLM requested {len(tool_calls)} tool calls: {[tc['function']['name'] for tc in tool_calls]}")

            else:
                # Final response
                state["final_response"] = assistant_message.content
                state["pending_tool_calls"] = []

                # Add to message history
                state["messages"].append({
                    "role": "assistant",
                    "content": assistant_message.content,
                })

                logger.info("LLM provided final response")

        except Exception as e:
            logger.error(f"Model call failed: {e}")
            state["final_response"] = f"I encountered an error: {str(e)}"
            state["should_continue"] = False

        return state

    async def _execute_tools(self, state: VideoAgentState) -> VideoAgentState:
        """
        Execute pending tool calls and add results to state.
        Results are truncated to prevent context overflow.
        """
        pending_calls = state.get("pending_tool_calls", [])
        media_id = state.get("video_context", {}).get("media_id") if state.get("video_context") else None

        tool_results = []
        sources = state.get("sources", [])

        for tool_call in pending_calls:
            func_name = tool_call["function"]["name"]
            func_args_str = tool_call["function"]["arguments"]

            try:
                func_args = json.loads(func_args_str)
            except json.JSONDecodeError:
                func_args = {}

            # Get the tool
            tool = self.tools.get(func_name)

            if tool:
                # Execute the tool
                result = await tool(media_id=media_id, **func_args)

                tool_results.append({
                    "tool_call_id": tool_call["id"],
                    "tool_name": func_name,
                    "result": result,
                    "error": result.get("error") if isinstance(result, dict) else None,
                })

                # Extract sources from search results
                if func_name == "search_video" and isinstance(result, dict):
                    for r in result.get("results", []):
                        sources.append({
                            "timestamp": r.get("timestamp", 0),
                            "type": r.get("type", "unknown"),
                            "description": r.get("content", "")[:100],
                            "score": r.get("score", 0),
                        })

                # Add tool message to conversation with truncation to prevent overflow
                truncated_content = truncate_tool_result(result)
                state["messages"].append({
                    "role": "tool",
                    "content": truncated_content,
                    "tool_call_id": tool_call["id"],
                    "name": func_name,
                })

                logger.info(f"Tool {func_name} executed successfully (result size: {len(truncated_content)} chars)")

            else:
                logger.warning(f"Unknown tool requested: {func_name}")
                state["messages"].append({
                    "role": "tool",
                    "content": json.dumps({"error": f"Unknown tool: {func_name}"}),
                    "tool_call_id": tool_call["id"],
                    "name": func_name,
                })

        # Update state
        state["tool_results"] = tool_results
        state["pending_tool_calls"] = []
        state["sources"] = sources

        return state

    # =========================================================================
    # Message Building
    # =========================================================================

    def _build_messages(self, state: VideoAgentState) -> list[dict]:
        """
        Build messages array for the LLM call with context limit management.
        
        Ensures total context stays under MAX_CONTEXT_TOKENS by:
        1. Truncating tool results
        2. Limiting conversation history
        3. Prioritizing recent messages
        """
        messages = []

        # System prompt
        video_context = state.get("video_context")
        if video_context and video_context.get("media_id"):
            system_content = SYSTEM_PROMPT
            # Add video context to system prompt
            if video_context.get("title"):
                system_content += f"\n\nCurrent video: {video_context.get('title')}"
            if video_context.get("duration"):
                system_content += f" (Duration: {video_context.get('duration')}s)"
        else:
            system_content = NO_VIDEO_CONTEXT_PROMPT

        messages.append({"role": "system", "content": system_content})
        system_tokens = estimate_tokens(system_content)
        
        # Calculate available tokens for conversation (leave room for response)
        available_tokens = MAX_CONTEXT_TOKENS - system_tokens - 2000  # 2k for response

        # Build conversation messages with truncation
        conversation_messages = []
        for msg in state.get("messages", []):
            formatted_msg = {"role": msg["role"]}

            if msg.get("content") is not None:
                content = msg["content"]
                # Truncate tool results that are too large
                if msg["role"] == "tool" and len(content) > MAX_TOOL_RESULT_CHARS:
                    try:
                        # Try to parse and intelligently truncate
                        result_data = json.loads(content)
                        content = truncate_tool_result(result_data)
                    except (json.JSONDecodeError, TypeError):
                        content = content[:MAX_TOOL_RESULT_CHARS] + "... [truncated]"
                formatted_msg["content"] = content

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

            conversation_messages.append(formatted_msg)

        # Check if we need to trim conversation history
        total_conv_tokens = estimate_messages_tokens(conversation_messages)
        
        if total_conv_tokens > available_tokens:
            logger.warning(
                f"Context too large ({total_conv_tokens} tokens). "
                f"Trimming to fit {available_tokens} tokens."
            )
            # Keep first user message and most recent messages
            if len(conversation_messages) > 2:
                # Keep first message (initial user query) and trim from the middle
                first_msg = conversation_messages[0]
                # Calculate how many recent messages we can keep
                remaining_tokens = available_tokens - estimate_messages_tokens([first_msg])
                
                # Add messages from the end until we run out of space
                trimmed_messages = [first_msg]
                recent_messages = []
                
                for msg in reversed(conversation_messages[1:]):
                    msg_tokens = estimate_messages_tokens([msg])
                    if remaining_tokens >= msg_tokens:
                        recent_messages.insert(0, msg)
                        remaining_tokens -= msg_tokens
                    else:
                        break
                
                if recent_messages:
                    # Add a marker that context was trimmed
                    trimmed_messages.append({
                        "role": "system",
                        "content": "[Previous conversation truncated to fit context limit. Continuing with recent context.]"
                    })
                    trimmed_messages.extend(recent_messages)
                
                conversation_messages = trimmed_messages
                logger.info(f"Trimmed to {len(conversation_messages)} messages")

        messages.extend(conversation_messages)
        return messages

    def _build_fallback_response(self, state: VideoAgentState) -> str:
        """
        Build a fallback response when max iterations reached.
        """
        tool_results = state.get("tool_results", [])

        if tool_results:
            # Summarize what we found
            summary_parts = ["Based on my analysis:"]
            for result in tool_results:
                if not result.get("error"):
                    summary_parts.append(f"- Used {result['tool_name']}")

            return " ".join(summary_parts) + "\n\nI gathered some information but couldn't complete the full analysis. Please try asking a more specific question."

        return "I couldn't complete the analysis. Please try rephrasing your question."


# Factory function for dependency injection
_agent_instance: VideoAgent | None = None


def get_video_agent() -> VideoAgent:
    """Get or create the video agent singleton."""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = VideoAgent()
    return _agent_instance
