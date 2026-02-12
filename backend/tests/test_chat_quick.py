"""Lightweight E2E checks for the /chat endpoint against a running API."""

import os

import pytest
import requests

pytestmark = [pytest.mark.integration, pytest.mark.e2e]


def _e2e_enabled() -> bool:
    return os.getenv("RUN_E2E_TESTS", "").lower() in {"1", "true", "yes"}


@pytest.fixture(scope="module")
def api_url() -> str:
    if not _e2e_enabled():
        pytest.skip("E2E tests disabled. Set RUN_E2E_TESTS=true to enable.")
    return os.getenv("QPRISMA_API_URL", "http://localhost:8000").rstrip("/")


@pytest.fixture(scope="module")
def auth_headers() -> dict[str, str]:
    token = os.getenv("QPRISMA_E2E_BEARER_TOKEN")
    if not token:
        pytest.skip("Missing QPRISMA_E2E_BEARER_TOKEN for authenticated /chat E2E tests.")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module", autouse=True)
def ensure_api_available(api_url: str) -> None:
    try:
        response = requests.get(f"{api_url}/health", timeout=5)
        response.raise_for_status()
    except requests.RequestException as exc:
        pytest.skip(f"API unavailable at {api_url}: {exc}")


@pytest.mark.parametrize(
    "payload",
    [
        {"message": "Hola, di una frase corta en español"},
        {"message": "¿Qué ves en la imagen?", "media_id": "test-id-123"},
    ],
)
def test_chat_endpoint_returns_non_empty_response(
    api_url: str, auth_headers: dict[str, str], payload: dict[str, str]
) -> None:
    response = requests.post(
        f"{api_url}/chat",
        json=payload,
        headers=auth_headers,
        timeout=30,
    )
    assert response.status_code == 200, response.text

    body = response.json()
    assert isinstance(body.get("response"), str)
    assert body["response"].strip()
