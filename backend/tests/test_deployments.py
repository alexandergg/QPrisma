"""Test Azure OpenAI deployments"""

import os

import pytest
import requests
from dotenv import load_dotenv
from openai import AzureOpenAI

if os.getenv("RUN_INTEGRATION_TESTS", "").lower() not in {"1", "true", "yes"}:
    pytest.skip(
        "Manual deployment checks are disabled. Set RUN_INTEGRATION_TESTS=true to enable.",
        allow_module_level=True,
    )

load_dotenv()

# First, try to list deployments using REST API
print("Listing deployments via REST API...")
print("-" * 50)

endpoint = os.getenv("AZURE_OPENAI_ENDPOINT").rstrip("/")
api_key = os.getenv("AZURE_OPENAI_API_KEY")

try:
    # Try to list deployments
    url = f"{endpoint}/openai/deployments?api-version=2024-10-01-preview"
    headers = {"api-key": api_key}
    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        data = resp.json()
        print("Available deployments:")
        for deployment in data.get("data", []):
            print(
                f"  - {deployment.get('id')}: model={deployment.get('model')}, status={deployment.get('status')}"
            )
    else:
        print(f"Could not list deployments: {resp.status_code} - {resp.text[:200]}")
except Exception as e:
    print(f"Error listing deployments: {e}")

print()

client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-01-preview"),
)

print(f"Endpoint: {os.getenv('AZURE_OPENAI_ENDPOINT')}")
print(f"API Version: {os.getenv('AZURE_OPENAI_API_VERSION')}")
print(f"Configured deployment: {os.getenv('AZURE_OPENAI_DEPLOYMENT_GPT')}")
print()

# Test common deployment names
deployment_names = [
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4",
    "gpt-4-turbo",
    "gpt-35-turbo",
    "gpt-4-vision",
    "gpt-4o-vision",
]

print("Testing deployments...")
print("-" * 50)

for name in deployment_names:
    try:
        response = client.chat.completions.create(
            model=name, messages=[{"role": "user", "content": "Say hello"}], max_tokens=10
        )
        print(f"[OK] {name}: WORKS - Response: {response.choices[0].message.content}")
    except Exception as e:
        error_msg = str(e)
        if "OperationNotSupported" in error_msg:
            print(f"[X] {name}: Not supported for chat")
        elif "DeploymentNotFound" in error_msg or "does not exist" in error_msg.lower():
            print(f"[X] {name}: Deployment not found")
        else:
            print(f"[X] {name}: Error - {error_msg[:80]}")
