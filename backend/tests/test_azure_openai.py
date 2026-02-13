"""Integration tests for Azure OpenAI connectivity."""

import os

import pytest
from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv()


pytestmark = [pytest.mark.integration, pytest.mark.requires_azure]


@pytest.fixture
def azure_config() -> tuple[str, str, str, str]:
    """Return required Azure OpenAI config for integration tests."""
    if not os.getenv("RUN_INTEGRATION_TESTS"):
        pytest.skip("Integration tests are disabled. Set RUN_INTEGRATION_TESTS=1 to enable.")

    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_GPT")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")

    missing = [
        name
        for name, value in (
            ("AZURE_OPENAI_ENDPOINT", endpoint),
            ("AZURE_OPENAI_API_KEY", api_key),
            ("AZURE_OPENAI_DEPLOYMENT_GPT", deployment),
        )
        if not value
    ]
    if missing:
        pytest.skip(f"Missing Azure configuration: {', '.join(missing)}")

    return endpoint, api_key, api_version, deployment


def test_azure_openai_connection(azure_config: tuple[str, str, str, str]):
    """Verify basic chat completion works against configured Azure deployment."""
    endpoint, api_key, api_version, deployment = azure_config
    client = AzureOpenAI(azure_endpoint=endpoint, api_key=api_key, api_version=api_version)

    response = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "user", "content": "Reply with the word: connected"}],
        max_tokens=16,
    )

    content = response.choices[0].message.content
    assert isinstance(content, str)
    assert content.strip()
