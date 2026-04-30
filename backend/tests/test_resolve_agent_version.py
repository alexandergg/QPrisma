import importlib.util
import sys
import types
from pathlib import Path

import pytest


def _load_resolver_module():
    module_path = Path(__file__).parents[2] / "scripts" / "resolve_agent_version.py"
    spec = importlib.util.spec_from_file_location("resolve_agent_version_under_test", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resolve_agent_version_strict_requires_endpoint(monkeypatch: pytest.MonkeyPatch):
    resolver = _load_resolver_module()
    monkeypatch.delenv("AZURE_AI_PROJECT_ENDPOINT", raising=False)

    with pytest.raises(resolver.AgentVersionResolutionError):
        resolver.resolve_agent_version(strict=True)


def test_resolve_agent_version_non_strict_keeps_explicit_fallback(
    monkeypatch: pytest.MonkeyPatch,
):
    resolver = _load_resolver_module()
    monkeypatch.delenv("AZURE_AI_PROJECT_ENDPOINT", raising=False)
    monkeypatch.setenv("AGENT_NAME", "custom-agent")

    assert resolver.resolve_agent_version(strict=False) == "custom-agent:1"


def test_resolve_agent_version_uses_explicit_version_without_endpoint(
    monkeypatch: pytest.MonkeyPatch,
):
    resolver = _load_resolver_module()
    monkeypatch.delenv("AZURE_AI_PROJECT_ENDPOINT", raising=False)
    monkeypatch.setenv("AGENT_NAME", "custom-agent")

    assert resolver.resolve_agent_version(strict=True, requested_version="77") == "custom-agent:77"


def test_resolve_agent_version_rejects_mismatched_agent_id_override(
    monkeypatch: pytest.MonkeyPatch,
):
    resolver = _load_resolver_module()
    monkeypatch.setenv("AGENT_NAME", "qprisma-video-agent")

    with pytest.raises(resolver.AgentVersionResolutionError):
        resolver.resolve_agent_version(
            strict=True,
            requested_version="other-agent:77",
        )


def test_resolve_agent_version_strict_resolves_latest_agent(
    monkeypatch: pytest.MonkeyPatch,
):
    resolver = _load_resolver_module()

    class FakeCredential:
        pass

    class FakeAgentsClient:
        def get(self, *, agent_name: str):
            assert agent_name == "qprisma-video-agent"
            return types.SimpleNamespace(version="42")

    class FakeProjectClient:
        def __init__(self, *, endpoint: str, credential: FakeCredential):
            assert endpoint == "https://example.services.ai.azure.com/api/projects/demo"
            self.agents = FakeAgentsClient()

    azure_module = types.ModuleType("azure")
    azure_ai_module = types.ModuleType("azure.ai")
    projects_module = types.ModuleType("azure.ai.projects")
    identity_module = types.ModuleType("azure.identity")
    projects_module.AIProjectClient = FakeProjectClient
    identity_module.DefaultAzureCredential = FakeCredential
    monkeypatch.setitem(sys.modules, "azure", azure_module)
    monkeypatch.setitem(sys.modules, "azure.ai", azure_ai_module)
    monkeypatch.setitem(sys.modules, "azure.ai.projects", projects_module)
    monkeypatch.setitem(sys.modules, "azure.identity", identity_module)
    monkeypatch.setenv(
        "AZURE_AI_PROJECT_ENDPOINT",
        "https://example.services.ai.azure.com/api/projects/demo",
    )

    assert (
        resolver.resolve_agent_version(strict=True, requested_version="latest")
        == "qprisma-video-agent:42"
    )


def test_main_strict_failure_returns_nonzero(monkeypatch: pytest.MonkeyPatch, capsys):
    resolver = _load_resolver_module()
    monkeypatch.delenv("AZURE_AI_PROJECT_ENDPOINT", raising=False)

    assert resolver.main(["--strict"]) == 1
    assert "AZURE_AI_PROJECT_ENDPOINT not set" in capsys.readouterr().err
