"""Tests for hosted agent runtime helpers (refreshed Responses preview).

These tests cover pure helpers in :mod:`agent.hosted.main` that do not require
the ``azure-ai-agentserver-responses`` runtime wheel (only available inside the
hosted Docker image). The Azure SDK module is shimmed at import time so the
helpers can be imported in normal CI.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage


def _install_sdk_shim(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install a minimal ``azure.ai.agentserver.responses`` stub.

    The real wheel is only installed inside the hosted container. The helpers
    we want to test never call into the SDK; we only need the import to succeed.
    """
    try:
        import azure.ai.agentserver.responses  # noqa: F401
        return
    except Exception:
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

    class _ResponsesAgentServerHost:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...

        def response_handler(self, fn):  # noqa: D401 - decorator shim
            return fn

        def run(self, *args: Any, **kwargs: Any) -> None: ...

    responses_mod.ResponseContext = _ResponseContext
    responses_mod.CreateResponse = _CreateResponse
    responses_mod.TextResponse = _TextResponse
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
    monkeypatch.setenv("AZURE_AI_PROJECT_ENDPOINT", "https://example.services.ai.azure.com/api/projects/demo")
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example.services.ai.azure.com/api/projects/demo")
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
        masked = hosted_main._mask_uri("https://example.services.ai.azure.com/api/projects/demo?key=abc")
        assert "key=abc" not in masked
        assert "example.services.ai.azure.com" in masked

    def test_handles_none(self, hosted_main):
        assert hosted_main._mask_uri(None) == "<unset>"
