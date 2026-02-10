"""Test Azure OpenAI connection and list deployments"""

import os

import pytest
from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv()


@pytest.mark.requires_azure
def test_azure_openai_connection():
    """Integration test: verify Azure OpenAI connectivity and deployments."""
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
    deployment_gpt = os.getenv("AZURE_OPENAI_DEPLOYMENT_GPT")

    print("🔍 Testing Azure OpenAI connection...")
    print(f"📍 Endpoint: {endpoint}")
    print(f"📋 API Version: {api_version}")
    print(f"🤖 GPT Deployment: {deployment_gpt}")
    print()

    client = AzureOpenAI(azure_endpoint=endpoint, api_key=api_key, api_version=api_version)

    # Test with a simple text completion (no vision)
    print("✅ Testing text completion...")
    response = client.chat.completions.create(
        model=deployment_gpt,
        messages=[{"role": "user", "content": "Say 'Hello, I am working!' in one sentence."}],
        max_tokens=50,
    )
    assert response.choices[0].message.content is not None
    print("✅ Text completion works!")
    print(f"Response: {response.choices[0].message.content}")
    print()

    # Try common deployment names
    print("🔍 Testing common deployment names...")
    common_names = ["gpt-4o", "gpt-4", "gpt-4-vision", "gpt-4-turbo", "gpt-4o-mini", "gpt-35-turbo"]

    for name in common_names:
        try:
            response = client.chat.completions.create(
                model=name, messages=[{"role": "user", "content": "Hi"}], max_tokens=5
            )
            print(f"✅ Deployment '{name}' exists and works")
        except Exception as e:
            if "404" in str(e):
                print(f"❌ Deployment '{name}' not found (404)")
            else:
                print(f"⚠️  Deployment '{name}' error: {str(e)[:100]}")
