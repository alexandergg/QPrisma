from unittest.mock import patch

import pytest


@pytest.mark.unit
class TestCreateModelHostedFoundry:
    def test_hosted_foundry_path_uses_foundry_token_provider(self, monkeypatch):
        import agent.nodes.base as base_module

        monkeypatch.setenv("FOUNDRY_HOSTING_ENVIRONMENT", "azure-ai-foundry")
        monkeypatch.setenv(
            "FOUNDRY_PROJECT_ENDPOINT",
            "https://example.services.ai.azure.com/api/projects/demo",
        )

        captured: dict = {}

        class _StubChat:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        with (
            patch.object(base_module, "ChatOpenAI", _StubChat),
            patch.object(
                base_module,
                "get_foundry_openai_token_provider",
                return_value=lambda: "foundry-token",
            ) as token_provider,
            patch.object(base_module, "build_openai_client_kwargs") as azure_kwargs,
        ):
            base_module.create_model(model_deployment="gpt-4o", temperature=0.2)

        token_provider.assert_called_once_with()
        azure_kwargs.assert_not_called()
        assert captured["model"] == "gpt-4o"
        assert (
            captured["base_url"]
            == "https://example.services.ai.azure.com/api/projects/demo/openai/v1"
        )
        assert captured["api_key"] == "foundry-token"
        assert captured["temperature"] == 0.2
