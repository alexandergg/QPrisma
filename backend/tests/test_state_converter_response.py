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
        """AIMessage with both text content and tool_calls → only tool calls
        emitted (no interleaved assistant message — Foundry requires mutual
        exclusivity between function calls and assistant messages)."""
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
        assert len(assistant_msgs) == 0

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
            content=None,
            tool_call_id="call_c",
            type="tool",
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
            content={"results": [1, 2]},
            tool_call_id="call_d",
            type="tool",
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


# ---------------------------------------------------------------------------
# Test: AIMessage with tool_calls AND text content → NO assistant message
# ---------------------------------------------------------------------------


class TestNoAssistantMessageOnToolCallTurn:
    """Verify that AIMessage with both tool_calls and text content emits
    ONLY FunctionToolCallItemResource items — no interleaved assistant message.
    This was the PRIMARY root cause of Foundry HTTP 400 errors."""

    def test_tool_calls_with_content_no_assistant_message(self, converter):
        """AIMessage with 'Let me search...' + tool_calls → only function calls emitted."""
        from azure.ai.agentserver.core.models import projects as pm

        ai_msg = AIMessage(
            content="Let me search for that information...",
            tool_calls=[
                {"name": "search_video", "id": "call_1", "args": {"query": "test"}},
                {"name": "get_transcript", "id": "call_2", "args": {"media_id": "v1"}},
            ],
        )
        tool_msg1 = ToolMessage(content="search result", tool_call_id="call_1")
        tool_msg2 = ToolMessage(content="transcript data", tool_call_id="call_2")
        final = AIMessage(content="Here is the summary.")

        output = [
            {"call_model": {"messages": [ai_msg]}},
            {"tools": {"messages": [tool_msg1, tool_msg2]}},
            {"call_model": {"messages": [final]}},
        ]
        items = converter.convert(output)

        # Should NOT contain an assistant message for the intermediate "Let me search..." text
        assistant_msgs = [
            i for i in items if isinstance(i, pm.ResponsesAssistantMessageItemResource)
        ]
        func_calls = [i for i in items if isinstance(i, pm.FunctionToolCallItemResource)]
        func_outputs = [i for i in items if isinstance(i, pm.FunctionToolCallOutputItemResource)]

        assert len(func_calls) == 2
        assert len(func_outputs) == 2
        # Only the final answer should be an assistant message
        assert len(assistant_msgs) == 1
        assert "summary" in assistant_msgs[0].content.lower()

    def test_tool_calls_with_whitespace_content_no_message(self, converter):
        """AIMessage with whitespace-only content + tool_calls → still no assistant message."""
        from azure.ai.agentserver.core.models import projects as pm

        ai_msg = AIMessage(
            content="   \n  ",
            tool_calls=[{"name": "search", "id": "call_x", "args": {}}],
        )
        tool_msg = ToolMessage(content="result", tool_call_id="call_x")
        final = AIMessage(content="Done.")

        output = [
            {"call_model": {"messages": [ai_msg]}},
            {"tools": {"messages": [tool_msg]}},
            {"call_model": {"messages": [final]}},
        ]
        items = converter.convert(output)

        assistant_msgs = [
            i for i in items if isinstance(i, pm.ResponsesAssistantMessageItemResource)
        ]
        assert len(assistant_msgs) == 1  # only final answer


# ---------------------------------------------------------------------------
# Test: QPRISMA_CONTEXT extraction with nested brackets (multi-video)
# ---------------------------------------------------------------------------


class TestContextExtractionNestedBrackets:
    """Verify that _extract_qprisma_context handles JSON with nested arrays/objects."""

    def test_multi_video_media_ids_array(self):
        from agent.hosted.state_converter import _extract_qprisma_context

        text = '[QPRISMA_CONTEXT:{"media_ids":["id1","id2"],"user_id":"u1"}]\nQuery text'
        metadata, clean_query = _extract_qprisma_context(text)
        assert metadata == {"media_ids": ["id1", "id2"], "user_id": "u1"}
        assert clean_query == "Query text"

    def test_single_video_simple(self):
        from agent.hosted.state_converter import _extract_qprisma_context

        text = '[QPRISMA_CONTEXT:{"media_id":"v1","user_id":"u1"}]\nWhat is this?'
        metadata, clean_query = _extract_qprisma_context(text)
        assert metadata == {"media_id": "v1", "user_id": "u1"}
        assert clean_query == "What is this?"

    def test_no_prefix_returns_empty(self):
        from agent.hosted.state_converter import _extract_qprisma_context

        text = "Just a plain query"
        metadata, clean_query = _extract_qprisma_context(text)
        assert metadata == {}
        assert clean_query == "Just a plain query"

    def test_nested_objects_in_context(self):
        from agent.hosted.state_converter import _extract_qprisma_context

        text = '[QPRISMA_CONTEXT:{"media_id":"v1","opts":{"lang":"en"}}]\nQuery'
        metadata, clean_query = _extract_qprisma_context(text)
        assert metadata == {"media_id": "v1", "opts": {"lang": "en"}}
        assert clean_query == "Query"

    def test_malformed_json_returns_empty(self):
        from agent.hosted.state_converter import _extract_qprisma_context

        text = "[QPRISMA_CONTEXT:{bad json}]\nQuery"
        metadata, clean_query = _extract_qprisma_context(text)
        assert metadata == {}
        assert clean_query == "[QPRISMA_CONTEXT:{bad json}]\nQuery"

    def test_compact_json_no_spaces(self):
        """Compact JSON (from generate_eval_data) parses correctly."""
        from agent.hosted.state_converter import _extract_qprisma_context

        text = '[QPRISMA_CONTEXT:{"media_id":"fc7e2e08","user_id":"f9156056"}]\nSummarize.'
        metadata, clean_query = _extract_qprisma_context(text)
        assert metadata["media_id"] == "fc7e2e08"
        assert clean_query == "Summarize."


# ---------------------------------------------------------------------------
# Test: Content sanitization strips control characters
# ---------------------------------------------------------------------------


class TestContentSanitization:
    """Verify _sanitize_tool_output strips control chars but keeps \\n, \\t."""

    def test_strips_null_bytes(self):
        from agent.hosted.state_converter import _sanitize_tool_output

        assert _sanitize_tool_output("hello\x00world") == "helloworld"

    def test_keeps_newlines_and_tabs(self):
        from agent.hosted.state_converter import _sanitize_tool_output

        text = "line1\nline2\ttab"
        assert _sanitize_tool_output(text) == text

    def test_strips_mixed_control_chars(self):
        from agent.hosted.state_converter import _sanitize_tool_output

        text = "abc\x01\x02\x03def\x7fghi\n\tjkl"
        assert _sanitize_tool_output(text) == "abcdefghi\n\tjkl"

    def test_clean_string_unchanged(self):
        from agent.hosted.state_converter import _sanitize_tool_output

        text = '{"result": "all good", "count": 42}'
        assert _sanitize_tool_output(text) == text


# ---------------------------------------------------------------------------
# Test: response_mode="final_answer" strips tool items
# ---------------------------------------------------------------------------


class TestFinalAnswerResponseMode:
    """Verify that response_mode='final_answer' strips tool-call and
    tool-output items, keeping only assistant messages.

    This mode allows Foundry's evaluation pipeline to save responses
    without encountering 'invalid format' errors from tool-related items.
    """

    @pytest.fixture()
    def final_answer_converter(self):
        """Converter in final_answer mode."""
        from agent.hosted.state_converter import QPrismaNonStreamResponseConverter

        ctx = _make_context()
        hitl = _make_hitl_helper()
        return QPrismaNonStreamResponseConverter(ctx, hitl, response_mode="final_answer")

    def test_strips_tool_items_keeps_assistant(self, final_answer_converter):
        """Multi-tool response → only the final assistant message survives."""
        from azure.ai.agentserver.core.models import projects as pm

        ai_tool_msg = AIMessage(
            content="",
            tool_calls=[
                {"name": "search_video", "id": "call_1", "args": {"query": "summary"}},
                {"name": "get_summary", "id": "call_2", "args": {}},
            ],
        )
        tool_out_1 = ToolMessage(content="search results...", tool_call_id="call_1")
        tool_out_2 = ToolMessage(content="video summary...", tool_call_id="call_2")
        final_msg = AIMessage(content="Here is the summary of the video.")

        output = [
            {"call_model": {"messages": [ai_tool_msg]}},
            {"tools": {"messages": [tool_out_1, tool_out_2]}},
            {"call_model": {"messages": [final_msg]}},
        ]
        items = final_answer_converter.convert(output)

        assert len(items) == 1
        assert isinstance(items[0], pm.ResponsesAssistantMessageItemResource)
        assert items[0].content == "Here is the summary of the video."

    def test_assistant_only_response_unchanged(self, final_answer_converter):
        """Response with only an assistant message → preserved as-is."""
        from azure.ai.agentserver.core.models import projects as pm

        output = [{"call_model": {"messages": [AIMessage(content="I can help!")]}}]
        items = final_answer_converter.convert(output)

        assert len(items) == 1
        assert isinstance(items[0], pm.ResponsesAssistantMessageItemResource)
        assert items[0].content == "I can help!"

    def test_full_mode_preserves_all_items(self, converter):
        """Default 'full' mode keeps tool-call and tool-output items."""
        from azure.ai.agentserver.core.models import projects as pm

        ai_tool_msg = AIMessage(
            content="",
            tool_calls=[{"name": "search_video", "id": "call_1", "args": {}}],
        )
        tool_out = ToolMessage(content="results", tool_call_id="call_1")
        final_msg = AIMessage(content="Done.")

        output = [
            {"call_model": {"messages": [ai_tool_msg]}},
            {"tools": {"messages": [tool_out]}},
            {"call_model": {"messages": [final_msg]}},
        ]
        items = converter.convert(output)

        tool_calls = [i for i in items if isinstance(i, pm.FunctionToolCallItemResource)]
        tool_outputs = [i for i in items if isinstance(i, pm.FunctionToolCallOutputItemResource)]
        messages = [i for i in items if isinstance(i, pm.ResponsesAssistantMessageItemResource)]
        assert len(tool_calls) == 1
        assert len(tool_outputs) == 1
        assert len(messages) == 1

    def test_empty_output_returns_empty(self, final_answer_converter):
        """Empty graph output → empty result even in final_answer mode."""
        items = final_answer_converter.convert([])
        assert items == []

    def test_invalid_mode_falls_back_to_full(self):
        """Unknown response_mode values fall back to 'full' (all items)."""
        from agent.hosted.state_converter import QPrismaNonStreamResponseConverter
        from azure.ai.agentserver.core.models import projects as pm

        ctx = _make_context()
        hitl = _make_hitl_helper()
        conv = QPrismaNonStreamResponseConverter(ctx, hitl, response_mode="unknown_mode")

        ai_tool_msg = AIMessage(
            content="",
            tool_calls=[{"name": "search_video", "id": "call_1", "args": {}}],
        )
        tool_out = ToolMessage(content="results", tool_call_id="call_1")
        final_msg = AIMessage(content="Answer.")

        output = [
            {"call_model": {"messages": [ai_tool_msg]}},
            {"tools": {"messages": [tool_out]}},
            {"call_model": {"messages": [final_msg]}},
        ]
        items = conv.convert(output)
        # Should behave like 'full' mode — all items present
        assert any(isinstance(i, pm.FunctionToolCallItemResource) for i in items)
        assert any(isinstance(i, pm.FunctionToolCallOutputItemResource) for i in items)
        assert any(isinstance(i, pm.ResponsesAssistantMessageItemResource) for i in items)


# ---------------------------------------------------------------------------
# Test: final_answer non-empty guarantee (v46 regression — Foundry 400 fix)
# ---------------------------------------------------------------------------


class TestFinalAnswerNonEmptyGuarantee:
    """Regression tests for the Foundry 400 "Response could not be saved due
    to invalid format" failures observed on v45 for media-context queries.

    The hosted agent graph ``call_model → tools → call_model → … → END``
    can, under certain conditions, end without producing a tool-free
    ``AIMessage`` with non-empty text (e.g. the final step is a tool call,
    ``max_iterations`` is reached, or the LLM returns empty content).  In
    ``response_mode="final_answer"`` the converter used to strip all tool
    items and hand Foundry an empty list, which the Responses API rejects
    with HTTP 400.  The converter now guarantees at least one
    ``ResponsesAssistantMessageItemResource`` in the output whenever the
    graph actually ran.
    """

    @pytest.fixture()
    def final_answer_converter(self):
        from agent.hosted.state_converter import QPrismaNonStreamResponseConverter

        ctx = _make_context()
        hitl = _make_hitl_helper()
        return QPrismaNonStreamResponseConverter(ctx, hitl, response_mode="final_answer")

    def test_graph_ends_on_tool_call_falls_back_to_preamble(self, final_answer_converter):
        """Graph ends on AIMessage(tool_calls + preamble) → preamble surfaced.

        Simulates the common Anthropic pattern where the final assistant
        message carries both narrative text and tool_calls.  Without the
        fix, stripping leaves zero items; with the fix, the preamble is
        used as the final answer.
        """
        from azure.ai.agentserver.core.models import projects as pm

        ai_with_preamble = AIMessage(
            content="Based on the video, here are the key points.",
            tool_calls=[{"name": "search_video", "id": "call_x", "args": {}}],
        )
        output = [{"call_model": {"messages": [ai_with_preamble]}}]
        items = final_answer_converter.convert(output)

        assert len(items) == 1
        assert isinstance(items[0], pm.ResponsesAssistantMessageItemResource)
        assert "Based on the video" in items[0].content

    def test_all_ai_messages_empty_falls_back_to_placeholder(self, final_answer_converter):
        """No AIMessage has text anywhere → placeholder synthesized, not empty."""
        from azure.ai.agentserver.core.models import projects as pm

        ai_tool = AIMessage(content="", tool_calls=[{"name": "search", "id": "c1", "args": {}}])
        output = [
            {"call_model": {"messages": [ai_tool]}},
            {"tools": {"messages": [ToolMessage(content="r", tool_call_id="c1")]}},
        ]
        items = final_answer_converter.convert(output)

        assert len(items) == 1
        assert isinstance(items[0], pm.ResponsesAssistantMessageItemResource)
        # Placeholder content is non-empty — Foundry can persist it.
        assert isinstance(items[0].content, str) and len(items[0].content) > 0

    def test_multiple_assistant_messages_collapsed_to_last(self, final_answer_converter):
        """Two assistant messages survive → only the last is kept.

        Multiple ``ResponsesAssistantMessageItemResource`` in a single
        response have been observed to trigger Foundry 400s.
        """
        from azure.ai.agentserver.core.models import projects as pm

        output = [
            {"call_model": {"messages": [AIMessage(content="First thought.")]}},
            {"call_model": {"messages": [AIMessage(content="Final answer here.")]}},
        ]
        items = final_answer_converter.convert(output)

        assert len(items) == 1
        assert isinstance(items[0], pm.ResponsesAssistantMessageItemResource)
        assert items[0].content == "Final answer here."

    def test_tool_loop_with_final_message_unchanged(self, final_answer_converter):
        """Canonical happy path: tool loop → final AIMessage → that message kept.

        Ensures the non-empty guarantee does not interfere with normal
        operation — the pre-existing test still holds under the new code.
        """
        from azure.ai.agentserver.core.models import projects as pm

        output = [
            {
                "call_model": {
                    "messages": [
                        AIMessage(
                            content="",
                            tool_calls=[{"name": "s", "id": "c1", "args": {}}],
                        )
                    ]
                }
            },
            {"tools": {"messages": [ToolMessage(content="r", tool_call_id="c1")]}},
            {"call_model": {"messages": [AIMessage(content="Video summary: …")]}},
        ]
        items = final_answer_converter.convert(output)

        assert len(items) == 1
        assert isinstance(items[0], pm.ResponsesAssistantMessageItemResource)
        assert items[0].content == "Video summary: …"

    def test_list_content_preamble_flattened(self, final_answer_converter):
        """AIMessage with list-style content (Anthropic blocks) is flattened."""
        from azure.ai.agentserver.core.models import projects as pm

        ai_with_blocks = AIMessage(
            content=[
                {"type": "text", "text": "Checking the transcript…"},
                {"type": "tool_use", "id": "c1", "name": "s", "input": {}},
            ],
            tool_calls=[{"name": "s", "id": "c1", "args": {}}],
        )
        output = [{"call_model": {"messages": [ai_with_blocks]}}]
        items = final_answer_converter.convert(output)

        assert len(items) == 1
        assert isinstance(items[0], pm.ResponsesAssistantMessageItemResource)
        assert "Checking the transcript" in items[0].content

    def test_final_ai_message_empty_string_replaced_with_fallback(self, final_answer_converter):
        """Final AIMessage with ``content=""`` → surviving empty item is replaced.

        ``_convert_single_message`` emits a ``ResponsesAssistantMessageItemResource``
        for every tool-free AIMessage regardless of content, so ``assistant_items``
        is non-empty here.  The empty surviving message must still be swapped for
        the placeholder fallback — Foundry would otherwise reject the response.
        """
        from azure.ai.agentserver.core.models import projects as pm

        output = [{"call_model": {"messages": [AIMessage(content="")]}}]
        items = final_answer_converter.convert(output)

        assert len(items) == 1
        assert isinstance(items[0], pm.ResponsesAssistantMessageItemResource)
        assert isinstance(items[0].content, str)
        assert items[0].content.strip()  # non-whitespace

    def test_final_ai_message_whitespace_only_replaced_with_fallback(self, final_answer_converter):
        """Final AIMessage with whitespace-only content → replaced with fallback.

        Covers the ``"   \\n\\t  "`` case where content is technically a
        non-empty string but collapses to nothing after stripping.
        """
        from azure.ai.agentserver.core.models import projects as pm

        output = [{"call_model": {"messages": [AIMessage(content="   \n\t  ")]}}]
        items = final_answer_converter.convert(output)

        assert len(items) == 1
        assert isinstance(items[0], pm.ResponsesAssistantMessageItemResource)
        assert isinstance(items[0].content, str)
        assert items[0].content.strip()  # non-whitespace

    def test_empty_final_message_uses_last_ai_text_when_available(self, final_answer_converter):
        """Empty final AIMessage + earlier preamble → preamble wins over placeholder."""
        from azure.ai.agentserver.core.models import projects as pm

        ai_with_preamble = AIMessage(
            content="Based on the transcript, here is what I found.",
            tool_calls=[{"name": "s", "id": "c1", "args": {}}],
        )
        output = [
            {"call_model": {"messages": [ai_with_preamble]}},
            {"tools": {"messages": [ToolMessage(content="r", tool_call_id="c1")]}},
            {"call_model": {"messages": [AIMessage(content="")]}},
        ]
        items = final_answer_converter.convert(output)

        assert len(items) == 1
        assert isinstance(items[0], pm.ResponsesAssistantMessageItemResource)
        assert "Based on the transcript" in items[0].content


# ---------------------------------------------------------------------------
# Test: QPrismaStateConverter response_mode integration
# ---------------------------------------------------------------------------


class TestStateConverterResponseMode:
    """Verify QPrismaStateConverter reads response_mode from QPRISMA_CONTEXT
    and env var, and passes it through to the response converter."""

    def test_env_var_default(self, monkeypatch):
        """QPRISMA_RESPONSE_MODE env var sets the default mode."""
        from agent.hosted.state_converter import QPrismaStateConverter

        monkeypatch.setenv("QPRISMA_RESPONSE_MODE", "final_answer")
        conv = QPrismaStateConverter(graph=MagicMock())
        assert conv._default_response_mode == "final_answer"

    def test_invalid_env_var_falls_back(self, monkeypatch):
        """Invalid QPRISMA_RESPONSE_MODE env var → 'full'."""
        from agent.hosted.state_converter import QPrismaStateConverter

        monkeypatch.setenv("QPRISMA_RESPONSE_MODE", "invalid")
        conv = QPrismaStateConverter(graph=MagicMock())
        assert conv._default_response_mode == "full"

    def test_no_env_var_defaults_to_full(self, monkeypatch):
        """No QPRISMA_RESPONSE_MODE env var → 'full'."""
        from agent.hosted.state_converter import QPrismaStateConverter

        monkeypatch.delenv("QPRISMA_RESPONSE_MODE", raising=False)
        conv = QPrismaStateConverter(graph=MagicMock())
        assert conv._default_response_mode == "full"

    @pytest.mark.asyncio
    async def test_context_response_mode_override(self, monkeypatch):
        """response_mode in QPRISMA_CONTEXT overrides env var default via convert_request()."""
        from agent.hosted.state_converter import QPrismaStateConverter, _request_response_mode

        monkeypatch.delenv("QPRISMA_RESPONSE_MODE", raising=False)
        conv = QPrismaStateConverter(graph=MagicMock())

        # Patch the parent convert_request to return a message with QPRISMA_CONTEXT
        from unittest.mock import AsyncMock

        msg_text = '[QPRISMA_CONTEXT:{"media_id":"v1","response_mode":"final_answer"}]\nSummarize.'
        super_result = {
            "input": {"messages": [HumanMessage(content=msg_text)]},
            "config": {},
        }
        monkeypatch.setattr(
            "agent.hosted.state_converter.ResponseAPIDefaultConverter.convert_request",
            AsyncMock(return_value=super_result),
        )

        mock_context = MagicMock()
        result = await conv.convert_request(mock_context)

        # The ContextVar should be set to the per-query override
        assert _request_response_mode.get() == "final_answer"
        # response_mode should be popped from the injected state
        assert "response_mode" not in result["input"]

    def test_context_extraction_preserves_response_mode(self):
        """_extract_qprisma_context preserves response_mode in metadata.

        The actual pop happens later in convert_request(), not in extraction.
        """
        from agent.hosted.state_converter import _extract_qprisma_context

        text = '[QPRISMA_CONTEXT:{"media_id":"v1","user_id":"u1","response_mode":"final_answer"}]\nQuery'
        metadata, clean = _extract_qprisma_context(text)
        # response_mode is preserved by extraction (not popped here)
        assert metadata.get("response_mode") == "final_answer"
        assert metadata.get("media_id") == "v1"
        assert clean == "Query"

    @pytest.mark.asyncio
    async def test_convert_request_pops_response_mode(self, monkeypatch):
        """convert_request() pops response_mode from metadata before injecting state."""
        from unittest.mock import AsyncMock

        from agent.hosted.state_converter import QPrismaStateConverter

        monkeypatch.delenv("QPRISMA_RESPONSE_MODE", raising=False)
        conv = QPrismaStateConverter(graph=MagicMock())

        msg_text = '[QPRISMA_CONTEXT:{"media_id":"v1","user_id":"u1","response_mode":"final_answer"}]\nQuery'
        super_result = {
            "input": {"messages": [HumanMessage(content=msg_text)]},
            "config": {},
        }
        monkeypatch.setattr(
            "agent.hosted.state_converter.ResponseAPIDefaultConverter.convert_request",
            AsyncMock(return_value=super_result),
        )

        result = await conv.convert_request(MagicMock())

        # response_mode should NOT appear in the graph input state
        assert "response_mode" not in result["input"]
        # Other fields should be injected normally
        assert result["input"]["media_id"] == "v1"
        assert result["input"]["user_id"] == "u1"
