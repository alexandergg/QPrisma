"""
LangGraph Agent Tests
=====================

Tests for the LangGraph-based video agent.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


class TestGraphState:
    """Test LangGraph state management."""

    def test_create_agent_state(self):
        """Test agent state creation."""
        from agent.state.agent_state import create_agent_state

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
        """Test state creation without video context.

        InjectedState keys are present but None/empty.
        """
        from agent.state.agent_state import create_agent_state

        messages = [HumanMessage(content="Hello")]
        state = create_agent_state(messages=messages)

        assert "video_context" not in state
        assert state["media_id"] is None
        assert state["media_ids"] == []
        assert state["user_id"] is None
        assert state["session_id"] is None
        assert state["sources"] == []

    def test_truncate_tool_message_content(self):
        """Test that large tool messages are truncated."""
        from agent.state.agent_state import MAX_TOOL_RESULT_CHARS, truncate_tool_message_content

        # Small message - should pass through unchanged
        small_msg = ToolMessage(content="short result", tool_call_id="tc-1", name="test")
        result = truncate_tool_message_content(small_msg)
        assert result.content == "short result"

        # Large message - should be truncated
        large_content = "x" * (MAX_TOOL_RESULT_CHARS + 1000)
        large_msg = ToolMessage(content=large_content, tool_call_id="tc-2", name="test")
        result = truncate_tool_message_content(large_msg)
        assert len(result.content) < len(large_content)
        assert "truncated" in result.content

        # Non-tool message - should pass through unchanged
        human_msg = HumanMessage(content="hello")
        result = truncate_tool_message_content(human_msg)
        assert result.content == "hello"


class TestRestoreMediaContext:
    """Test restore_media_context node for reliable media_id injection."""

    def test_overrides_none_state_with_config_media_id(self):
        """When state has no media_id but config does, state is updated."""
        from agent.nodes.video_nodes import restore_media_context
        from langchain_core.runnables import RunnableConfig

        state = {"media_id": None, "media_ids": None, "video_context": None}
        config = RunnableConfig(configurable={"media_id": "vid-123"})

        result = restore_media_context(state, config)

        assert result["media_id"] == "vid-123"
        assert result["video_context"]["media_id"] == "vid-123"

    def test_overrides_stale_media_id(self):
        """When state has a different media_id, config wins."""
        from agent.nodes.video_nodes import restore_media_context
        from langchain_core.runnables import RunnableConfig

        state = {
            "media_id": "old-vid",
            "media_ids": None,
            "video_context": {"media_id": "old-vid"},
        }
        config = RunnableConfig(configurable={"media_id": "new-vid"})

        result = restore_media_context(state, config)

        assert result["media_id"] == "new-vid"
        assert result["video_context"]["media_id"] == "new-vid"

    def test_no_op_when_ids_match(self):
        """When state and config agree, no video_context update is needed if present."""
        from agent.nodes.video_nodes import restore_media_context
        from langchain_core.runnables import RunnableConfig

        state = {
            "media_id": "vid-123",
            "media_ids": None,
            "video_context": {"media_id": "vid-123"},
        }
        config = RunnableConfig(configurable={"media_id": "vid-123"})

        result = restore_media_context(state, config)

        # No updates needed — state is already correct
        assert result == {}

    def test_creates_video_context_when_missing(self):
        """When state has correct media_id but no video_context, one is created."""
        from agent.nodes.video_nodes import restore_media_context
        from langchain_core.runnables import RunnableConfig

        state = {"media_id": "vid-123", "media_ids": None, "video_context": None}
        config = RunnableConfig(configurable={"media_id": "vid-123"})

        result = restore_media_context(state, config)

        assert "video_context" in result
        assert result["video_context"]["media_id"] == "vid-123"

    def test_no_config_no_state_media_id_returns_empty(self):
        """When neither config nor state has media_id, no updates are made."""
        from agent.nodes.video_nodes import restore_media_context
        from langchain_core.runnables import RunnableConfig

        state = {"media_id": None, "media_ids": None, "video_context": None}
        config = RunnableConfig(configurable={})

        result = restore_media_context(state, config)

        assert result == {}

    def test_falls_back_to_state_media_id_when_config_missing(self):
        """When config has no media_id but state has one (from checkpoint), preserve it."""
        from agent.nodes.video_nodes import restore_media_context
        from langchain_core.runnables import RunnableConfig

        # State has media_id from checkpoint, config doesn't (frontend didn't send it)
        state = {
            "media_id": "checkpointed-vid",
            "media_ids": None,
            "video_context": {"media_id": "checkpointed-vid"},
        }
        config = RunnableConfig(configurable={})

        result = restore_media_context(state, config)

        # State already has the right value — no updates needed
        assert result == {}

    def test_falls_back_to_state_and_creates_video_context(self):
        """When config has no media_id but state has one, create video_context if missing."""
        from agent.nodes.video_nodes import restore_media_context
        from langchain_core.runnables import RunnableConfig

        state = {
            "media_id": "checkpointed-vid",
            "media_ids": None,
            "video_context": None,  # Missing despite media_id being set
        }
        config = RunnableConfig(configurable={})

        result = restore_media_context(state, config)

        assert result["video_context"]["media_id"] == "checkpointed-vid"

    def test_restores_media_ids_from_config(self):
        """Config media_ids overrides stale state media_ids."""
        from agent.nodes.video_nodes import restore_media_context
        from langchain_core.runnables import RunnableConfig

        state = {
            "media_id": "vid-1",
            "media_ids": ["vid-1"],
            "video_context": {"media_id": "vid-1"},
        }
        config = RunnableConfig(configurable={"media_id": "vid-1", "media_ids": ["vid-1", "vid-2"]})

        result = restore_media_context(state, config)

        assert result["media_ids"] == ["vid-1", "vid-2"]

    def test_single_media_ids_message_restores_single_video_context(self):
        """Video-MME media_ids=[id] context should bind single-video tools."""
        from langchain_core.runnables import RunnableConfig

        from agent.nodes.video_nodes import restore_media_context

        state = {
            "messages": [
                HumanMessage(
                    content=(
                        '[QPRISMA_CONTEXT:{"media_ids":["vid-123"],"user_id":"u1"}]'
                        '[QPRISMA_BENCH:{"eval_mode":"mcq","format":"letter_only"}]\n'
                        "Question: What color?"
                    )
                )
            ],
            "media_id": None,
            "media_ids": None,
            "video_context": None,
            "user_id": None,
        }
        config = RunnableConfig(configurable={})

        result = restore_media_context(state, config)

        assert result["media_id"] == "vid-123"
        assert result["media_ids"] == ["vid-123"]
        assert result["video_context"]["media_id"] == "vid-123"
        assert result["user_id"] == "u1"
        assert result["benchmark_context"] == {
            "eval_mode": "mcq",
            "format": "letter_only",
        }
        assert result["messages"][0].content == "Question: What color?"

    def test_graph_has_restore_media_context_node(self):
        """The compiled graph includes restore_media_context before call_model."""
        from agent.graphs.video import create_video_agent_graph
        from langgraph.checkpoint.memory import MemorySaver

        graph = create_video_agent_graph(MemorySaver())
        node_names = list(graph.get_graph().nodes.keys())

        assert "restore_media_context" in node_names
        assert "call_model" in node_names

        # Verify restore_media_context is an entry point (reachable from __start__)
        mermaid = graph.get_graph().draw_mermaid()
        assert "restore_media_context" in mermaid


class TestCallModelConfigFallback:
    """Test that call_model recovers media_id from config when state has None."""

    @pytest.mark.asyncio
    async def test_call_model_recovers_media_id_from_config(self):
        """call_model should read media_id from config.configurable as fallback."""

        from agent.nodes.video_nodes import get_system_message

        # Simulate state where media_id was lost (e.g., checkpointer bug)
        state = {
            "messages": [HumanMessage(content="Tell me about this video")],
            "media_id": None,
            "media_ids": None,
            "video_context": None,
            "conversation_context": [],
        }

        # The NO_VIDEO_CONTEXT_PROMPT should be used
        system_msg = get_system_message(state)
        assert "no video loaded" in system_msg.content.lower()

        # Now with media_id in state, the SYSTEM_PROMPT should be used
        state["media_id"] = "vid-123"
        state["video_context"] = {"media_id": "vid-123"}
        system_msg = get_system_message(state)
        assert "no video loaded" not in system_msg.content.lower()

    """Test metadata extraction helpers."""

    def test_extract_metadata_from_tool_result_search(self):
        """Test extracting metadata from search results."""
        from agent.graphs.video import extract_metadata_from_tool_result

        tool_result = {
            "results": [
                {
                    "timestamp": 30.5,
                    "timestamp_formatted": "0:30",
                    "type": "visual",
                    "content": "A person speaking on stage",
                    "score": 0.95,
                }
            ],
        }

        meta = extract_metadata_from_tool_result(tool_result)
        assert len(meta["sources"]) == 1
        assert meta["sources"][0]["timestamp"] == 30.5
        assert len(meta["navigation_actions"]) == 1
        assert meta["navigation_actions"][0]["action"] == "jump_to"

    def test_extract_metadata_from_tool_result_entity(self):
        """Test extracting entity occurrences."""
        from agent.graphs.video import extract_metadata_from_tool_result

        tool_result = {
            "occurrences": [
                {
                    "timestamp": 60.0,
                    "timestamp_formatted": "1:00",
                    "occurrence_type": "visible",
                    "context": "Person appears on screen",
                    "confidence": 0.85,
                }
            ],
        }

        meta = extract_metadata_from_tool_result(tool_result)
        assert len(meta["sources"]) == 1
        assert meta["sources"][0]["type"] == "visible"

    def test_extract_metadata_from_tool_result_highlights(self):
        """Test extracting highlight suggestions."""
        from agent.graphs.video import extract_metadata_from_tool_result

        tool_result = {
            "highlights": [
                {
                    "title": "Key Moment",
                    "start_time": 120,
                    "end_time": 150,
                    "description": "An exciting moment",
                    "highlight_reason": "High engagement",
                }
            ],
        }

        meta = extract_metadata_from_tool_result(tool_result)
        assert len(meta["clip_suggestions"]) == 1
        assert meta["clip_suggestions"][0]["label"] == "Key Moment"

    def test_extract_metadata_from_tool_result_entities(self):
        """Test extracting related entities."""
        from agent.graphs.video import extract_metadata_from_tool_result

        tool_result = {
            "related_entities": [
                {"name": "John", "type": "person", "relevance": 0.9},
            ],
        }

        meta = extract_metadata_from_tool_result(tool_result)
        assert len(meta["entities"]) == 1
        assert meta["entities"][0]["name"] == "John"

    def test_extract_metadata_from_tool_result_empty(self):
        """Test extracting from empty/irrelevant result."""
        from agent.graphs.video import extract_metadata_from_tool_result

        meta = extract_metadata_from_tool_result({"message": "No results found"})
        assert meta["sources"] == []
        assert meta["navigation_actions"] == []
        assert meta["clip_suggestions"] == []
        assert meta["entities"] == []

    def test_extract_metadata_from_messages(self):
        """Test full message-level metadata extraction."""
        from agent.graphs.video import extract_metadata_from_messages

        messages = [
            HumanMessage(content="Find highlights"),
            AIMessage(
                content="",
                tool_calls=[{"name": "search_video", "args": {"query": "test"}, "id": "tc1"}],
            ),
            ToolMessage(
                content=json.dumps(
                    {
                        "results": [
                            {
                                "timestamp": 10,
                                "timestamp_formatted": "0:10",
                                "type": "visual",
                                "content": "test",
                                "score": 0.8,
                            }
                        ]
                    }
                ),
                tool_call_id="tc1",
                name="search_video",
            ),
            AIMessage(content="Here are the results"),
        ]

        meta = extract_metadata_from_messages(messages)
        assert meta["tool_calls"] == 1
        assert len(meta["sources"]) == 1


class TestVideoAgentGraph:
    """Test the LangGraph video agent."""

    @pytest.mark.asyncio
    async def test_agent_graph_creation(self):
        """Test that the graph compiles successfully."""
        from agent.graphs.video import create_video_agent_graph
        from langgraph.checkpoint.memory import MemorySaver

        checkpointer = MemorySaver()
        graph = create_video_agent_graph(checkpointer)

        assert graph is not None
        assert "CompiledStateGraph" in type(graph).__name__

    @pytest.mark.asyncio
    async def test_video_agent_graph_class(self):
        """Test VideoAgentGraph class initialization."""
        from agent.graphs.video import VideoAgentGraph

        agent = VideoAgentGraph(model_deployment="gpt-4o")

        assert agent.model_deployment == "gpt-4o"
        assert agent._graph is None  # Lazy initialization

    @pytest.mark.asyncio
    async def test_video_agent_graph_singleton(self):
        """Test that get_video_agent_graph returns singleton."""
        import agent.graphs.video as module
        from agent.graphs.video import get_video_agent_graph

        module._graph_instance = None

        agent1 = await get_video_agent_graph()
        agent2 = await get_video_agent_graph()

        assert agent1 is agent2

    def test_video_agent_has_proper_methods(self):
        """Test that VideoAgentGraph has all methods as proper class methods."""
        from agent.graphs.video import VideoAgentGraph

        agent = VideoAgentGraph(model_deployment="gpt-4o")

        assert hasattr(agent, "run")
        assert hasattr(agent, "run_stream")
        assert hasattr(agent, "get_state_history")
        assert hasattr(agent, "resume_from_checkpoint")
        assert hasattr(agent, "get_graph_diagram")
        assert hasattr(agent, "_build_messages")
        assert hasattr(agent, "_build_config")


class TestIterationLimits:
    """Test agent iteration limit behavior."""

    def test_video_should_continue_no_tool_calls(self):
        """Test should_continue returns END when no tool calls."""
        from agent.nodes.video_nodes import should_continue

        state = {"messages": [AIMessage(content="Final answer")], "tool_calls_count": 0}
        assert should_continue(state) == "__end__"

    def test_video_should_continue_at_limit(self):
        """Test should_continue returns END when at max iterations."""
        from agent.nodes.video_nodes import MAX_TOOL_ITERATIONS, should_continue

        state = {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[{"name": "search", "args": {}, "id": "tc1"}],
                )
            ],
            "tool_calls_count": MAX_TOOL_ITERATIONS,
        }
        assert should_continue(state) == "__end__"

    def test_video_should_continue_with_tool_calls(self):
        """Test should_continue returns 'tools' when under limit."""
        from agent.nodes.video_nodes import should_continue

        state = {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[{"name": "search", "args": {}, "id": "tc1"}],
                )
            ],
            "tool_calls_count": 1,
        }
        assert should_continue(state) == "tools"


class TestLangGraphTools:
    """Test LangGraph tool definitions."""

    def test_search_tools_defined(self):
        """Test that search tools are properly defined."""
        from agent.tools.general import SEARCH_TOOLS

        assert len(SEARCH_TOOLS) >= 5

        tool_names = [t.name for t in SEARCH_TOOLS]
        assert "search_video" in tool_names
        assert "find_entity" in tool_names
        assert "get_transcript" in tool_names
        assert "describe_scene" in tool_names
        assert "list_chapters" in tool_names

    @pytest.mark.asyncio
    async def test_search_video_no_context(self):
        """Test search_video returns error without media_id."""
        from agent.tools.general import search_video

        result = await search_video.ainvoke(
            {"query": "test"},
            config={"configurable": {}},
        )

        assert "error" in result
        assert result["error"]["type"] == "no_context"
        assert "No video context" in result["error"]["message"]

    @pytest.mark.asyncio
    async def test_list_chapters_uses_graph_direct(self):
        """Timeline output should query KnowledgeGraphService directly, not StructureService."""
        from agent.tools.context_tools import list_chapters

        mock_kg = MagicMock()
        mock_kg.is_connected = True
        mock_kg.get_video_node.return_value = {
            "video_id": "vid-123",
            "title": "Festival Video",
            "summary": "Festival-themed product montage.",
            "topics": ["Dragon Boat Festival", "SmallRig"],
        }
        mock_kg.get_video_scenes.return_value = [
            {
                "scene_index": 0,
                "start_time": 0.0,
                "end_time": 15.0,
                "title": "A busy street scene",
                "description": "Pedestrians move through a crowded intersection.",
            },
            {
                "scene_index": 1,
                "start_time": 15.0,
                "end_time": 30.0,
                "title": "Dragon boat branding close-up",
                "description": "",
            },
        ]

        with patch("services.knowledge_graph.get_knowledge_graph_service", return_value=mock_kg):
            result = await list_chapters.coroutine(target_video_id="vid-123")

        assert result["total_chapters"] == 2
        assert result["chapters"][0]["title"] == "A busy street scene"
        assert result["chapters"][0]["summary"] == (
            "Pedestrians move through a crowded intersection."
        )
        assert result["chapters"][1]["title"] == "Dragon boat branding close-up"
        # Scene has empty description — summary falls back to the scene title
        assert result["chapters"][1]["summary"] == "Dragon boat branding close-up"
        assert result["video_summary"] == "Festival-themed product montage."
        assert result["topics"] == ["Dragon Boat Festival", "SmallRig"]
        # No bulk frame fetch needed — scene properties and video_node.summary suffice
        mock_kg.get_video_node.assert_called_once_with("vid-123")
        mock_kg.get_video_scenes.assert_called_once_with("vid-123")
        mock_kg.get_video_frames.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_chapters_no_scenes_returns_topics(self):
        """When no scenes exist, list_chapters should return video-level topics."""
        from agent.tools.context_tools import list_chapters

        mock_kg = MagicMock()
        mock_kg.is_connected = True
        mock_kg.get_video_node.return_value = {"video_id": "vid-123"}
        mock_kg.get_video_scenes.return_value = []
        mock_kg.get_video_summary.return_value = ("A video about festivals.", ["Festival"])

        with patch("services.knowledge_graph.get_knowledge_graph_service", return_value=mock_kg):
            result = await list_chapters.coroutine(target_video_id="vid-123")

        assert result["chapters"] == []
        assert result["topics"] == ["Festival"]
        assert result["summary"] == "A video about festivals."

    @pytest.mark.asyncio
    async def test_list_chapters_graph_unavailable(self):
        """When Neo4j call fails, return a tool_error."""
        from agent.tools.context_tools import list_chapters

        mock_kg = MagicMock()
        mock_kg.get_video_node.side_effect = Exception("Neo4j connection refused")

        with patch("services.knowledge_graph.get_knowledge_graph_service", return_value=mock_kg):
            result = await list_chapters.coroutine(target_video_id="vid-123")

        assert "error" in result
        assert result["error"]["type"] == "query_error"
        assert "Failed to get chapters" in result["error"]["message"]


class TestRedisCheckpointer:
    """Test Redis checkpointer creation via unified factory."""

    @pytest.mark.asyncio
    async def test_checkpointer_fallback_to_memory(self):
        """Test fallback to MemorySaver when no persistent stores available."""
        import agent.graphs.video as module
        from langgraph.checkpoint.memory import MemorySaver

        # Reset singleton state
        module._shared_checkpointer = None
        module._checkpointer_lock = None

        with (
            patch.dict("os.environ", {"REDIS_URL": "", "DATABASE_URL": ""}, clear=False),
            patch.object(module, "_create_checkpointer_candidate", return_value=None),
        ):
            checkpointer = await module.get_shared_checkpointer()
            assert isinstance(checkpointer, MemorySaver)

        # Reset for other tests
        module._shared_checkpointer = None


class TestAgentImports:
    """Test that the agent module exports correctly."""

    def test_langgraph_exports(self):
        """Test LangGraph exports from agent module."""
        from agent import (
            AgentState,
            VideoAgentGraph,
            create_agent_state,
            get_shared_checkpointer,
            get_video_agent_graph,
        )

        assert VideoAgentGraph is not None
        assert AgentState is not None
        assert create_agent_state is not None
        assert get_video_agent_graph is not None
        assert get_shared_checkpointer is not None

    def test_metadata_extraction_exports(self):
        """Test metadata extraction helpers are importable."""
        from agent.graphs.video import (
            extract_metadata_from_messages,
            extract_metadata_from_tool_result,
        )

        assert extract_metadata_from_messages is not None
        assert extract_metadata_from_tool_result is not None

    def test_state_exports(self):
        """Test state module exports."""
        from agent.state import (
            AgentState,
            truncate_tool_message_content,
        )

        assert AgentState is not None
        assert truncate_tool_message_content is not None


class TestFormattingUtils:
    """Test formatting utility functions."""

    def test_format_timestamp(self):
        """Test timestamp formatting."""
        from agent.utils.formatting import format_timestamp

        assert format_timestamp(0) == "0:00"
        assert format_timestamp(61) == "1:01"
        assert format_timestamp(3661) == "1:01:01"

    def test_parse_timestamp(self):
        """Test timestamp parsing."""
        from agent.utils.formatting import parse_timestamp

        assert parse_timestamp("1:30") == 90
        assert parse_timestamp("1:01:01") == 3661

    def test_get_timestamp_from_content(self):
        """Test extracting timestamps from node content."""
        from agent.utils.formatting import get_timestamp_from_content

        assert get_timestamp_from_content({"timestamp": 30.5}) == 30.5
        assert get_timestamp_from_content({"start_time": 60.0}) == 60.0
        assert get_timestamp_from_content({}) == 0.0
        assert get_timestamp_from_content({}, default=99.0) == 99.0


# =============================================================================
# Graph Execution Tests with Mocked LLM (P0 Item #6)
# =============================================================================


class TestGraphExecutionPaths:
    """
    Test full graph execution paths with mocked LLM.

    These tests verify the graph structure and routing logic
    without requiring actual LLM API calls.
    """

    @pytest.mark.asyncio
    async def test_video_graph_structure(self):
        """Test that the video graph compiles with expected nodes."""
        from agent.graphs.video import create_video_agent_graph
        from langgraph.checkpoint.memory import MemorySaver

        checkpointer = MemorySaver()
        graph = create_video_agent_graph(checkpointer)

        # Verify graph structure
        graph_nodes = graph.get_graph().nodes
        node_names = list(graph_nodes.keys())

        # Should have all expected nodes
        assert "restore_media_context" in node_names
        assert "call_model" in node_names
        assert "tools" in node_names
        assert "update_context" in node_names
        assert "error_handler" in node_names

    @pytest.mark.asyncio
    async def test_video_graph_edges(self):
        """Test that the video graph has correct edge connections."""
        from agent.graphs.video import create_video_agent_graph
        from langgraph.checkpoint.memory import MemorySaver

        checkpointer = MemorySaver()
        graph = create_video_agent_graph(checkpointer)

        # Get graph structure
        graph_repr = graph.get_graph()

        # Verify we can generate a diagram (means graph is well-formed)
        mermaid = graph_repr.draw_mermaid()
        assert "call_model" in mermaid
        assert "tools" in mermaid

    @pytest.mark.asyncio
    async def test_video_graph_max_iterations(self):
        """Test that graph respects max iteration limits."""
        from agent.nodes.video_nodes import MAX_TOOL_ITERATIONS, should_continue

        # Simulate state at max iterations
        state = {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[{"name": "search", "args": {}, "id": "tc1"}],
                )
            ],
            "tool_calls_count": MAX_TOOL_ITERATIONS,
            "consecutive_errors": 0,
        }

        # Should return END even though there are tool calls
        result = should_continue(state)
        assert result == "__end__"


class TestErrorHandling:
    """Test error handling and graceful degradation."""

    @pytest.mark.asyncio
    async def test_error_handler_with_partial_results(self):
        """Test error handler generates helpful response with partial results."""
        from agent.nodes.base import error_handler_node

        state = {
            "messages": [],
            "consecutive_errors": 3,
            "last_error": "Connection timeout",
            "partial_results": [
                {"tool": "search_video", "summary": "Found 3 results about topic X"},
                {"tool": "find_entity", "summary": "Located person at 1:30"},
            ],
        }

        result = await error_handler_node(state, {})

        # Should generate a helpful response
        assert "messages" in result
        assert len(result["messages"]) == 1
        assert (
            "partial" in result["messages"][0].content.lower()
            or "found" in result["messages"][0].content.lower()
        )
        # Should reset error state
        assert result["consecutive_errors"] == 0

    @pytest.mark.asyncio
    async def test_error_handler_without_partial_results(self):
        """Test error handler with no partial results."""
        from agent.nodes.base import error_handler_node

        state = {
            "messages": [],
            "consecutive_errors": 3,
            "last_error": "Service unavailable",
            "partial_results": [],
        }

        result = await error_handler_node(state, {})

        # Should ask user to try again
        assert "messages" in result
        response_content = result["messages"][0].content.lower()
        assert "error" in response_content or "issue" in response_content

    def test_should_retry_exception_transient(self):
        """Test retry policy for transient errors."""
        from agent.state.agent_state import should_retry_exception

        # Transient errors should retry
        assert should_retry_exception(ConnectionError("Network issue"))
        assert should_retry_exception(TimeoutError("Request timed out"))
        assert should_retry_exception(Exception("rate limit exceeded"))
        assert should_retry_exception(Exception("503 Service Unavailable"))

    def test_should_retry_exception_permanent(self):
        """Test retry policy for permanent errors."""
        from agent.state.agent_state import should_retry_exception

        # Permanent errors should not retry
        assert not should_retry_exception(ValueError("Invalid input"))
        assert not should_retry_exception(TypeError("Wrong type"))
        assert not should_retry_exception(KeyError("Missing key"))
        assert not should_retry_exception(PermissionError("Access denied"))

    def test_error_threshold_routing(self):
        """Test that error threshold routes to error_handler."""
        from agent.nodes.base import MAX_CONSECUTIVE_ERRORS, base_should_continue

        # State with errors but partial results
        state = {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[{"name": "search", "args": {}, "id": "tc1"}],
                )
            ],
            "tool_calls_count": 1,
            "consecutive_errors": MAX_CONSECUTIVE_ERRORS,
            "partial_results": [{"tool": "test", "summary": "some result"}],
        }

        result = base_should_continue(state, max_iterations=5)
        assert result == "error_handler"


class TestInputOutputSchemaSeparation:
    """Test Input/Output schema separation (P0 Item #1)."""

    def test_input_state_excludes_internal_fields(self):
        """Test that AgentInputState doesn't expose internal bookkeeping."""
        from agent.state.agent_state import AgentInputState

        # These fields should be in InputState
        input_fields = AgentInputState.__annotations__
        assert "messages" in input_fields
        assert "media_id" in input_fields
        assert "user_id" in input_fields

        # These internal fields should NOT be in InputState
        assert "tool_calls_count" not in input_fields
        assert "consecutive_errors" not in input_fields
        assert "partial_results" not in input_fields
        assert "memory_context" not in input_fields
        assert "artifact_refs" not in input_fields

    def test_output_state_excludes_internal_fields(self):
        """Test that AgentOutputState doesn't expose internal bookkeeping."""
        from agent.state.agent_state import AgentOutputState

        output_fields = AgentOutputState.__annotations__

        # Should have results
        assert "messages" in output_fields
        assert "sources" in output_fields

        # Should NOT have internal tracking
        assert "tool_calls_count" not in output_fields
        assert "consecutive_errors" not in output_fields
        assert "conversation_context" not in output_fields
        assert "memory_context" not in output_fields
        assert "artifact_refs" not in output_fields

    def test_internal_state_has_all_fields(self):
        """Test that AgentState has all fields including internal ones."""
        from agent.state.agent_state import AgentState

        state_fields = AgentState.__annotations__

        # Should have all fields
        assert "messages" in state_fields
        assert "tool_calls_count" in state_fields
        assert "consecutive_errors" in state_fields
        assert "partial_results" in state_fields
        assert "conversation_context" in state_fields
        assert "memory_context" in state_fields
        assert "artifact_refs" in state_fields


class TestDynamicToolBinding:
    """Test dynamic tool binding (P1 Item #8)."""

    def test_select_tools_for_search_query(self):
        """Test tool selection for search-like queries."""
        from agent.nodes.base import select_tools_for_query
        from agent.tools import SEARCH_TOOLS

        query = "Find where the speaker mentions AI"
        selected = select_tools_for_query(query, SEARCH_TOOLS, max_tools=5)

        assert len(selected) <= 5
        # Should prioritize search tools
        tool_names = [t.name for t in selected]
        assert any("search" in name.lower() for name in tool_names)

    def test_select_tools_for_entity_query(self):
        """Test tool selection for entity-focused queries."""
        from agent.nodes.base import select_tools_for_query
        from agent.tools import SEARCH_TOOLS

        query = "Who is the main person speaking?"
        selected = select_tools_for_query(query, SEARCH_TOOLS, max_tools=5)

        assert len(selected) <= 5

    def test_select_tools_for_generic_timeline_query(self):
        """Generic timeline queries should prioritize structure-aware tools."""
        from agent.nodes.base import select_tools_for_query
        from agent.tools import SEARCH_TOOLS

        query = "Generate a timeline"
        selected = select_tools_for_query(query, SEARCH_TOOLS, max_tools=5)

        tool_names = [t.name for t in selected]
        assert "list_chapters" in tool_names[:4]
        assert "get_video_info" in tool_names
        assert "get_summary" in tool_names

    def test_select_tools_max_limit(self):
        """Test that tool selection respects max_tools limit."""
        from agent.nodes.base import select_tools_for_query
        from agent.tools import SEARCH_TOOLS

        query = "Do everything"  # Vague query that might match many tools

        for max_tools in [3, 5, 8, 10]:
            selected = select_tools_for_query(query, SEARCH_TOOLS, max_tools=max_tools)
            assert len(selected) <= max_tools

    def test_multi_video_library_query_prioritises_library_tools(self):
        """Library tools are prioritised when is_multi_video and query has library keywords."""
        from agent.nodes.base import select_tools_for_query
        from agent.tools import SEARCH_TOOLS

        query = "Search across all videos for mentions of AI"
        selected = select_tools_for_query(query, SEARCH_TOOLS, max_tools=8, is_multi_video=True)

        tool_names = [t.name for t in selected]
        # At least one multi-video tool should be in the first 3 positions
        first_three = tool_names[:3]
        assert any(
            name
            in (
                "search_across_videos",
                "compare_videos",
                "find_common_entities",
                "get_library_overview",
            )
            for name in first_three
        ), f"Expected library tool in first 3, got {first_three}"

    def test_multi_video_guarantees_at_least_one_library_tool(self):
        """Even without library keywords, is_multi_video ensures >=1 library tool."""
        from agent.nodes.base import select_tools_for_query
        from agent.tools import SEARCH_TOOLS

        # Query has no library keywords at all
        query = "Find the speaker mentioning revenue"
        selected = select_tools_for_query(query, SEARCH_TOOLS, max_tools=8, is_multi_video=True)

        tool_names = {t.name for t in selected}
        library_names = {
            "search_across_videos",
            "compare_videos",
            "find_common_entities",
            "get_library_overview",
        }
        assert (
            tool_names & library_names
        ), f"Expected at least 1 library tool when is_multi_video=True, got {tool_names}"

    def test_single_video_unchanged_behavior(self):
        """When is_multi_video=False, results must be identical to default call."""
        from agent.nodes.base import select_tools_for_query
        from agent.tools import SEARCH_TOOLS

        query = "Find the speaker mentioning revenue"
        default = select_tools_for_query(query, SEARCH_TOOLS, max_tools=8)
        explicit_false = select_tools_for_query(
            query, SEARCH_TOOLS, max_tools=8, is_multi_video=False
        )
        assert [t.name for t in default] == [t.name for t in explicit_false]

    def test_multi_video_respects_max_tools(self):
        """Library-mode selection still respects the max_tools cap."""
        from agent.nodes.base import select_tools_for_query
        from agent.tools import SEARCH_TOOLS

        query = "Compare all videos and find every topic across the library"
        for max_tools in [3, 5, 8]:
            selected = select_tools_for_query(
                query, SEARCH_TOOLS, max_tools=max_tools, is_multi_video=True
            )
            assert len(selected) <= max_tools

    def test_multi_video_compare_query_includes_compare_videos(self):
        """A 'compare' query in multi-video mode should include compare_videos."""
        from agent.nodes.base import select_tools_for_query
        from agent.tools import SEARCH_TOOLS

        query = "Compare the main topics between both videos"
        selected = select_tools_for_query(query, SEARCH_TOOLS, max_tools=8, is_multi_video=True)

        tool_names = {t.name for t in selected}
        assert (
            "compare_videos" in tool_names or "search_across_videos" in tool_names
        ), f"Expected cross-video tool for compare query, got {tool_names}"

    # -- Selector regression tests for confusing tool pairs --

    def test_describe_scene_still_classified_as_search(self):
        """describe_scene docstring update must keep routing keywords for search."""
        from agent.nodes.base import select_tools_for_query
        from agent.tools import SEARCH_TOOLS

        query = "What is happening at 1:30?"
        selected = select_tools_for_query(query, SEARCH_TOOLS, max_tools=8)
        tool_names = [t.name for t in selected]
        assert "describe_scene" in tool_names, f"describe_scene missing from {tool_names}"

    def test_find_entity_stays_in_entity_category(self):
        """find_entity must still route on entity queries after docstring change."""
        from agent.nodes.base import select_tools_for_query
        from agent.tools import SEARCH_TOOLS

        query = "Who is the person in the red shirt?"
        selected = select_tools_for_query(query, SEARCH_TOOLS, max_tools=8)
        tool_names = [t.name for t in selected]
        assert "find_entity" in tool_names, f"find_entity missing from {tool_names}"

    def test_get_entity_timeline_routes_for_tracking(self):
        """get_entity_timeline should be selected for tracking/timeline queries."""
        from agent.nodes.base import select_tools_for_query
        from agent.tools import SEARCH_TOOLS

        query = "Track how the speaker changes throughout the video"
        selected = select_tools_for_query(query, SEARCH_TOOLS, max_tools=8)
        tool_names = [t.name for t in selected]
        assert "get_entity_timeline" in tool_names, f"get_entity_timeline missing from {tool_names}"

    def test_get_transcript_routes_for_quote_queries(self):
        """get_transcript should be selected for verbatim/quote queries."""
        from agent.nodes.base import select_tools_for_query
        from agent.tools import SEARCH_TOOLS

        query = "What exactly did the speaker say about revenue?"
        selected = select_tools_for_query(query, SEARCH_TOOLS, max_tools=8)
        tool_names = [t.name for t in selected]
        assert "get_transcript" in tool_names, f"get_transcript missing from {tool_names}"

    def test_overview_tools_selected_for_summary_query(self):
        """Summary queries should select get_summary and list_chapters."""
        from agent.nodes.base import select_tools_for_query
        from agent.tools import SEARCH_TOOLS

        query = "Give me a summary of this video"
        selected = select_tools_for_query(query, SEARCH_TOOLS, max_tools=8)
        tool_names = [t.name for t in selected]
        assert "get_summary" in tool_names, f"get_summary missing from {tool_names}"

    def test_scene_context_routes_for_context_queries(self):
        """get_scene_context is in subtitle category (name contains 'text' substring).
        Verify it surfaces for subtitle/transcript queries."""
        from agent.nodes.base import select_tools_for_query
        from agent.tools import SEARCH_TOOLS

        # get_scene_context is categorised as subtitle because the tool name
        # "get_scene_context" contains the substring "text" (con-text).
        # It surfaces when the query matches subtitle keywords.
        query = "What exactly was said around the 5 minute mark?"
        selected = select_tools_for_query(query, SEARCH_TOOLS, max_tools=8)
        tool_names = [t.name for t in selected]
        assert "get_scene_context" in tool_names, f"get_scene_context missing from {tool_names}"


class TestProductionCheckpointerFactory:
    """Test unified async checkpointer factory."""

    @pytest.mark.asyncio
    async def test_checkpointer_cascade_fallback(self):
        """Test that factory falls back to MemorySaver when no stores available."""
        import agent.graphs.video as module
        from langgraph.checkpoint.memory import MemorySaver

        module._shared_checkpointer = None
        module._checkpointer_lock = None

        with patch.object(module, "_create_checkpointer_candidate", return_value=None):
            checkpointer = await module.get_shared_checkpointer()
            assert isinstance(checkpointer, MemorySaver)

        module._shared_checkpointer = None

    @pytest.mark.asyncio
    async def test_checkpointer_materializes_candidate(self):
        """Test that a valid candidate is materialized and returned."""
        import agent.graphs.video as module

        mock_saver = MagicMock()
        mock_saver.setup = AsyncMock()

        module._shared_checkpointer = None
        module._checkpointer_lock = None

        with (
            patch.object(module, "_create_checkpointer_candidate", return_value=mock_saver),
            patch.object(
                module,
                "_materialize_checkpointer",
                new_callable=AsyncMock,
                return_value=mock_saver,
            ),
        ):
            checkpointer = await module.get_shared_checkpointer()
            assert checkpointer is mock_saver

        module._shared_checkpointer = None

    @pytest.mark.asyncio
    async def test_checkpointer_singleton_behavior(self):
        """Test that get_shared_checkpointer returns the same instance."""
        import agent.graphs.video as module

        mock_saver = MagicMock()

        module._shared_checkpointer = None
        module._checkpointer_lock = None

        with (
            patch.object(module, "_create_checkpointer_candidate", return_value=mock_saver),
            patch.object(
                module,
                "_materialize_checkpointer",
                new_callable=AsyncMock,
                return_value=mock_saver,
            ),
        ):
            cp1 = await module.get_shared_checkpointer()
            cp2 = await module.get_shared_checkpointer()
            assert cp1 is cp2

        module._shared_checkpointer = None


class TestMultiTenantSecurity:
    """Test multi-tenant security (P0 Item #5)."""

    def test_state_includes_user_id(self):
        """Test that state properly tracks user_id."""
        from agent.state.agent_state import create_agent_state

        state = create_agent_state(
            messages=[HumanMessage(content="test")],
            user_id="user-123",
            session_id="session-456",
        )

        assert state["user_id"] == "user-123"
        assert state["session_id"] == "session-456"

    def test_config_scopes_by_thread(self):
        """Test that config properly scopes by thread_id."""
        from agent.graphs.video import VideoAgentGraph

        agent = VideoAgentGraph()
        config = agent._build_config(media_id="vid-1", session_id="user-123-session-1")

        # Thread ID should be set for checkpointer isolation
        assert config["configurable"]["thread_id"] == "user-123-session-1"


# =============================================================================
# Observability Tests
# =============================================================================


class TestObservability:
    """Test observability utilities (logging, metrics, tracing)."""

    def test_request_context_creation(self):
        """Test RequestContext creation with defaults."""
        from agent.utils.observability import RequestContext

        ctx = RequestContext()
        assert ctx.request_id is not None
        assert len(ctx.request_id) == 8
        assert ctx.node_path == []
        assert ctx.tool_calls == []

    def test_request_context_tracking(self):
        """Test RequestContext tracks nodes and tool calls."""
        from agent.utils.observability import RequestContext

        ctx = RequestContext(user_id="user-1")

        ctx.add_node("call_model")
        ctx.add_node("tools")
        ctx.add_tool_call("search_video", 150.5, True)
        ctx.add_tool_call("find_entity", 200.0, False)
        ctx.add_error("Connection timeout", "tools")

        assert len(ctx.node_path) == 2
        assert len(ctx.tool_calls) == 2
        assert len(ctx.errors) == 1
        assert ctx.tool_calls[0]["success"] is True
        assert ctx.tool_calls[1]["success"] is False

    def test_request_context_manager(self):
        """Test request_context context manager."""
        from agent.utils.observability import get_request_context, request_context

        with request_context(user_id="test-user", media_id="test-video") as ctx:
            assert ctx.user_id == "test-user"
            assert ctx.media_id == "test-video"

            # Should be accessible via get_request_context
            current = get_request_context()
            assert current.user_id == "test-user"

    def test_metrics_counter(self):
        """Test Metrics counter operations."""
        from agent.utils.observability import Metrics

        Metrics.reset()

        Metrics.inc_counter("test_counter", {"label": "a"})
        Metrics.inc_counter("test_counter", {"label": "a"})
        Metrics.inc_counter("test_counter", {"label": "b"})

        all_metrics = Metrics.get_all()
        assert all_metrics["counters"]["test_counter{label=a}"] == 2
        assert all_metrics["counters"]["test_counter{label=b}"] == 1

    def test_metrics_histogram(self):
        """Test Metrics histogram operations."""
        from agent.utils.observability import Metrics

        Metrics.reset()

        Metrics.observe_histogram("test_duration", 0.1)
        Metrics.observe_histogram("test_duration", 0.2)
        Metrics.observe_histogram("test_duration", 0.3)

        all_metrics = Metrics.get_all()
        assert len(all_metrics["histograms"]["test_duration"]) == 3
        assert abs(sum(all_metrics["histograms"]["test_duration"]) - 0.6) < 0.001

    def test_record_tool_call_metrics(self):
        """Test convenience method for recording tool calls."""
        from agent.utils.observability import Metrics

        Metrics.reset()

        Metrics.record_tool_call("search_video", 0.15, True, "video")
        Metrics.record_tool_call("search_video", 0.20, False, "video")

        all_metrics = Metrics.get_all()

        # Should have call counter
        assert "agent_tool_calls_total{agent=video,tool=search_video}" in all_metrics["counters"]
        assert all_metrics["counters"]["agent_tool_calls_total{agent=video,tool=search_video}"] == 2

        # Should have error counter
        assert (
            all_metrics["counters"]["agent_tool_call_errors_total{agent=video,tool=search_video}"]
            == 1
        )

    def test_structured_logger(self):
        """Test StructuredLogger includes context."""

        from agent.utils.observability import get_logger, request_context

        logger = get_logger("test_module")

        # Capture log output
        with request_context(user_id="log-test-user", request_id="req-123"):
            # Logger should work without errors
            logger.info("Test message", extra_field="value")
            logger.tool_start("test_tool")
            logger.tool_end("test_tool", 100.0, True)

    def test_inject_request_context_to_config(self):
        """Test injecting context into RunnableConfig."""
        from agent.utils.observability import (
            RequestContext,
            inject_request_context_to_config,
        )

        ctx = RequestContext(
            request_id="test-req-1",
            user_id="user-1",
            session_id="session-1",
        )

        config = {"configurable": {"thread_id": "t1"}}
        updated = inject_request_context_to_config(config, ctx)

        assert updated["configurable"]["request_id"] == "test-req-1"
        assert updated["configurable"]["user_id"] == "user-1"
        assert updated["metadata"]["request_id"] == "test-req-1"


class TestStateValidation:
    """Test Pydantic-style state validation."""

    def test_state_has_required_fields(self):
        """Test that create_agent_state initializes all fields."""
        from agent.state.agent_state import create_agent_state

        state = create_agent_state(
            messages=[HumanMessage(content="test")],
            media_id="vid-1",
        )

        # All tracking fields should be initialized
        assert state["tool_calls_count"] == 0
        assert state["consecutive_errors"] == 0
        assert state["partial_results"] == []
        assert state["conversation_context"] == []
        assert state["memory_context"] == []
        assert state["artifact_refs"] == []
        assert state["sources"] == []

    def test_state_types_correct(self):
        """Test that state fields have correct types."""
        from agent.state.agent_state import (
            AgentInputState,
            AgentOutputState,
            AgentState,
        )

        # Check AgentState has all expected fields
        state_annotations = AgentState.__annotations__

        assert "messages" in state_annotations
        assert "tool_calls_count" in state_annotations
        assert "consecutive_errors" in state_annotations
        assert "partial_results" in state_annotations
        assert "memory_context" in state_annotations
        assert "artifact_refs" in state_annotations

        # Check Input/Output schemas are subsets
        input_annotations = AgentInputState.__annotations__
        output_annotations = AgentOutputState.__annotations__

        # Input should not have internal tracking
        assert "tool_calls_count" not in input_annotations
        assert "consecutive_errors" not in input_annotations

        # Output should have results but not tracking
        assert "sources" in output_annotations
        assert "tool_calls_count" not in output_annotations


class TestMultiVideoState:
    """Test multi-video agent state creation and routing."""

    def test_create_agent_state_with_media_ids(self):
        """Test state creation with multiple video IDs."""
        from agent.state.agent_state import create_agent_state

        messages = [HumanMessage(content="Compare these videos")]
        state = create_agent_state(
            messages=messages,
            media_id="vid-1",
            media_ids=["vid-1", "vid-2", "vid-3"],
        )

        assert state["media_id"] == "vid-1"
        assert state["media_ids"] == ["vid-1", "vid-2", "vid-3"]
        assert state["video_context"]["media_id"] == "vid-1"

    def test_create_agent_state_dedup_media_ids(self):
        """Test deduplication of media_ids."""
        from agent.state.agent_state import create_agent_state

        messages = [HumanMessage(content="test")]
        state = create_agent_state(
            messages=messages,
            media_id="vid-1",
            media_ids=["vid-1", "vid-2", "vid-1", "vid-2"],
        )

        assert state["media_ids"] == ["vid-1", "vid-2"]

    def test_create_agent_state_single_media_ids_is_included(self):
        """Test that media_ids is set even with a single video (prevents KeyError on resume)."""
        from agent.state.agent_state import create_agent_state

        messages = [HumanMessage(content="test")]
        state = create_agent_state(
            messages=messages,
            media_id="vid-1",
            media_ids=["vid-1"],
        )

        assert state["media_id"] == "vid-1"
        assert state["media_ids"] == ["vid-1"]

    def test_create_agent_state_max_10_videos(self):
        """Test that media_ids is capped at 10."""
        from agent.state.agent_state import create_agent_state

        ids = [f"vid-{i}" for i in range(15)]
        messages = [HumanMessage(content="test")]
        state = create_agent_state(
            messages=messages,
            media_ids=ids,
        )

        assert len(state["media_ids"]) == 10
        assert state["media_id"] == "vid-0"

    def test_create_agent_state_merge_media_id_and_ids(self):
        """Test merging media_id with media_ids preserving order."""
        from agent.state.agent_state import create_agent_state

        messages = [HumanMessage(content="test")]
        state = create_agent_state(
            messages=messages,
            media_id="vid-0",
            media_ids=["vid-1", "vid-2"],
        )

        assert state["media_ids"] == ["vid-0", "vid-1", "vid-2"]
        assert state["media_id"] == "vid-0"

    def test_extract_metadata_from_cross_video_results(self):
        """Test extracting sources from cross-video tool output."""
        from agent.graphs.video import extract_metadata_from_tool_result

        tool_result = {
            "results_by_video": [
                {
                    "video_id": "vid-1",
                    "video_title": "Video One",
                    "matches": [
                        {
                            "timestamp": 30.0,
                            "timestamp_formatted": "0:30",
                            "content": "A topic discussed",
                            "score": 0.9,
                        }
                    ],
                },
                {
                    "video_id": "vid-2",
                    "video_title": "Video Two",
                    "matches": [
                        {
                            "timestamp": 60.0,
                            "timestamp_formatted": "1:00",
                            "content": "Same topic here",
                            "score": 0.85,
                        }
                    ],
                },
            ],
        }

        meta = extract_metadata_from_tool_result(tool_result)
        assert len(meta["sources"]) == 2
        assert meta["sources"][0]["video_id"] == "vid-1"
        assert meta["sources"][0]["video_title"] == "Video One"
        assert meta["sources"][1]["video_id"] == "vid-2"

    def test_extract_metadata_from_comparison_results(self):
        """Test extracting sources from compare_videos output."""
        from agent.graphs.video import extract_metadata_from_tool_result

        tool_result = {
            "comparison": [
                {
                    "video_id": "vid-1",
                    "video_title": "Video A",
                    "relevant_moments": [
                        {
                            "timestamp": 45.0,
                            "timestamp_formatted": "0:45",
                            "content": "Key moment",
                            "score": 0.88,
                        }
                    ],
                },
            ],
        }

        meta = extract_metadata_from_tool_result(tool_result)
        assert len(meta["sources"]) == 1
        assert meta["sources"][0]["video_title"] == "Video A"
        assert meta["sources"][0]["timestamp"] == 45.0

    def test_extract_metadata_from_chapters(self):
        """Test extracting sources from list_chapters output."""
        from agent.graphs.video import extract_metadata_from_tool_result

        tool_result = {
            "total_chapters": 2,
            "chapters": [
                {
                    "number": 1,
                    "title": "Introduction",
                    "start_time": 0,
                    "start_formatted": "0:00",
                    "end_time": 30,
                    "end_formatted": "0:30",
                    "summary": "Opening remarks",
                },
                {
                    "number": 2,
                    "title": "Main Content",
                    "start_time": 30,
                    "start_formatted": "0:30",
                    "end_time": 120,
                    "end_formatted": "2:00",
                    "summary": "Core discussion",
                },
            ],
        }

        meta = extract_metadata_from_tool_result(tool_result)
        assert len(meta["sources"]) == 2
        assert meta["sources"][0]["timestamp"] == 0
        assert meta["sources"][0]["type"] == "structure"
        assert meta["sources"][0]["description"] == "Opening remarks"
        assert meta["sources"][1]["timestamp"] == 30
        assert len(meta["navigation_actions"]) == 2
        assert meta["navigation_actions"][0]["label"] == "Chapter: Introduction"

    def test_extract_metadata_from_transcript(self):
        """Test extracting source from get_transcript output."""
        from agent.graphs.video import extract_metadata_from_tool_result

        tool_result = {
            "start_time": 10,
            "end_time": 60,
            "start_formatted": "0:10",
            "end_formatted": "1:00",
            "transcript": "Hello world...",
            "segments_count": 15,
            "speakers": ["Speaker A"],
        }

        meta = extract_metadata_from_tool_result(tool_result)
        assert len(meta["sources"]) == 1
        assert meta["sources"][0]["timestamp"] == 10
        assert meta["sources"][0]["type"] == "audio"
        assert meta["sources"][0]["timestamp_formatted"] == "0:10"
        assert "15 segments" in meta["sources"][0]["description"]

    def test_extract_metadata_from_transcript_zero_segments(self):
        """Test that transcript with zero segments produces no source."""
        from agent.graphs.video import extract_metadata_from_tool_result

        tool_result = {
            "start_time": 0,
            "end_time": 30,
            "start_formatted": "0:00",
            "end_formatted": "0:30",
            "transcript": "",
            "segments_count": 0,
            "speakers": [],
        }

        meta = extract_metadata_from_tool_result(tool_result)
        assert len(meta["sources"]) == 0

    def test_extract_metadata_from_describe_scene(self):
        """Test extracting source from describe_scene output."""
        from agent.graphs.video import extract_metadata_from_tool_result

        tool_result = {
            "timestamp": 15.5,
            "timestamp_formatted": "0:15",
            "description": "A presenter stands at a podium addressing the audience.",
            "scene_type": "presentation",
        }

        meta = extract_metadata_from_tool_result(tool_result)
        assert len(meta["sources"]) == 1
        assert meta["sources"][0]["timestamp"] == 15.5
        assert meta["sources"][0]["type"] == "visual"
        assert "presenter" in meta["sources"][0]["description"]

    def test_extract_metadata_from_describe_scene_not_in_results(self):
        """Test that describe_scene extraction does not trigger when results key present."""
        from agent.graphs.video import extract_metadata_from_tool_result

        tool_result = {
            "timestamp": 10,
            "description": "Should not be extracted as standalone",
            "results": [
                {
                    "timestamp": 10,
                    "timestamp_formatted": "0:10",
                    "type": "visual",
                    "content": "From results list",
                    "score": 0.9,
                }
            ],
        }

        meta = extract_metadata_from_tool_result(tool_result)
        # Should only get the source from results list, not from top-level describe_scene
        assert len(meta["sources"]) == 1
        assert meta["sources"][0]["description"] == "From results list"

    def test_extract_metadata_from_scene_context(self):
        """Test extracting source from get_scene_context output."""
        from agent.graphs.video import extract_metadata_from_tool_result

        tool_result = {
            "timestamp": 30,
            "context": {
                "before": {"frames": [{"timestamp": "0:25"}]},
                "during": {"frames": [], "audio": []},
                "after": {"frames": [{"timestamp": "0:35"}]},
            },
            "total_frames_in_window": 5,
        }

        meta = extract_metadata_from_tool_result(tool_result)
        assert len(meta["sources"]) == 1
        assert meta["sources"][0]["timestamp"] == 30
        assert meta["sources"][0]["type"] == "visual"
        assert meta["sources"][0]["description"] == "Scene context window"
        assert len(meta["navigation_actions"]) == 1
        assert meta["navigation_actions"][0]["action"] == "jump_to"
        assert "30" in meta["navigation_actions"][0]["label"]

    def test_extract_metadata_from_community_overview(self):
        """Test that community overview (no timestamps) produces no sources."""
        from agent.graphs.video import extract_metadata_from_tool_result

        tool_result = {
            "total_communities": 3,
            "communities": [
                {"title": "Tech Discussion", "summary": "About AI", "themes": ["AI"]},
            ],
        }

        meta = extract_metadata_from_tool_result(tool_result)
        assert len(meta["sources"]) == 0

    def test_extract_metadata_video_id_injected_into_search_results(self):
        """Test that video_id is injected into single-video search sources."""
        from agent.graphs.video import extract_metadata_from_tool_result

        tool_result = {
            "results": [
                {
                    "timestamp": 10.0,
                    "timestamp_formatted": "0:10",
                    "type": "visual",
                    "content": "A dog running",
                    "score": 0.9,
                }
            ],
        }

        meta = extract_metadata_from_tool_result(
            tool_result, video_id="vid-abc", video_title="My Video"
        )
        assert len(meta["sources"]) == 1
        assert meta["sources"][0]["video_id"] == "vid-abc"
        assert meta["sources"][0]["video_title"] == "My Video"

    def test_extract_metadata_video_id_injected_without_title(self):
        """Test that video_id alone is injected when video_title is None."""
        from agent.graphs.video import extract_metadata_from_tool_result

        tool_result = {
            "results": [
                {
                    "timestamp": 5.0,
                    "timestamp_formatted": "0:05",
                    "type": "audio",
                    "content": "Hello world",
                    "score": 0.8,
                }
            ],
        }

        meta = extract_metadata_from_tool_result(tool_result, video_id="vid-xyz")
        assert meta["sources"][0]["video_id"] == "vid-xyz"
        assert "video_title" not in meta["sources"][0]

    def test_extract_metadata_video_id_not_overwritten_for_cross_video(self):
        """Test that cross-video sources keep their own video_id."""
        from agent.graphs.video import extract_metadata_from_tool_result

        tool_result = {
            "results_by_video": [
                {
                    "video_id": "vid-1",
                    "video_title": "Video One",
                    "matches": [
                        {
                            "timestamp": 30.0,
                            "timestamp_formatted": "0:30",
                            "content": "Topic A",
                            "score": 0.9,
                        }
                    ],
                },
            ],
        }

        meta = extract_metadata_from_tool_result(
            tool_result, video_id="vid-primary", video_title="Primary Video"
        )
        assert len(meta["sources"]) == 1
        # Cross-video source must keep its own video_id, not the passed one
        assert meta["sources"][0]["video_id"] == "vid-1"
        assert meta["sources"][0]["video_title"] == "Video One"

    def test_extract_metadata_video_id_mixed_single_and_cross(self):
        """Test mixed results: single-video gets injected, cross-video keeps own."""
        from agent.graphs.video import extract_metadata_from_tool_result

        tool_result = {
            "results": [
                {
                    "timestamp": 10.0,
                    "timestamp_formatted": "0:10",
                    "type": "visual",
                    "content": "Scene description",
                    "score": 0.85,
                }
            ],
            "results_by_video": [
                {
                    "video_id": "vid-other",
                    "video_title": "Other Video",
                    "matches": [
                        {
                            "timestamp": 20.0,
                            "timestamp_formatted": "0:20",
                            "content": "Cross video result",
                            "score": 0.75,
                        }
                    ],
                },
            ],
        }

        meta = extract_metadata_from_tool_result(
            tool_result, video_id="vid-main", video_title="Main Video"
        )
        assert len(meta["sources"]) == 2
        # Single-video source gets injected video_id
        single_src = [s for s in meta["sources"] if s["video_id"] == "vid-main"]
        assert len(single_src) == 1
        assert single_src[0]["video_title"] == "Main Video"
        # Cross-video source keeps its own
        cross_src = [s for s in meta["sources"] if s["video_id"] == "vid-other"]
        assert len(cross_src) == 1
        assert cross_src[0]["video_title"] == "Other Video"

    def test_extract_metadata_no_video_id_backward_compatible(self):
        """Test backward compatibility: no video_id param means no video_id in sources."""
        from agent.graphs.video import extract_metadata_from_tool_result

        tool_result = {
            "results": [
                {
                    "timestamp": 10.0,
                    "timestamp_formatted": "0:10",
                    "type": "visual",
                    "content": "A scene",
                    "score": 0.9,
                }
            ],
        }

        meta = extract_metadata_from_tool_result(tool_result)
        assert len(meta["sources"]) == 1
        assert "video_id" not in meta["sources"][0]
        assert "video_title" not in meta["sources"][0]

    def test_extract_metadata_from_messages_passes_video_id(self):
        """Test that extract_metadata_from_messages forwards video_id."""
        from agent.graphs.video import extract_metadata_from_messages
        from langchain_core.messages import ToolMessage

        messages = [
            ToolMessage(
                content=(
                    '{"results": [{"timestamp": 5.0, "timestamp_formatted": "0:05",'
                    ' "type": "visual", "content": "Hello", "score": 0.8}]}'
                ),
                tool_call_id="tc1",
            ),
        ]

        meta = extract_metadata_from_messages(messages, video_id="vid-msg", video_title="Msg Video")
        assert len(meta["sources"]) == 1
        assert meta["sources"][0]["video_id"] == "vid-msg"
        assert meta["sources"][0]["video_title"] == "Msg Video"

    def test_multi_video_prompt_selection(self):
        """Test that multi-video prompt is selected."""
        from agent.nodes.video_nodes import get_system_message

        state = {
            "video_context": {"media_id": "vid-1"},
            "media_id": "vid-1",
            "media_ids": ["vid-1", "vid-2", "vid-3"],
        }

        msg = get_system_message(state)
        assert "cross-video" in msg.content.lower() or "multiple videos" in msg.content.lower()

    def test_single_video_prompt_without_media_ids(self):
        """Test single-video prompt is used without media_ids."""
        from agent.nodes.video_nodes import get_system_message

        state = {
            "video_context": {"media_id": "vid-1"},
            "media_id": "vid-1",
            "media_ids": None,
        }

        msg = get_system_message(state)
        assert "cross-video" not in msg.content.lower()

    def test_single_media_ids_prompt_uses_video_context(self):
        """A single media_ids entry should not trigger the no-video prompt."""
        from agent.nodes.video_nodes import get_system_message

        state = {
            "video_context": None,
            "media_id": None,
            "media_ids": ["vid-1"],
        }

        msg = get_system_message(state)
        assert "no video loaded" not in msg.content.lower()
        assert "cross-video" not in msg.content.lower()

    def test_benchmark_prompt_overrides_final_answer_shape(self):
        """Video-MME benchmark mode should suppress normal explanatory output."""
        from agent.nodes.video_nodes import get_system_message

        state = {
            "video_context": {"media_id": "vid-1"},
            "media_id": "vid-1",
            "media_ids": ["vid-1"],
            "benchmark_context": {"eval_mode": "mcq", "format": "letter_only"},
        }

        msg = get_system_message(state)
        assert "Benchmark Response Mode" in msg.content
        assert "exactly one uppercase letter" in msg.content
        assert "follow-up questions" in msg.content

    def test_multi_video_prompt_lists_all_media_ids(self):
        """Test that multi-video prompt lists each media_id individually."""
        from agent.nodes.video_nodes import get_system_message

        state = {
            "video_context": {"media_id": "vid-1"},
            "media_id": "vid-1",
            "media_ids": ["vid-1", "vid-2", "vid-3"],
        }

        msg = get_system_message(state)
        assert "vid-1" in msg.content
        assert "vid-2" in msg.content
        assert "vid-3" in msg.content
        assert "Selected Videos (3):" in msg.content

    def test_multi_video_prompt_includes_tool_guidance(self):
        """Test that multi-video prompt includes guidance about cross-video tools."""
        from agent.nodes.video_nodes import get_system_message

        state = {
            "video_context": {"media_id": "vid-1"},
            "media_id": "vid-1",
            "media_ids": ["vid-1", "vid-2"],
        }

        msg = get_system_message(state)
        assert "search_across_videos" in msg.content
        assert "compare_videos" in msg.content
        assert "target_video_id" in msg.content

    def test_multi_video_prompt_enumerates_videos(self):
        """Test that multi-video prompt numbers each video."""
        from agent.nodes.video_nodes import get_system_message

        state = {
            "video_context": {"media_id": "vid-a"},
            "media_id": "vid-a",
            "media_ids": ["vid-a", "vid-b"],
        }

        msg = get_system_message(state)
        assert "Video 1: vid-a" in msg.content
        assert "Video 2: vid-b" in msg.content

    def test_restore_media_context_logs_all_multi_video_ids(self):
        """Test that restore_media_context logs all media_ids in multi-video mode."""
        import logging

        from agent.nodes.video_nodes import restore_media_context
        from langchain_core.runnables import RunnableConfig

        state = {
            "media_id": None,
            "media_ids": None,
            "video_context": None,
        }
        config = RunnableConfig(
            configurable={
                "media_id": "vid-1",
                "media_ids": ["vid-1", "vid-2", "vid-3"],
            }
        )

        logger = logging.getLogger("agent.nodes.video_nodes")
        with patch.object(logger, "info") as mock_info:
            restore_media_context(state, config)
            log_messages = [str(call) for call in mock_info.call_args_list]
            multi_video_log = [m for m in log_messages if "multi-video mode" in m]
            assert len(multi_video_log) == 1
            assert "vid-1" in multi_video_log[0]
            assert "vid-2" in multi_video_log[0]
            assert "vid-3" in multi_video_log[0]
            assert "3" in multi_video_log[0]

    def test_system_message_includes_video_titles(self):
        """Test that system message shows titles when video_titles is populated."""
        from agent.nodes.video_nodes import get_system_message

        state = {
            "video_context": {"media_id": "vid-1"},
            "media_id": "vid-1",
            "media_ids": ["vid-1", "vid-2"],
            "video_titles": {
                "vid-1": "Introduction to Python",
                "vid-2": "Advanced Machine Learning",
            },
        }

        msg = get_system_message(state)
        assert '"Introduction to Python"' in msg.content
        assert '"Advanced Machine Learning"' in msg.content
        assert "(id: vid-1)" in msg.content
        assert "(id: vid-2)" in msg.content
        assert "Video 1:" in msg.content
        assert "Video 2:" in msg.content

    def test_system_message_fallback_without_titles(self):
        """Test that system message falls back to raw IDs when no titles."""
        from agent.nodes.video_nodes import get_system_message

        state = {
            "video_context": {"media_id": "vid-1"},
            "media_id": "vid-1",
            "media_ids": ["vid-1", "vid-2"],
        }

        msg = get_system_message(state)
        # Without video_titles, should show raw IDs
        assert "Video 1: vid-1" in msg.content
        assert "Video 2: vid-2" in msg.content

    def test_system_message_multi_video_strategy_guidance(self):
        """Test that the multi-video prompt includes fallback strategy guidance."""
        from agent.nodes.video_nodes import get_system_message

        state = {
            "video_context": {"media_id": "vid-1"},
            "media_id": "vid-1",
            "media_ids": ["vid-1", "vid-2"],
        }

        msg = get_system_message(state)
        assert "get_library_overview" in msg.content
        assert "Fallback" in msg.content


class TestMultiVideoApiSchemas:
    """Test API schema validation for multi-video."""

    def test_chat_request_media_ids(self):
        """Test ChatRequest with media_ids."""
        from models.api_schemas import ChatRequest

        req = ChatRequest(
            message="Compare videos",
            media_id="vid-1",
            media_ids=["vid-1", "vid-2", "vid-3"],
        )
        ids = req.get_effective_media_ids()
        assert ids == ["vid-1", "vid-2", "vid-3"]

    def test_chat_request_media_ids_dedup(self):
        """Test deduplication in get_effective_media_ids."""
        from models.api_schemas import ChatRequest

        req = ChatRequest(
            message="test",
            media_id="vid-1",
            media_ids=["vid-1", "vid-2"],
        )
        ids = req.get_effective_media_ids()
        assert ids == ["vid-1", "vid-2"]

    def test_chat_request_no_media_ids(self):
        """Test get_effective_media_ids with only media_id."""
        from models.api_schemas import ChatRequest

        req = ChatRequest(message="test", media_id="vid-1")
        ids = req.get_effective_media_ids()
        assert ids == ["vid-1"]

    def test_chat_request_max_10(self):
        """Test max 10 videos validation at schema level."""
        import pydantic

        from models.api_schemas import ChatRequest

        with pytest.raises(pydantic.ValidationError):
            ChatRequest(
                message="test",
                media_ids=[f"v-{i}" for i in range(15)],
            )

    def test_agent_chat_request_media_ids(self):
        """Test AgentChatRequest with media_ids."""
        from models.api_schemas import AgentChatRequest

        req = AgentChatRequest(
            message="Compare",
            media_id="vid-1",
            media_ids=["vid-2", "vid-3"],
        )
        ids = req.get_effective_media_ids()
        assert "vid-1" in ids
        assert "vid-2" in ids
        assert "vid-3" in ids
