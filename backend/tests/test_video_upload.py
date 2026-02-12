"""E2E tests for video upload and processing endpoints against a running API."""

import os
from pathlib import Path

import pytest
import requests

pytestmark = [pytest.mark.integration, pytest.mark.e2e, pytest.mark.slow]


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
        pytest.skip("Missing QPRISMA_E2E_BEARER_TOKEN for authenticated E2E tests.")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module", autouse=True)
def ensure_api_available(api_url: str) -> None:
    try:
        response = requests.get(f"{api_url}/health", timeout=5)
        response.raise_for_status()
    except requests.RequestException as exc:
        pytest.skip(f"API unavailable at {api_url}: {exc}")


@pytest.fixture(scope="module")
def media_id(api_url: str, auth_headers: dict[str, str], sample_video_path: Path) -> str:
    if not sample_video_path.exists():
        pytest.skip(f"Sample video not found: {sample_video_path}")

    with sample_video_path.open("rb") as file_obj:
        response = requests.post(
            f"{api_url}/upload",
            files={"file": (sample_video_path.name, file_obj, "video/mp4")},
            headers=auth_headers,
            timeout=120,
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("media_id")
    return payload["media_id"]


def test_video_upload_and_processing(
    api_url: str, auth_headers: dict[str, str], media_id: str
) -> None:
    response = requests.post(
        f"{api_url}/process/video/ffmpeg",
        params={"media_id": media_id, "preset": "balanced"},
        headers=auth_headers,
        timeout=90,
    )
    assert response.status_code == 200, response.text

    payload = response.json()
    assert payload.get("status")
    assert payload.get("message")


def test_search_processed_video(api_url: str, auth_headers: dict[str, str], media_id: str) -> None:
    response = requests.post(
        f"{api_url}/search",
        json={"query": "video frame", "top_k": 5},
        headers=auth_headers,
        timeout=30,
    )
    assert response.status_code == 200, response.text

    payload = response.json()
    assert payload.get("query")
    assert isinstance(payload.get("results"), list)
