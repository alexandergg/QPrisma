"""Integration tests for Azure OpenAI connectivity."""

import os

import pytest
from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv()

pytestmark = [pytest.mark.integration, pytest.mark.requires_azure]


def _integration_enabled() -> bool:
    return os.getenv("RUN_INTEGRATION_TESTS", "").lower() in {"1", "true", "yes"}


@pytest.fixture(scope="module")
def azure_config() -> dict[str, str]:
    if not _integration_enabled():
        pytest.skip("Integration tests disabled. Set RUN_INTEGRATION_TESTS=true to enable.")

    config = {
        "endpoint": os.getenv("AZURE_OPENAI_ENDPOINT", ""),
        "api_key": os.getenv("AZURE_OPENAI_API_KEY", ""),
        "gpt_deployment": os.getenv("AZURE_OPENAI_DEPLOYMENT_GPT", ""),
        "embedding_deployment": os.getenv("AZURE_OPENAI_DEPLOYMENT_EMBEDDING", ""),
        "api_version": os.getenv("AZURE_OPENAI_API_VERSION", ""),
    }
    missing = [key for key, value in config.items() if not value]
    if missing:
        pytest.skip(f"Missing Azure OpenAI settings: {', '.join(missing)}")
    return config


@pytest.fixture(scope="module")
def openai_client(azure_config: dict[str, str]) -> AzureOpenAI:
    return AzureOpenAI(
        azure_endpoint=azure_config["endpoint"],
        api_key=azure_config["api_key"],
        api_version=azure_config["api_version"],
    )


def test_create_azure_openai_client(openai_client: AzureOpenAI) -> None:
    assert openai_client is not None


def test_generate_embedding(openai_client: AzureOpenAI, azure_config: dict[str, str]) -> None:
    response = openai_client.embeddings.create(
        model=azure_config["embedding_deployment"],
        input="Hello world",
    )
    embedding = response.data[0].embedding
    assert isinstance(embedding, list)
    assert len(embedding) > 0
    assert all(isinstance(value, float) for value in embedding[:10])


def test_chat_completion(openai_client: AzureOpenAI, azure_config: dict[str, str]) -> None:
    response = openai_client.chat.completions.create(
        model=azure_config["gpt_deployment"],
        messages=[{"role": "user", "content": "Say hello in Spanish"}],
        max_tokens=50,
    )
    message = response.choices[0].message.content
    assert isinstance(message, str)
    assert message.strip()
