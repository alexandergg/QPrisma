"""Tests for hosted agent runtime helpers (refreshed Responses preview).

These tests cover pure helpers in :mod:`agent.hosted.main` that do not require
the ``azure-ai-agentserver-responses`` runtime wheel (only available inside the
hosted Docker image). The Azure SDK module is shimmed at import time so the
helpers can be imported in normal CI.
"""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage


def _install_sdk_shim(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install a minimal ``azure.ai.agentserver.responses`` stub.

    The real wheel is only installed inside the hosted container. This shim
    mirrors the small Responses streaming surface used by the hosted runtime.
    """
    try:
        import azure.ai.agentserver.responses  # noqa: F401

        return
    except Exception:  # noqa: S110
        pass

    azure_mod = sys.modules.get("azure") or types.ModuleType("azure")
    ai_mod = sys.modules.get("azure.ai") or types.ModuleType("azure.ai")
    agentserver_mod = sys.modules.get("azure.ai.agentserver") or types.ModuleType(
        "azure.ai.agentserver"
    )
    responses_mod = types.ModuleType("azure.ai.agentserver.responses")

    class _ResponseContext:  # noqa: D401 - shim
        async def get_history(self) -> list[Any]:
            return []

    class _CreateResponse:
        def __init__(self) -> None:
            self.metadata: dict[str, Any] | None = None
            self.input: list[Any] = []

    class _TextResponse:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.args = args
            self.kwargs = kwargs

    class _TextContentBuilder:
        def __init__(self) -> None:
            self.final_text = ""

        def emit_added(self) -> types.SimpleNamespace:
            return types.SimpleNamespace(type="response.content_part.added")

        def emit_delta(self, text: str) -> types.SimpleNamespace:
            self.final_text += text
            return types.SimpleNamespace(type="response.output_text.delta", delta=text)

        def emit_text_done(self, final_text: str | None = None) -> types.SimpleNamespace:
            return types.SimpleNamespace(
                type="response.output_text.done",
                text=final_text if final_text is not None else self.final_text,
            )

        def emit_done(self) -> types.SimpleNamespace:
            return types.SimpleNamespace(type="response.content_part.done")

    class _MessageBuilder:
        def __init__(self) -> None:
            self.text_content = _TextContentBuilder()

        def emit_added(self) -> types.SimpleNamespace:
            return types.SimpleNamespace(
                type="response.output_item.added",
                item=types.SimpleNamespace(type="message"),
            )

        def add_text_content(self) -> _TextContentBuilder:
            return self.text_content

        def emit_done(self) -> types.SimpleNamespace:
            return types.SimpleNamespace(
                type="response.output_item.done",
                item=types.SimpleNamespace(type="message"),
            )

    class _FunctionCallBuilder:
        def __init__(self, name: str, call_id: str) -> None:
            self.name = name
            self.call_id = call_id
            self.arguments = ""

        def _item(self) -> types.SimpleNamespace:
            return types.SimpleNamespace(
                type="function_call",
                name=self.name,
                call_id=self.call_id,
                arguments=self.arguments,
            )

        def emit_added(self) -> types.SimpleNamespace:
            return types.SimpleNamespace(type="response.output_item.added", item=self._item())

        def emit_arguments_delta(self, delta: str) -> types.SimpleNamespace:
            self.arguments += delta
            return types.SimpleNamespace(type="response.function_call_arguments.delta", delta=delta)

        def emit_arguments_done(self, arguments: str) -> types.SimpleNamespace:
            self.arguments = arguments
            return types.SimpleNamespace(
                type="response.function_call_arguments.done",
                name=self.name,
                arguments=arguments,
            )

        def emit_done(self) -> types.SimpleNamespace:
            return types.SimpleNamespace(type="response.output_item.done", item=self._item())

    class _ResponseEventStream:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.args = args
            self.kwargs = kwargs

        def emit_created(self, *, status: str = "in_progress") -> types.SimpleNamespace:
            return types.SimpleNamespace(type="response.created", status=status)

        def emit_in_progress(self) -> types.SimpleNamespace:
            return types.SimpleNamespace(type="response.in_progress")

        def emit_completed(self) -> types.SimpleNamespace:
            return types.SimpleNamespace(type="response.completed")

        def add_output_item_message(self) -> _MessageBuilder:
            return _MessageBuilder()

        def add_output_item_function_call(
            self,
            *,
            name: str,
            call_id: str,
        ) -> _FunctionCallBuilder:
            return _FunctionCallBuilder(name=name, call_id=call_id)

    class _ResponsesAgentServerHost:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...

        def response_handler(self, fn):  # noqa: D401 - decorator shim
            return fn

        def run(self, *args: Any, **kwargs: Any) -> None: ...

    responses_mod.ResponseContext = _ResponseContext
    responses_mod.CreateResponse = _CreateResponse
    responses_mod.TextResponse = _TextResponse
    responses_mod.ResponseEventStream = _ResponseEventStream
    responses_mod.ResponsesAgentServerHost = _ResponsesAgentServerHost

    azure_mod.ai = ai_mod
    ai_mod.agentserver = agentserver_mod
    agentserver_mod.responses = responses_mod

    monkeypatch.setitem(sys.modules, "azure", azure_mod)
    monkeypatch.setitem(sys.modules, "azure.ai", ai_mod)
    monkeypatch.setitem(sys.modules, "azure.ai.agentserver", agentserver_mod)
    monkeypatch.setitem(sys.modules, "azure.ai.agentserver.responses", responses_mod)


@pytest.fixture
def hosted_main(monkeypatch: pytest.MonkeyPatch):
    _install_sdk_shim(monkeypatch)
    # Avoid grabbing real Azure credentials during import
    monkeypatch.setenv(
        "AZURE_AI_PROJECT_ENDPOINT", "https://example.services.ai.azure.com/api/projects/demo"
    )
    monkeypatch.setenv(
        "FOUNDRY_PROJECT_ENDPOINT", "https://example.services.ai.azure.com/api/projects/demo"
    )
    sys.modules.pop("agent.hosted.main", None)
    import agent.hosted.main as hosted_main  # noqa: PLC0415

    return hosted_main


@pytest.mark.unit
class TestNormaliseMediaIds:
    def test_none_returns_empty(self, hosted_main):
        assert hosted_main._normalise_media_ids(None) == []

    def test_list_filters_blanks(self, hosted_main):
        assert hosted_main._normalise_media_ids(["a", "", None, "b"]) == ["a", "b"]

    def test_csv_string(self, hosted_main):
        assert hosted_main._normalise_media_ids("a, b ,c") == ["a", "b", "c"]

    def test_scalar_value(self, hosted_main):
        assert hosted_main._normalise_media_ids(42) == ["42"]


@pytest.mark.unit
class TestBuildInitialState:
    def test_metadata_promoted_into_state(self, hosted_main):
        state = hosted_main._build_initial_state(
            metadata={
                "media_id": "vid-1",
                "media_ids": ["vid-1", "vid-2"],
                "user_id": "user-42",
                "session_id": "sess-9",
            },
            messages=[HumanMessage(content="hi")],
        )

        assert state["media_id"] == "vid-1"
        assert state["media_ids"] == ["vid-1", "vid-2"]
        assert state["user_id"] == "user-42"
        assert state["session_id"] == "sess-9"
        assert isinstance(state["messages"][0], HumanMessage)

    def test_media_id_inserted_into_media_ids_when_missing(self, hosted_main):
        state = hosted_main._build_initial_state(
            metadata={"media_id": "vid-7", "media_ids": ["vid-other"]},
            messages=[],
        )
        assert state["media_ids"][0] == "vid-7"

    def test_camel_case_aliases_supported(self, hosted_main):
        state = hosted_main._build_initial_state(
            metadata={"userId": "user-1", "sessionId": "sess-1"},
            messages=[],
        )
        assert state["user_id"] == "user-1"
        assert state["session_id"] == "sess-1"

    def test_drops_invalid_benchmark_context(self, hosted_main):
        state = hosted_main._build_initial_state(
            metadata={"benchmark_context": "not-a-dict"},
            messages=[],
        )
        assert "benchmark_context" not in state


@pytest.mark.unit
class TestCoerceMessage:
    def test_passthrough_basemessage(self, hosted_main):
        msg = HumanMessage(content="hello")
        assert hosted_main._coerce_message(msg) is msg

    def test_dict_user_role(self, hosted_main):
        msg = hosted_main._coerce_message({"role": "user", "content": "hi"})
        assert isinstance(msg, HumanMessage)
        assert msg.content == "hi"

    def test_dict_assistant_role(self, hosted_main):
        msg = hosted_main._coerce_message({"role": "assistant", "content": "ok"})
        assert isinstance(msg, AIMessage)

    def test_dict_system_role(self, hosted_main):
        msg = hosted_main._coerce_message({"role": "system", "content": "sys"})
        assert isinstance(msg, SystemMessage)

    def test_unknown_returns_none(self, hosted_main):
        assert hosted_main._coerce_message(object()) is None


@pytest.mark.unit
class TestMaskUri:
    def test_keeps_host_drops_path_and_query(self, hosted_main):
        masked = hosted_main._mask_uri(
            "https://example.services.ai.azure.com/api/projects/demo?key=abc"
        )
        assert "key=abc" not in masked
        assert "example.services.ai.azure.com" in masked

    def test_handles_none(self, hosted_main):
        assert hosted_main._mask_uri(None) == "<unset>"


@pytest.mark.unit
class TestResponseEventStreaming:
    async def test_tool_lifecycle_emits_function_call_events(self, hosted_main):
        class FakeGraph:
            async def astream_events(self, *_args: Any, **_kwargs: Any):
                yield {
                    "event": "on_tool_start",
                    "name": "get_summary",
                    "run_id": "run-1",
                    "data": {"input": {"media_id": "vid-1"}},
                }
                yield {
                    "event": "on_tool_end",
                    "name": "get_summary",
                    "run_id": "run-1",
                    "data": {"output": {"summary": "Done"}},
                }

        events = [
            event
            async for event in hosted_main._stream_response_events(
                context=types.SimpleNamespace(response_id="resp-1"),
                request=types.SimpleNamespace(metadata={}),
                graph=FakeGraph(),
                state={},
                config={},
                cancellation_signal=asyncio.Event(),
            )
        ]

        function_added = [
            event
            for event in events
            if event.type == "response.output_item.added"
            and getattr(getattr(event, "item", None), "type", None) == "function_call"
        ]
        function_done = [
            event
            for event in events
            if event.type == "response.output_item.done"
            and getattr(getattr(event, "item", None), "type", None) == "function_call"
        ]
        arguments_done = [
            event for event in events if event.type == "response.function_call_arguments.done"
        ]

        assert function_added[0].item.name == "get_summary"
        assert '"media_id": "vid-1"' in arguments_done[0].arguments
        assert function_done[0].item.name == "get_summary"

    async def test_model_stream_emits_text_delta(self, hosted_main):
        class FakeGraph:
            async def astream_events(self, *_args: Any, **_kwargs: Any):
                yield {
                    "event": "on_chat_model_stream",
                    "run_id": "llm-1",
                    "data": {"chunk": types.SimpleNamespace(content="Hello")},
                }
                yield {
                    "event": "on_chat_model_stream",
                    "run_id": "llm-1",
                    "data": {"chunk": types.SimpleNamespace(content=" world")},
                }

        events = [
            event
            async for event in hosted_main._stream_response_events(
                context=types.SimpleNamespace(response_id="resp-1"),
                request=types.SimpleNamespace(metadata={}),
                graph=FakeGraph(),
                state={},
                config={},
                cancellation_signal=asyncio.Event(),
            )
        ]
        deltas = [event.delta for event in events if event.type == "response.output_text.delta"]
        done_text = [event.text for event in events if event.type == "response.output_text.done"]

        assert deltas == ["Hello", " world"]
        assert done_text == ["Hello world"]

    async def test_model_end_fallback_emits_final_text(self, hosted_main):
        class FakeGraph:
            async def astream_events(self, *_args: Any, **_kwargs: Any):
                yield {
                    "event": "on_chat_model_end",
                    "run_id": "llm-1",
                    "data": {"output": AIMessage(content="Final answer")},
                }

        events = [
            event
            async for event in hosted_main._stream_response_events(
                context=types.SimpleNamespace(response_id="resp-1"),
                request=types.SimpleNamespace(metadata={}),
                graph=FakeGraph(),
                state={},
                config={},
                cancellation_signal=asyncio.Event(),
            )
        ]
        deltas = [event.delta for event in events if event.type == "response.output_text.delta"]

        assert deltas == ["Final answer"]

    async def test_model_end_ignores_tool_call_only_messages(self, hosted_main):
        class FakeGraph:
            async def astream_events(self, *_args: Any, **_kwargs: Any):
                yield {
                    "event": "on_chat_model_end",
                    "run_id": "llm-1",
                    "data": {
                        "output": AIMessage(
                            content="",
                            tool_calls=[
                                {
                                    "name": "get_summary",
                                    "args": {"media_id": "vid-1"},
                                    "id": "call-1",
                                }
                            ],
                        )
                    },
                }

        events = [
            event
            async for event in hosted_main._stream_response_events(
                context=types.SimpleNamespace(response_id="resp-1"),
                request=types.SimpleNamespace(metadata={}),
                graph=FakeGraph(),
                state={},
                config={},
                cancellation_signal=asyncio.Event(),
            )
        ]
        deltas = [event for event in events if event.type == "response.output_text.delta"]

        assert deltas == []


@pytest.mark.unit
def test_setup_telemetry_uses_current_tracer_constructor(
    hosted_main,
    monkeypatch: pytest.MonkeyPatch,
):
    calls: dict[str, Any] = {}

    class FakeCredential:
        pass

    class FakeAzureAIOpenTelemetryTracer:
        def __init__(self, *, project_endpoint: str, credential: Any, agent_id: str) -> None:
            calls["tracer"] = {
                "project_endpoint": project_endpoint,
                "credential": credential,
                "agent_id": agent_id,
            }

    langchain_mod = types.ModuleType("langchain_azure_ai")
    callbacks_mod = types.ModuleType("langchain_azure_ai.callbacks")
    tracers_mod = types.ModuleType("langchain_azure_ai.callbacks.tracers")
    tracers_mod.AzureAIOpenTelemetryTracer = FakeAzureAIOpenTelemetryTracer
    callbacks_mod.tracers = tracers_mod
    langchain_mod.callbacks = callbacks_mod

    monkeypatch.setitem(sys.modules, "langchain_azure_ai", langchain_mod)
    monkeypatch.setitem(sys.modules, "langchain_azure_ai.callbacks", callbacks_mod)
    monkeypatch.setitem(sys.modules, "langchain_azure_ai.callbacks.tracers", tracers_mod)
    monkeypatch.setattr(hosted_main, "DefaultAzureCredential", FakeCredential)
    monkeypatch.setenv(
        "FOUNDRY_PROJECT_ENDPOINT", "https://example.services.ai.azure.com/api/projects/demo"
    )
    monkeypatch.setenv("FOUNDRY_AGENT_NAME", "qprisma-video-agent")

    tracer = hosted_main._setup_telemetry()

    assert isinstance(tracer, hosted_main.SafeAzureAIOpenTelemetryTracer)
    assert calls["tracer"]["project_endpoint"] == (
        "https://example.services.ai.azure.com/api/projects/demo"
    )
    assert isinstance(calls["tracer"]["credential"], FakeCredential)
    assert calls["tracer"]["agent_id"] == "qprisma-video-agent"
