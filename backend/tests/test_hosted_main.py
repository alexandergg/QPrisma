"""Tests for hosted agent runtime environment setup."""

import os
import sys
import types
from types import SimpleNamespace

import pytest
from agent.hosted.main import create_hosted_app


def _make_module(name: str, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


@pytest.mark.unit
def test_create_hosted_app_overwrites_blank_sdk_endpoint(monkeypatch):
    fake_graph = object()
    fake_app = object()
    captured: dict[str, object] = {}

    class FakeMemorySaver:
        pass

    class FakeConverter:
        def __init__(self, graph):
            self.graph = graph

    def fake_create_video_agent_graph(*, checkpointer):
        captured["checkpointer"] = checkpointer
        return fake_graph

    def fake_from_langgraph(graph, *, converter):
        captured["graph"] = graph
        captured["converter"] = converter
        return fake_app

    monkeypatch.setenv("AZURE_AI_PROJECT_ENDPOINT", "")

    azure_module = _make_module("azure")
    azure_ai_module = _make_module("azure.ai")
    azure_agentserver_module = _make_module("azure.ai.agentserver")
    azure_langgraph_module = _make_module(
        "azure.ai.agentserver.langgraph", from_langgraph=fake_from_langgraph
    )
    azure_module.ai = azure_ai_module
    azure_ai_module.agentserver = azure_agentserver_module
    azure_agentserver_module.langgraph = azure_langgraph_module

    langgraph_module = _make_module("langgraph")
    langgraph_checkpoint_module = _make_module("langgraph.checkpoint")
    langgraph_checkpoint_memory_module = _make_module(
        "langgraph.checkpoint.memory", MemorySaver=FakeMemorySaver
    )
    langgraph_module.checkpoint = langgraph_checkpoint_module
    langgraph_checkpoint_module.memory = langgraph_checkpoint_memory_module

    monkeypatch.setitem(sys.modules, "langgraph", langgraph_module)
    monkeypatch.setitem(sys.modules, "langgraph.checkpoint", langgraph_checkpoint_module)
    monkeypatch.setitem(
        sys.modules,
        "langgraph.checkpoint.memory",
        langgraph_checkpoint_memory_module,
    )
    monkeypatch.setitem(
        sys.modules,
        "agent.graphs.video",
        _make_module(
            "agent.graphs.video",
            create_video_agent_graph=fake_create_video_agent_graph,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "agent.hosted.state_converter",
        _make_module("agent.hosted.state_converter", QPrismaStateConverter=FakeConverter),
    )
    monkeypatch.setitem(
        sys.modules,
        "core.config",
        _make_module(
            "core.config",
            settings=SimpleNamespace(
                foundry=SimpleNamespace(
                    project_endpoint="https://example.services.ai.azure.com/api/projects/demo"
                )
            ),
        ),
    )
    monkeypatch.setitem(sys.modules, "azure", azure_module)
    monkeypatch.setitem(sys.modules, "azure.ai", azure_ai_module)
    monkeypatch.setitem(sys.modules, "azure.ai.agentserver", azure_agentserver_module)
    monkeypatch.setitem(sys.modules, "azure.ai.agentserver.langgraph", azure_langgraph_module)

    app = create_hosted_app()

    assert app is fake_app
    assert isinstance(captured["checkpointer"], FakeMemorySaver)
    assert captured["graph"] is fake_graph
    assert isinstance(captured["converter"], FakeConverter)
    assert captured["converter"].graph is fake_graph
    assert (
        os.environ["AZURE_AI_PROJECT_ENDPOINT"]
        == "https://example.services.ai.azure.com/api/projects/demo"
    )
