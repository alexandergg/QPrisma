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
        def __init__(self, *, call_id, output, id, status="completed"):
            self.call_id = call_id
            self.output = output
            self.id = id
            self.status = status

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
        """Extract (name, call_id, arguments_json) from a LangChain tool_call dict.

        Matches the real SDK behaviour: returns ``None`` for missing or
        unconvertible fields (no default fallbacks).
        """
        name = tool_call.get("name")
        call_id = tool_call.get("id")
        argument = None
        arguments_raw = tool_call.get("args")
        if isinstance(arguments_raw, str):
            argument = arguments_raw
        elif isinstance(arguments_raw, dict):
            argument = json.dumps(arguments_raw, ensure_ascii=False)
        return name, call_id, argument

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

    # Register in sys.modules; preserve existing azure/azure.ai namespace packages.
    # Import the real packages first (if installed) so namespace resolution
    # for sibling packages like azure.identity continues to work.
    try:
        import azure  # noqa: F811
    except ImportError:
        sys.modules["azure"] = _make_mod("azure")
    try:
        import azure.ai  # noqa: F811, F401
    except ImportError:
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


# ---------------------------------------------------------------------------
# Test: status field present on all emitted items
# ---------------------------------------------------------------------------


class TestStatusFieldPresent:
    """Verify all emitted items include status='completed'.

    The Foundry Responses API requires `status` on every item.  A missing
    `status` on FunctionToolCallOutputItemResource caused 100% failure for
    any evaluation query that triggered tool calls.
    """

    def test_tool_output_has_status_completed(self, converter):
        """FunctionToolCallOutputItemResource must have status='completed'."""
        from azure.ai.agentserver.core.models import projects as pm

        ai_msg = AIMessage(
            content="",
            tool_calls=[{"name": "search_video", "id": "call_s1", "args": {"q": "test"}}],
        )
        tool_msg = ToolMessage(content="result", tool_call_id="call_s1")
        output = [
            {"call_model": {"messages": [ai_msg]}},
            {"tools": {"messages": [tool_msg]}},
        ]
        items = converter.convert(output)
        func_outputs = [i for i in items if isinstance(i, pm.FunctionToolCallOutputItemResource)]
        assert len(func_outputs) == 1
        assert func_outputs[0].status == "completed"

    def test_all_items_have_status(self, converter):
        """Every item in a full flow must carry status='completed'."""
        output = [
            {"restore_media_context": {}},
            {
                "call_model": {
                    "messages": [
                        AIMessage(
                            content="",
                            tool_calls=[
                                {"name": "search", "id": "c1", "args": {}},
                                {"name": "get_frame", "id": "c2", "args": {}},
                            ],
                        )
                    ]
                }
            },
            {
                "tools": {
                    "messages": [
                        ToolMessage(content="found it", tool_call_id="c1"),
                        ToolMessage(content="frame ok", tool_call_id="c2"),
                    ]
                }
            },
            {"call_model": {"messages": [AIMessage(content="Here's the answer.")]}},
        ]
        items = converter.convert(output)
        assert len(items) == 5  # 2 FTC + 2 FTCO + 1 AM
        for item in items:
            assert hasattr(item, "status"), f"{type(item).__name__} missing 'status'"
            assert (
                item.status == "completed"
            ), f"{type(item).__name__} has status={item.status!r}, expected 'completed'"


# ---------------------------------------------------------------------------
# Phase 2 Tests: None field guards, per-item isolation, truncation
# ---------------------------------------------------------------------------


class TestToolCallMissingCallId:
    """Tool calls without ``id`` must be dropped (no synthetic IDs).

    Uses ``model_construct()`` to bypass LangChain's Pydantic validation,
    which normally requires ``id`` on every tool_call dict.  This simulates
    edge cases where the LLM returns malformed data or a custom provider
    populates ``tool_calls`` without full validation.
    """

    def test_missing_id_dropped(self, converter):
        from azure.ai.agentserver.core.models import projects as pm

        ai_msg = AIMessage.model_construct(
            content="",
            type="ai",
            tool_calls=[
                {"name": "search_video", "args": {"q": "test"}},  # no "id"
            ],
        )
        output = [{"call_model": {"messages": [ai_msg]}}]
        items = converter.convert(output)
        func_calls = [i for i in items if isinstance(i, pm.FunctionToolCallItemResource)]
        assert len(func_calls) == 0

    def test_missing_id_increments_error_count(self, converter):
        ai_msg = AIMessage.model_construct(
            content="",
            type="ai",
            tool_calls=[{"name": "search_video", "args": {"q": "test"}}],
        )
        output = [{"call_model": {"messages": [ai_msg]}}]
        converter.convert(output)
        assert converter._conversion_errors >= 1


class TestToolCallMissingName:
    """Tool calls without ``name`` must be dropped."""

    def test_missing_name_dropped(self, converter):
        from azure.ai.agentserver.core.models import projects as pm

        ai_msg = AIMessage.model_construct(
            content="",
            type="ai",
            tool_calls=[
                {"id": "call_1", "args": {"q": "test"}},  # no "name"
            ],
        )
        output = [{"call_model": {"messages": [ai_msg]}}]
        items = converter.convert(output)
        func_calls = [i for i in items if isinstance(i, pm.FunctionToolCallItemResource)]
        assert len(func_calls) == 0

    def test_missing_name_increments_error_count(self, converter):
        ai_msg = AIMessage.model_construct(
            content="",
            type="ai",
            tool_calls=[{"id": "call_1", "args": {"q": "test"}}],
        )
        output = [{"call_model": {"messages": [ai_msg]}}]
        converter.convert(output)
        assert converter._conversion_errors >= 1


class TestToolCallNoneArguments:
    """Tool calls with ``args=None`` → ``arguments`` defaults to ``"{}"``."""

    def test_args_none_defaults_to_empty_json(self, converter):
        from azure.ai.agentserver.core.models import projects as pm

        ai_msg = AIMessage.model_construct(
            content="",
            type="ai",
            tool_calls=[
                {"name": "search_video", "id": "call_1", "args": None},
            ],
        )
        output = [{"call_model": {"messages": [ai_msg]}}]
        items = converter.convert(output)
        func_calls = [i for i in items if isinstance(i, pm.FunctionToolCallItemResource)]
        assert len(func_calls) == 1
        assert func_calls[0].arguments == "{}"

    def test_args_list_type_defaults_to_empty_json(self, converter):
        """Non-dict/non-str args (e.g. list) also → empty JSON."""
        from azure.ai.agentserver.core.models import projects as pm

        ai_msg = AIMessage.model_construct(
            content="",
            type="ai",
            tool_calls=[
                {"name": "search_video", "id": "call_1", "args": [1, 2, 3]},
            ],
        )
        output = [{"call_model": {"messages": [ai_msg]}}]
        items = converter.convert(output)
        func_calls = [i for i in items if isinstance(i, pm.FunctionToolCallItemResource)]
        assert len(func_calls) == 1
        assert func_calls[0].arguments == "{}"


class TestPerItemIsolation:
    """One malformed tool call must not kill the rest."""

    def test_good_calls_survive_bad_sibling(self, converter):
        from azure.ai.agentserver.core.models import projects as pm

        ai_msg = AIMessage.model_construct(
            content="",
            type="ai",
            tool_calls=[
                {"name": "search_video", "id": "call_ok1", "args": {"q": "a"}},
                {"id": "call_bad", "args": {}},  # no name → dropped
                {"name": "get_frame", "id": "call_ok2", "args": {"ts": "1:00"}},
            ],
        )
        output = [{"call_model": {"messages": [ai_msg]}}]
        items = converter.convert(output)
        func_calls = [i for i in items if isinstance(i, pm.FunctionToolCallItemResource)]
        assert len(func_calls) == 2
        assert {fc.call_id for fc in func_calls} == {"call_ok1", "call_ok2"}


class TestToolOutputMissingCallId:
    """ToolMessage with ``tool_call_id=None`` must be dropped."""

    def test_none_tool_call_id_dropped(self, converter):
        from azure.ai.agentserver.core.models import projects as pm

        ai_msg = AIMessage(
            content="",
            tool_calls=[{"name": "search", "id": "call_a", "args": {}}],
        )
        # ToolMessage with tool_call_id=None (use model_construct to bypass validation)
        tool_msg = ToolMessage.model_construct(content="result", tool_call_id=None, type="tool")
        output = [
            {"call_model": {"messages": [ai_msg]}},
            {"tools": {"messages": [tool_msg]}},
        ]
        items = converter.convert(output)
        func_outputs = [i for i in items if isinstance(i, pm.FunctionToolCallOutputItemResource)]
        assert len(func_outputs) == 0


class TestToolOutputNoneContent:
    """ToolMessage with ``content=None`` → coerced to ``"{}"``."""

    def test_none_content_coerced(self, converter):
        from azure.ai.agentserver.core.models import projects as pm

        ai_msg = AIMessage(
            content="",
            tool_calls=[{"name": "search", "id": "call_c", "args": {}}],
        )
        # Use model_construct to bypass LangChain validation that coerces None→"None"
        tool_msg = ToolMessage.model_construct(
            content=None, tool_call_id="call_c", type="tool",
        )
        output = [
            {"call_model": {"messages": [ai_msg]}},
            {"tools": {"messages": [tool_msg]}},
        ]
        items = converter.convert(output)
        func_outputs = [i for i in items if isinstance(i, pm.FunctionToolCallOutputItemResource)]
        assert len(func_outputs) == 1
        assert func_outputs[0].output == "{}"

    def test_dict_content_serialized(self, converter):
        from azure.ai.agentserver.core.models import projects as pm

        ai_msg = AIMessage(
            content="",
            tool_calls=[{"name": "search", "id": "call_d", "args": {}}],
        )
        # Use model_construct so LangChain doesn't coerce dict to str()
        tool_msg = ToolMessage.model_construct(
            content={"results": [1, 2]}, tool_call_id="call_d", type="tool",
        )
        output = [
            {"call_model": {"messages": [ai_msg]}},
            {"tools": {"messages": [tool_msg]}},
        ]
        items = converter.convert(output)
        func_outputs = [i for i in items if isinstance(i, pm.FunctionToolCallOutputItemResource)]
        assert len(func_outputs) == 1
        assert json.loads(func_outputs[0].output) == {"results": [1, 2]}


class TestToolOutputTruncation:
    """Oversized tool outputs are truncated to ``_MAX_TOOL_OUTPUT_CHARS``."""

    def test_large_output_truncated(self, converter):
        from agent.hosted.state_converter import _MAX_TOOL_OUTPUT_CHARS
        from azure.ai.agentserver.core.models import projects as pm

        ai_msg = AIMessage(
            content="",
            tool_calls=[{"name": "get_transcript", "id": "call_t", "args": {}}],
        )
        huge_content = "x" * (_MAX_TOOL_OUTPUT_CHARS + 10_000)
        tool_msg = ToolMessage(content=huge_content, tool_call_id="call_t")
        output = [
            {"call_model": {"messages": [ai_msg]}},
            {"tools": {"messages": [tool_msg]}},
        ]
        items = converter.convert(output)
        func_outputs = [i for i in items if isinstance(i, pm.FunctionToolCallOutputItemResource)]
        assert len(func_outputs) == 1
        assert len(func_outputs[0].output) < len(huge_content)
        assert "[truncated" in func_outputs[0].output

    def test_small_output_not_truncated(self, converter):
        from agent.hosted.state_converter import _MAX_TOOL_OUTPUT_CHARS
        from azure.ai.agentserver.core.models import projects as pm

        ai_msg = AIMessage(
            content="",
            tool_calls=[{"name": "search", "id": "call_u", "args": {}}],
        )
        small_content = "short result"
        tool_msg = ToolMessage(content=small_content, tool_call_id="call_u")
        output = [
            {"call_model": {"messages": [ai_msg]}},
            {"tools": {"messages": [tool_msg]}},
        ]
        items = converter.convert(output)
        func_outputs = [i for i in items if isinstance(i, pm.FunctionToolCallOutputItemResource)]
        assert func_outputs[0].output == small_content


class TestNormalMultiToolCallFlow:
    """Normal multi-tool-call flow with valid data still works correctly."""

    def test_three_tool_calls_all_emitted(self, converter):
        from azure.ai.agentserver.core.models import projects as pm

        ai_msg = AIMessage(
            content="",
            tool_calls=[
                {"name": "search_video", "id": "c1", "args": {"q": "intro"}},
                {"name": "get_transcript", "id": "c2", "args": {"start": "0:00"}},
                {"name": "get_entities", "id": "c3", "args": {"type": "all"}},
            ],
        )
        tool_msgs = [
            ToolMessage(content="found intro", tool_call_id="c1"),
            ToolMessage(content="transcript text", tool_call_id="c2"),
            ToolMessage(content='{"entities":[]}', tool_call_id="c3"),
        ]
        output = [
            {"call_model": {"messages": [ai_msg]}},
            {"tools": {"messages": tool_msgs}},
            {"call_model": {"messages": [AIMessage(content="Summary answer")]}},
        ]
        items = converter.convert(output)
        func_calls = [i for i in items if isinstance(i, pm.FunctionToolCallItemResource)]
        func_outputs = [i for i in items if isinstance(i, pm.FunctionToolCallOutputItemResource)]
        assistant_msgs = [
            i for i in items if isinstance(i, pm.ResponsesAssistantMessageItemResource)
        ]
        assert len(func_calls) == 3
        assert len(func_outputs) == 3
        assert len(assistant_msgs) == 1
        assert assistant_msgs[0].content == "Summary answer"


class TestTruncationEnforcesLimit:
    """Truncated output must not exceed ``_MAX_TOOL_OUTPUT_CHARS``."""

    def test_truncated_length_within_limit(self, converter):
        from agent.hosted.state_converter import _MAX_TOOL_OUTPUT_CHARS
        from azure.ai.agentserver.core.models import projects as pm

        ai_msg = AIMessage(
            content="",
            tool_calls=[{"name": "get_transcript", "id": "call_lim", "args": {}}],
        )
        huge_content = "x" * (_MAX_TOOL_OUTPUT_CHARS + 50_000)
        tool_msg = ToolMessage(content=huge_content, tool_call_id="call_lim")
        output = [
            {"call_model": {"messages": [ai_msg]}},
            {"tools": {"messages": [tool_msg]}},
        ]
        items = converter.convert(output)
        func_outputs = [i for i in items if isinstance(i, pm.FunctionToolCallOutputItemResource)]
        assert len(func_outputs) == 1
        assert len(func_outputs[0].output) <= _MAX_TOOL_OUTPUT_CHARS


class TestFallbackSkippedForToolMessages:
    """Fallback to super().convert() must NOT run when tool messages caused the errors."""

    def test_all_malformed_tool_calls_no_fallback(self, converter):
        """When ALL tool calls are dropped (missing id+name), converter should
        return empty list rather than falling back to base converter."""
        ai_msg = AIMessage.model_construct(
            content="",
            tool_calls=[
                {"name": None, "id": None, "args": {}},
                {"name": None, "id": None, "args": {}},
            ],
        )
        tool_msg1 = ToolMessage.model_construct(content="result1", tool_call_id=None)
        tool_msg2 = ToolMessage.model_construct(content="result2", tool_call_id=None)
        output = [
            {"call_model": {"messages": [ai_msg]}},
            {"tools": {"messages": [tool_msg1, tool_msg2]}},
        ]
        items = converter.convert(output)
        # All items should be dropped — no fallback to base converter
        assert items == []
        assert converter._conversion_errors > 0
