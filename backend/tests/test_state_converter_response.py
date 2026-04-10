"""Tests for QPrismaNonStreamResponseConverter.

Validates the custom response converter that fixes multi-tool-call support,
orphan-output guarding, and node-level filtering for the Foundry Responses API.
"""

from __future__ import annotations

import json
import sys
import types
from enum import Enum
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

# ---------------------------------------------------------------------------
# Mock azure.ai.agentserver SDK when the pre-release package is unavailable
# ---------------------------------------------------------------------------
# The azure-ai-agentserver-langgraph SDK is a pre-release (>=1.0.0b17) and
# may not be installed in CI test environments.  state_converter.py has
# top-level imports from this package, so we register lightweight stub
# modules in sys.modules before any fixture triggers those imports.

if "azure.ai.agentserver" not in sys.modules:

    class _ItemResource:
        """Base class for Responses API item resources."""

    class _FunctionToolCallItemResource(_ItemResource):
        def __init__(self, *, call_id, name, arguments, id, status="completed"):
            self.call_id = call_id
            self.name = name
            self.arguments = arguments
            self.id = id
            self.status = status

    class _FunctionToolCallOutputItemResource(_ItemResource):
        def __init__(self, *, call_id, output, id):
            self.call_id = call_id
            self.output = output
            self.id = id

    class _ResponsesAssistantMessageItemResource(_ItemResource):
        def __init__(self, *, content, id, status="completed"):
            self.content = content
            self.id = id
            self.status = status

    class _ResponsesMessageRole(Enum):
        ASSISTANT = "assistant"
        USER = "user"

    class _LanggraphRunContext:
        pass

    class _GraphInputArguments(dict):
        pass

    class _ResponseAPIDefaultConverter:
        def __init__(self, *, graph=None, create_non_stream_response_converter=None):
            self._graph = graph
            self._create_non_stream_response_converter = create_non_stream_response_converter

        def _create_human_in_the_loop_helper(self, context):
            return MagicMock()

        async def convert_request(self, context):
            return {"input": {}, "config": {}}

    class _ResponseAPIMessagesNonStreamResponseConverter:
        def __init__(self, context, hitl_helper):
            self.context = context
            self.hitl_helper = hitl_helper

        def convert(self, output):
            return []

        def convert_MessageContent(self, content, *, role=None):
            return content

    def _extract_function_call(tool_call):
        """Extract (name, call_id, arguments_json) from a LangChain tool_call dict."""
        name = tool_call.get("name", "")
        call_id = tool_call.get("id", "")
        args = tool_call.get("args", {})
        return name, call_id, json.dumps(args, ensure_ascii=False)

    _INTERRUPT_NODE_NAME = "__interrupt__"

    def _make_mod(name, attrs=None):
        mod = types.ModuleType(name)
        mod.__path__ = []  # mark as package so sub-imports work
        mod.__package__ = name
        if attrs:
            for k, v in attrs.items():
                setattr(mod, k, v)
        return mod

    _projects_mod = _make_mod(
        "azure.ai.agentserver.core.models.projects",
        {
            "ItemResource": _ItemResource,
            "FunctionToolCallItemResource": _FunctionToolCallItemResource,
            "FunctionToolCallOutputItemResource": _FunctionToolCallOutputItemResource,
            "ResponsesAssistantMessageItemResource": _ResponsesAssistantMessageItemResource,
            "ResponsesMessageRole": _ResponsesMessageRole,
        },
    )

    _agentserver_mods = {
        "azure.ai.agentserver": _make_mod("azure.ai.agentserver"),
        "azure.ai.agentserver.core": _make_mod("azure.ai.agentserver.core"),
        "azure.ai.agentserver.core.models": _make_mod(
            "azure.ai.agentserver.core.models", {"projects": _projects_mod}
        ),
        "azure.ai.agentserver.core.models.projects": _projects_mod,
        "azure.ai.agentserver.langgraph": _make_mod(
            "azure.ai.agentserver.langgraph",
            {"LanggraphRunContext": _LanggraphRunContext},
        ),
        "azure.ai.agentserver.langgraph.models": _make_mod("azure.ai.agentserver.langgraph.models"),
        "azure.ai.agentserver.langgraph.models.response_api_converter": _make_mod(
            "azure.ai.agentserver.langgraph.models.response_api_converter",
            {"GraphInputArguments": _GraphInputArguments},
        ),
        "azure.ai.agentserver.langgraph.models.response_api_default_converter": _make_mod(
            "azure.ai.agentserver.langgraph.models.response_api_default_converter",
            {"ResponseAPIDefaultConverter": _ResponseAPIDefaultConverter},
        ),
        "azure.ai.agentserver.langgraph.models.response_api_non_stream_response_converter": _make_mod(
            "azure.ai.agentserver.langgraph.models.response_api_non_stream_response_converter",
            {
                "INTERRUPT_NODE_NAME": _INTERRUPT_NODE_NAME,
                "ResponseAPIMessagesNonStreamResponseConverter": _ResponseAPIMessagesNonStreamResponseConverter,
            },
        ),
        "azure.ai.agentserver.langgraph.models.utils": _make_mod(
            "azure.ai.agentserver.langgraph.models.utils",
            {"extract_function_call": _extract_function_call},
        ),
    }

    # Wire parent→child submodule attributes
    _agentserver_mods["azure.ai.agentserver"].core = _agentserver_mods["azure.ai.agentserver.core"]
    _agentserver_mods["azure.ai.agentserver"].langgraph = _agentserver_mods[
        "azure.ai.agentserver.langgraph"
    ]
    _agentserver_mods["azure.ai.agentserver.core"].models = _agentserver_mods[
        "azure.ai.agentserver.core.models"
    ]
    _agentserver_mods["azure.ai.agentserver.langgraph"].models = _agentserver_mods[
        "azure.ai.agentserver.langgraph.models"
    ]

    # Register in sys.modules; preserve existing azure/azure.ai namespace packages
    if "azure" not in sys.modules:
        sys.modules["azure"] = _make_mod("azure")
    if "azure.ai" not in sys.modules:
        sys.modules["azure.ai"] = _make_mod("azure.ai")
    sys.modules["azure"].ai = sys.modules["azure.ai"]
    sys.modules["azure.ai"].agentserver = _agentserver_mods["azure.ai.agentserver"]
    sys.modules.update(_agentserver_mods)

# ---------------------------------------------------------------------------
# Lightweight stubs for azure.ai.agentserver types
# ---------------------------------------------------------------------------


class _IdGenerator:
    """Deterministic ID generator for tests."""

    def __init__(self):
        self._counter = 0

    def _next(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}_{self._counter}"

    def generate_function_call_id(self) -> str:
        return self._next("fc")

    def generate_function_output_id(self) -> str:
        return self._next("fo")

    def generate_message_id(self) -> str:
        return self._next("msg")


def _make_context() -> MagicMock:
    ctx = MagicMock()
    ctx.agent_run.id_generator = _IdGenerator()
    return ctx


def _make_hitl_helper() -> MagicMock:
    helper = MagicMock()
    helper.convert_interrupts.return_value = []
    return helper


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def converter():
    """Create a QPrismaNonStreamResponseConverter with mocked dependencies."""
    from agent.hosted.state_converter import QPrismaNonStreamResponseConverter

    ctx = _make_context()
    hitl = _make_hitl_helper()
    return QPrismaNonStreamResponseConverter(ctx, hitl)


# ---------------------------------------------------------------------------
# Test: assistant-only response (no tool calls)
# ---------------------------------------------------------------------------


class TestAssistantOnlyResponse:
    def test_simple_text_response(self, converter):
        """AIMessage with text only → single assistant message item."""
        from azure.ai.agentserver.core.models import projects as pm

        output = [{"call_model": {"messages": [AIMessage(content="Hello!")]}}]
        items = converter.convert(output)
        assert len(items) == 1
        assert isinstance(items[0], pm.ResponsesAssistantMessageItemResource)

    def test_empty_content_still_emitted(self, converter):
        """AIMessage with empty content → still emits assistant item."""
        from azure.ai.agentserver.core.models import projects as pm

        output = [{"call_model": {"messages": [AIMessage(content="")]}}]
        items = converter.convert(output)
        assert len(items) == 1
        assert isinstance(items[0], pm.ResponsesAssistantMessageItemResource)


# ---------------------------------------------------------------------------
# Test: multi-tool-call support
# ---------------------------------------------------------------------------


class TestMultiToolCall:
    def test_all_tool_calls_emitted(self, converter):
        """AIMessage with 3 tool_calls → all 3 emitted as FunctionToolCallItemResource."""
        from azure.ai.agentserver.core.models import projects as pm

        ai_msg = AIMessage(
            content="",
            tool_calls=[
                {"name": "search_video", "id": "call_1", "args": {"q": "intro"}},
                {"name": "get_frame", "id": "call_2", "args": {"ts": "00:01"}},
                {"name": "get_entities", "id": "call_3", "args": {"type": "person"}},
            ],
        )
        tool_msgs = [
            ToolMessage(content="found: intro scene", tool_call_id="call_1"),
            ToolMessage(content="frame at 00:01", tool_call_id="call_2"),
            ToolMessage(content="person: Alice", tool_call_id="call_3"),
        ]
        output = [
            {"call_model": {"messages": [ai_msg]}},
            {"tools": {"messages": tool_msgs}},
        ]
        items = converter.convert(output)

        func_calls = [i for i in items if isinstance(i, pm.FunctionToolCallItemResource)]
        func_outputs = [i for i in items if isinstance(i, pm.FunctionToolCallOutputItemResource)]
        assert len(func_calls) == 3
        assert len(func_outputs) == 3
        assert {fc.call_id for fc in func_calls} == {"call_1", "call_2", "call_3"}
        assert {fo.call_id for fo in func_outputs} == {"call_1", "call_2", "call_3"}

    def test_single_tool_call_still_works(self, converter):
        """AIMessage with 1 tool_call → 1 call + 1 output."""
        from azure.ai.agentserver.core.models import projects as pm

        ai_msg = AIMessage(
            content="",
            tool_calls=[{"name": "search_video", "id": "call_a", "args": {"q": "test"}}],
        )
        tool_msg = ToolMessage(content="result", tool_call_id="call_a")
        output = [
            {"call_model": {"messages": [ai_msg]}},
            {"tools": {"messages": [tool_msg]}},
        ]
        items = converter.convert(output)
        func_calls = [i for i in items if isinstance(i, pm.FunctionToolCallItemResource)]
        func_outputs = [i for i in items if isinstance(i, pm.FunctionToolCallOutputItemResource)]
        assert len(func_calls) == 1
        assert len(func_outputs) == 1


# ---------------------------------------------------------------------------
# Test: orphan-output guarding
# ---------------------------------------------------------------------------


class TestOrphanOutputGuard:
    def test_orphaned_tool_output_dropped(self, converter):
        """ToolMessage with no matching tool call → dropped."""

        tool_msg = ToolMessage(content="orphan result", tool_call_id="call_orphan")
        output = [{"tools": {"messages": [tool_msg]}}]
        items = converter.convert(output)
        assert len(items) == 0

    def test_mixed_valid_and_orphan(self, converter):
        """Valid tool output kept, orphan dropped."""
        from azure.ai.agentserver.core.models import projects as pm

        ai_msg = AIMessage(
            content="",
            tool_calls=[{"name": "search", "id": "call_good", "args": {}}],
        )
        output = [
            {"call_model": {"messages": [ai_msg]}},
            {
                "tools": {
                    "messages": [
                        ToolMessage(content="good", tool_call_id="call_good"),
                        ToolMessage(content="orphan", tool_call_id="call_missing"),
                    ]
                }
            },
        ]
        items = converter.convert(output)
        func_outputs = [i for i in items if isinstance(i, pm.FunctionToolCallOutputItemResource)]
        assert len(func_outputs) == 1
        assert func_outputs[0].call_id == "call_good"


# ---------------------------------------------------------------------------
# Test: node-level filtering
# ---------------------------------------------------------------------------


class TestNodeFiltering:
    def test_restore_media_context_skipped(self, converter):
        """Messages from restore_media_context are never emitted."""
        output = [
            {
                "restore_media_context": {
                    "messages": [
                        HumanMessage(content="clean question"),
                        AIMessage(content="previous answer"),
                    ]
                }
            },
            {"call_model": {"messages": [AIMessage(content="new answer")]}},
        ]
        items = converter.convert(output)
        assert len(items) == 1  # only the new answer

    def test_human_message_in_other_node_filtered(self, converter):
        """HumanMessage from any node is filtered as defense-in-depth."""
        output = [
            {
                "some_node": {
                    "messages": [
                        HumanMessage(content="injected user msg"),
                        AIMessage(content="agent response"),
                    ]
                }
            },
        ]
        items = converter.convert(output)
        assert len(items) == 1  # only the AIMessage

    def test_system_message_filtered(self, converter):
        """SystemMessage from any node is filtered."""
        output = [
            {
                "call_model": {
                    "messages": [
                        SystemMessage(content="system prompt"),
                        AIMessage(content="real response"),
                    ]
                }
            },
        ]
        items = converter.convert(output)
        assert len(items) == 1

    def test_update_context_no_messages(self, converter):
        """update_context returns non-message state → no items emitted."""
        output = [{"update_context": {"sources": ["src1"], "video_context": {}}}]
        items = converter.convert(output)
        assert len(items) == 0


# ---------------------------------------------------------------------------
# Test: AIMessage with both content and tool_calls
# ---------------------------------------------------------------------------


class TestContentPlusToolCalls:
    def test_text_plus_tool_calls(self, converter):
        """AIMessage with both text content and tool_calls → both emitted."""
        from azure.ai.agentserver.core.models import projects as pm

        ai_msg = AIMessage(
            content="Let me search for that.",
            tool_calls=[{"name": "search_video", "id": "call_x", "args": {"q": "topic"}}],
        )
        output = [{"call_model": {"messages": [ai_msg]}}]
        items = converter.convert(output)
        func_calls = [i for i in items if isinstance(i, pm.FunctionToolCallItemResource)]
        assistant_msgs = [
            i for i in items if isinstance(i, pm.ResponsesAssistantMessageItemResource)
        ]
        assert len(func_calls) == 1
        assert len(assistant_msgs) == 1

    def test_whitespace_only_content_not_emitted(self, converter):
        """AIMessage with whitespace-only content + tool_calls → only tool calls."""
        from azure.ai.agentserver.core.models import projects as pm

        ai_msg = AIMessage(
            content="   ",
            tool_calls=[{"name": "search", "id": "call_y", "args": {}}],
        )
        output = [{"call_model": {"messages": [ai_msg]}}]
        items = converter.convert(output)
        func_calls = [i for i in items if isinstance(i, pm.FunctionToolCallItemResource)]
        assistant_msgs = [
            i for i in items if isinstance(i, pm.ResponsesAssistantMessageItemResource)
        ]
        assert len(func_calls) == 1
        assert len(assistant_msgs) == 0


# ---------------------------------------------------------------------------
# Test: HITL interrupt support
# ---------------------------------------------------------------------------


class TestHITLInterrupts:
    def test_interrupt_node_delegates_to_hitl(self, converter):
        """__interrupt__ node output is delegated to HITL helper."""
        interrupt_data = {"type": "approval", "message": "approve?"}
        output = [{"__interrupt__": interrupt_data}]
        converter.convert(output)
        converter.hitl_helper.convert_interrupts.assert_called_once_with(interrupt_data)


# ---------------------------------------------------------------------------
# Test: invalid input handling
# ---------------------------------------------------------------------------


class TestInvalidInput:
    def test_non_list_raises_value_error(self, converter):
        """Non-list output raises ValueError."""
        with pytest.raises(ValueError, match="Expected a list"):
            converter.convert({"not": "a list"})

    def test_empty_list_returns_empty(self, converter):
        """Empty list → empty items."""
        items = converter.convert([])
        assert items == []


# ---------------------------------------------------------------------------
# Test: full realistic QPrisma flow
# ---------------------------------------------------------------------------


class TestRealisticQPrismaFlow:
    def test_general_query_flow(self, converter):
        """General query: restore_media_context(no messages) → call_model → response."""
        from azure.ai.agentserver.core.models import projects as pm

        output = [
            {"restore_media_context": {}},
            {"call_model": {"messages": [AIMessage(content="I can help with videos.")]}},
            {"update_context": {"sources": [], "video_context": None}},
        ]
        items = converter.convert(output)
        assert len(items) == 1
        assert isinstance(items[0], pm.ResponsesAssistantMessageItemResource)

    def test_video_query_with_multi_tool_calls(self, converter):
        """Video query: context → model(3 tools) → tool results → model(answer)."""
        from azure.ai.agentserver.core.models import projects as pm

        output = [
            {
                "restore_media_context": {
                    "messages": [HumanMessage(content="What happens at 2:30?")]
                }
            },
            {
                "call_model": {
                    "messages": [
                        AIMessage(
                            content="",
                            tool_calls=[
                                {"name": "search_video", "id": "c1", "args": {"q": "2:30"}},
                                {"name": "get_frame", "id": "c2", "args": {"ts": "2:30"}},
                            ],
                        )
                    ]
                }
            },
            {
                "tools": {
                    "messages": [
                        ToolMessage(content="scene at 2:30: presentation", tool_call_id="c1"),
                        ToolMessage(content="frame: slide 5", tool_call_id="c2"),
                    ]
                }
            },
            {
                "call_model": {
                    "messages": [
                        AIMessage(content="At 2:30, there's a presentation showing slide 5.")
                    ]
                }
            },
            {"update_context": {"sources": ["s1"], "video_context": {"current": "v1"}}},
        ]
        items = converter.convert(output)
        func_calls = [i for i in items if isinstance(i, pm.FunctionToolCallItemResource)]
        func_outputs = [i for i in items if isinstance(i, pm.FunctionToolCallOutputItemResource)]
        assistant_msgs = [
            i for i in items if isinstance(i, pm.ResponsesAssistantMessageItemResource)
        ]
        assert len(func_calls) == 2
        assert len(func_outputs) == 2
        assert len(assistant_msgs) == 1
        assert {fc.call_id for fc in func_calls} == {"c1", "c2"}
