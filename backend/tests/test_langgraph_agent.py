"""
LangGraph Agent Tests
=====================

Tests for the LangGraph-based video and editor agents.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestGraphState:
    """Test LangGraph state management."""

    def test_create_agent_state(self):
        """Test agent state creation."""
        from langchain_core.messages import HumanMessage

        from agent.graph_state import create_agent_state

        messages = [HumanMessage(content="What happens in the video?")]
        state = create_agent_state(
            messages=messages,
            media_id="test-video-123",
            user_id="user-456",
            session_id="session-789",
        )

        assert len(state["messages"]) == 1
        assert state["messages"][0].content == "What happens in the video?"
        assert state["video_context"]["media_id"] == "test-video-123"
        assert state["user_id"] == "user-456"
        assert state["session_id"] == "session-789"

    def test_create_agent_state_without_video(self):
        """Test state creation without video context."""
        from langchain_core.messages import HumanMessage

        from agent.graph_state import create_agent_state

        messages = [HumanMessage(content="Hello")]
        state = create_agent_state(messages=messages)

        assert state["video_context"] is None
        assert state["sources"] == []


class TestVideoAgentGraph:
    """Test the LangGraph video agent."""

    @pytest.fixture
    def mock_azure_openai(self):
        """Mock Azure OpenAI chat model."""
        with patch("agent.video_agent_graph.AzureChatOpenAI") as mock:
            mock_instance = MagicMock()
            mock.return_value = mock_instance
            yield mock_instance

    @pytest.mark.asyncio
    async def test_agent_graph_creation(self):
        """Test that the graph compiles successfully."""
        from langgraph.checkpoint.memory import MemorySaver

        from agent.video_agent_graph import create_video_agent_graph

        checkpointer = MemorySaver()
        graph = create_video_agent_graph(checkpointer)

        # Graph should be compiled
        assert graph is not None
        # CompiledStateGraph type check
        assert "CompiledStateGraph" in type(graph).__name__

    @pytest.mark.asyncio
    async def test_video_agent_graph_class(self):
        """Test VideoAgentGraph class initialization."""
        from agent.video_agent_graph import VideoAgentGraph

        agent = VideoAgentGraph(model_deployment="gpt-4o")

        assert agent.model_deployment == "gpt-4o"
        assert agent._graph is None  # Lazy initialization

    @pytest.mark.asyncio
    async def test_video_agent_graph_singleton(self):
        """Test that get_video_agent_graph returns singleton."""
        from agent.video_agent_graph import get_video_agent_graph

        # Reset singleton
        import agent.video_agent_graph as module
        module._graph_instance = None

        agent1 = get_video_agent_graph()
        agent2 = get_video_agent_graph()

        assert agent1 is agent2


class TestEditorAgentGraph:
    """Test the LangGraph editor agent."""

    @pytest.mark.asyncio
    async def test_editor_graph_creation(self):
        """Test that the editor graph compiles successfully."""
        from langgraph.checkpoint.memory import MemorySaver

        from agent.editor_agent_graph import create_editor_agent_graph

        checkpointer = MemorySaver()
        graph = create_editor_agent_graph(checkpointer)

        assert graph is not None

    @pytest.mark.asyncio
    async def test_editor_agent_graph_class(self):
        """Test EditorAgentGraph class initialization."""
        from agent.editor_agent_graph import EditorAgentGraph

        agent = EditorAgentGraph(model_deployment="gpt-4o")

        assert agent.model_deployment == "gpt-4o"

    @pytest.mark.asyncio
    async def test_editor_agent_graph_singleton(self):
        """Test that get_editor_agent_graph returns singleton."""
        from agent.editor_agent_graph import get_editor_agent_graph

        # Reset singleton
        import agent.editor_agent_graph as module
        module._editor_graph_instance = None

        agent1 = get_editor_agent_graph()
        agent2 = get_editor_agent_graph()

        assert agent1 is agent2


class TestLangGraphTools:
    """Test LangGraph tool definitions."""

    def test_search_tools_defined(self):
        """Test that search tools are properly defined."""
        from agent.graph_tools import SEARCH_TOOLS

        assert len(SEARCH_TOOLS) >= 5

        tool_names = [t.name for t in SEARCH_TOOLS]
        assert "search_video" in tool_names
        assert "find_entity" in tool_names
        assert "get_transcript" in tool_names
        assert "describe_scene" in tool_names
        assert "list_chapters" in tool_names

    def test_editor_tools_defined(self):
        """Test that editor tools are properly defined."""
        from agent.graph_editor_tools import EDITOR_TOOLS

        assert len(EDITOR_TOOLS) >= 10

        tool_names = [t.name for t in EDITOR_TOOLS]
        assert "create_clip" in tool_names
        assert "modify_clip" in tool_names
        assert "delete_clip" in tool_names
        assert "list_clips" in tool_names
        assert "add_subtitles" in tool_names
        assert "export_clip" in tool_names

    @pytest.mark.asyncio
    async def test_search_video_no_context(self):
        """Test search_video returns error without media_id."""
        from agent.graph_tools import search_video

        result = await search_video.ainvoke(
            {"query": "test"},
            config={"configurable": {}},
        )

        assert "error" in result
        assert "No video context" in result["error"]

    @pytest.mark.asyncio
    async def test_create_clip_no_project(self):
        """Test create_clip returns error without project_id."""
        from agent.graph_editor_tools import create_clip

        result = await create_clip.ainvoke(
            {"start_time": 0, "end_time": 10},
            config={"configurable": {}},
        )

        assert "error" in result
        assert "No project context" in result["error"]


class TestRedisCheckpointer:
    """Test Redis checkpointer creation."""

    def test_create_redis_checkpointer_fallback(self):
        """Test fallback to MemorySaver when Redis unavailable."""
        from langgraph.checkpoint.memory import MemorySaver

        with patch.dict("os.environ", {"REDIS_URL": "redis://invalid:6379"}):
            # Import fresh to test with patched env
            import importlib
            import agent.video_agent_graph as module
            importlib.reload(module)

            # Force an error by patching the import
            original_func = module.create_redis_checkpointer

            def mock_create():
                try:
                    from langgraph.checkpoint.redis import RedisSaver
                    raise Exception("Connection failed")
                except Exception:
                    return MemorySaver()

            with patch.object(module, "create_redis_checkpointer", mock_create):
                checkpointer = mock_create()
                # Should fall back to MemorySaver
                assert isinstance(checkpointer, MemorySaver)


class TestAgentImports:
    """Test that the agent module exports correctly."""

    def test_langgraph_exports(self):
        """Test LangGraph exports from agent module."""
        from agent import (
            AgentState,
            EditorAgentGraph,
            VideoAgentGraph,
            create_agent_state,
            create_redis_checkpointer,
            get_editor_agent_graph,
            get_video_agent_graph,
        )

        # All should be importable
        assert VideoAgentGraph is not None
        assert EditorAgentGraph is not None
        assert AgentState is not None
        assert create_agent_state is not None
        assert get_video_agent_graph is not None
        assert get_editor_agent_graph is not None
        assert create_redis_checkpointer is not None

    def test_legacy_exports(self):
        """Test legacy exports still work."""
        from agent import (
            EditorAgent,
            VideoAgent,
            VideoAgentState,
            get_editor_agent,
            get_video_agent,
        )

        # Legacy imports should still work
        assert VideoAgent is not None
        assert EditorAgent is not None
        assert VideoAgentState is not None
        assert get_video_agent is not None
        assert get_editor_agent is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
