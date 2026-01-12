"""
Video Agent Tests
=================

Tests for the agentic chat system.
"""

import asyncio
import json
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestToolDefinitions:
    """Test tool schema definitions."""

    def test_all_tools_loaded(self):
        """Verify all tools are loaded."""
        from agent.tools import ALL_TOOLS

        assert len(ALL_TOOLS) == 9

        tool_names = [t.name for t in ALL_TOOLS]
        assert "search_video" in tool_names
        assert "get_transcript" in tool_names
        assert "list_chapters" in tool_names

    def test_tool_definitions_valid_schema(self):
        """Verify tool definitions have valid OpenAI schema."""
        from agent.tools import TOOL_DEFINITIONS

        for tool_def in TOOL_DEFINITIONS:
            assert tool_def["type"] == "function"
            assert "function" in tool_def
            func = tool_def["function"]
            assert "name" in func
            assert "description" in func
            assert "parameters" in func
            assert func["parameters"]["type"] == "object"


class TestAgentState:
    """Test agent state management."""

    def test_create_initial_state(self):
        """Test initial state creation."""
        from agent.state import create_initial_state

        state = create_initial_state(
            message="What happens in the video?",
            media_id="test-video-123",
        )

        assert state["messages"][-1]["role"] == "user"
        assert state["messages"][-1]["content"] == "What happens in the video?"
        assert state["video_context"]["media_id"] == "test-video-123"
        assert state["should_continue"] is True
        assert state["iteration_count"] == 0

    def test_create_initial_state_with_history(self):
        """Test initial state with chat history."""
        from agent.state import create_initial_state

        history = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
        ]

        state = create_initial_state(
            message="Tell me more",
            media_id="test-video",
            chat_history=history,
        )

        # History + new message
        assert len(state["messages"]) == 3
        assert state["messages"][0]["content"] == "Hi"
        assert state["messages"][2]["content"] == "Tell me more"


class TestVideoAgent:
    """Test the main video agent."""

    @pytest.fixture
    def mock_openai_client(self):
        """Create a mock OpenAI client."""
        client = MagicMock()

        # Mock a simple response without tool calls
        mock_response = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "Based on my analysis, the video shows..."
        mock_message.tool_calls = None
        mock_response.choices = [MagicMock(message=mock_message)]

        client.chat.completions.create.return_value = mock_response
        return client

    @pytest.fixture
    def mock_openai_with_tools(self):
        """Create a mock that returns tool calls."""
        client = MagicMock()

        # First call: returns tool calls
        tool_call = MagicMock()
        tool_call.id = "call_123"
        tool_call.function.name = "search_video"
        tool_call.function.arguments = json.dumps({"query": "introduction"})

        mock_message1 = MagicMock()
        mock_message1.content = None
        mock_message1.tool_calls = [tool_call]

        # Second call: returns final response
        mock_message2 = MagicMock()
        mock_message2.content = "I found the introduction at 0:30."
        mock_message2.tool_calls = None

        mock_response1 = MagicMock()
        mock_response1.choices = [MagicMock(message=mock_message1)]

        mock_response2 = MagicMock()
        mock_response2.choices = [MagicMock(message=mock_message2)]

        client.chat.completions.create.side_effect = [mock_response1, mock_response2]
        return client

    @pytest.mark.asyncio
    async def test_agent_simple_response(self, mock_openai_client):
        """Test agent with simple response (no tools)."""
        from agent.video_agent import VideoAgent

        agent = VideoAgent(client=mock_openai_client)

        result = await agent.run(
            message="What is this video about?",
            media_id=None,  # No video context
        )

        assert "response" in result
        assert result["tool_calls_made"] == 0

    @pytest.mark.asyncio
    async def test_agent_with_tool_calls(self, mock_openai_with_tools):
        """Test agent that uses tools."""
        from agent.video_agent import VideoAgent

        # Mock the search tool
        with patch("agent.tools.search_tools.SearchVideoTool.execute") as mock_search:
            mock_search.return_value = {
                "query": "introduction",
                "results": [
                    {
                        "timestamp": 30,
                        "type": "visual",
                        "content": "Introduction slide",
                        "score": 0.95,
                    }
                ],
                "total_found": 1,
            }

            agent = VideoAgent(client=mock_openai_with_tools)

            result = await agent.run(
                message="Find the introduction",
                media_id="test-video-123",
            )

            assert "response" in result
            assert result["tool_calls_made"] >= 1

    @pytest.mark.asyncio
    async def test_agent_max_iterations(self, mock_openai_client):
        """Test that agent respects max iterations."""
        from agent.video_agent import VideoAgent
        from agent.state import AgentConfig

        # Configure for few iterations
        config = AgentConfig(max_iterations=2)
        agent = VideoAgent(client=mock_openai_client, config=config)

        # Should complete without infinite loop
        result = await agent.run(
            message="Test message",
            media_id="test-video",
        )

        assert "response" in result


class TestAgentTools:
    """Test individual tools."""

    @pytest.mark.asyncio
    async def test_search_video_no_context(self):
        """Test search tool without video context."""
        from agent.tools.search_tools import search_video

        result = await search_video(
            media_id=None,
            query="test query",
        )

        assert "error" in result
        assert "No video context" in result["error"]

    @pytest.mark.asyncio
    async def test_get_transcript_no_context(self):
        """Test transcript tool without video context."""
        from agent.tools.navigation_tools import get_transcript

        result = await get_transcript(
            media_id=None,
            start_time=0,
            end_time=60,
        )

        assert "error" in result

    @pytest.mark.asyncio
    async def test_list_chapters_no_context(self):
        """Test chapters tool without video context."""
        from agent.tools.structure_tools import list_chapters

        result = await list_chapters(media_id=None)

        assert "error" in result


class TestAgentMemory:
    """Test agent memory with Redis."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        with patch("agent.memory.redis") as mock:
            mock_client = MagicMock()
            mock.from_url.return_value = mock_client
            yield mock_client

    def test_create_session(self, mock_redis):
        """Test session creation."""
        from agent.memory import AgentMemory

        memory = AgentMemory()
        memory._client = mock_redis

        session = memory.create_session(
            session_id="test-session-123",
            user_id="user-456",
            media_id="video-789",
        )

        assert session["session_id"] == "test-session-123"
        mock_redis.hset.assert_called()
        mock_redis.expire.assert_called()

    def test_add_message(self, mock_redis):
        """Test adding messages to history."""
        from agent.memory import AgentMemory

        memory = AgentMemory()
        memory._client = mock_redis

        memory.add_message(
            session_id="test-session",
            role="user",
            content="Hello!",
        )

        mock_redis.rpush.assert_called()
        mock_redis.ltrim.assert_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
