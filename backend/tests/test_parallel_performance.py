"""Performance smoke tests for FFmpeg processing request latency."""

import os
import time
from pathlib import Path

import pytest
import requests

pytestmark = [pytest.mark.integration, pytest.mark.e2e, pytest.mark.slow]


def _performance_enabled() -> bool:
    return os.getenv("RUN_PERFORMANCE_TESTS", "").lower() in {"1", "true", "yes"}


@pytest.fixture(scope="module")
def api_url() -> str:
    if not _performance_enabled():
        pytest.skip("Performance tests disabled. Set RUN_PERFORMANCE_TESTS=true to enable.")
    return os.getenv("QPRISMA_API_URL", "http://localhost:8000").rstrip("/")


@pytest.fixture(scope="module")
def auth_headers() -> dict[str, str]:
    token = os.getenv("QPRISMA_E2E_BEARER_TOKEN")
    if not token:
        pytest.skip("Missing QPRISMA_E2E_BEARER_TOKEN for authenticated performance tests.")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module", autouse=True)
def ensure_api_available(api_url: str) -> None:
    try:
        response = requests.get(f"{api_url}/health", timeout=5)
        response.raise_for_status()
    except requests.RequestException as exc:
        pytest.skip(f"API unavailable at {api_url}: {exc}")


@pytest.fixture(scope="module")
def uploaded_media_id(api_url: str, auth_headers: dict[str, str], sample_video_path: Path) -> str:
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


@pytest.mark.parametrize("preset", ["fast_preview", "balanced"])
def test_processing_request_latency(
    api_url: str,
    auth_headers: dict[str, str],
    uploaded_media_id: str,
    preset: str,
) -> None:
    start = time.perf_counter()
    response = requests.post(
        f"{api_url}/process/video/ffmpeg",
        params={"media_id": uploaded_media_id, "preset": preset},
        headers=auth_headers,
        timeout=120,
    )
    elapsed_seconds = time.perf_counter() - start

    assert response.status_code == 200, response.text
    assert elapsed_seconds < 120
