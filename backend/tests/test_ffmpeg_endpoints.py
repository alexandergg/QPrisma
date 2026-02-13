"""E2E checks for FFmpeg-related API endpoints."""

import os

import pytest
import requests

if os.getenv("RUN_E2E_TESTS", "").lower() not in {"1", "true", "yes"}:
    pytest.skip(
        "Manual FFmpeg endpoint checks are disabled. Set RUN_E2E_TESTS=true to enable.",
        allow_module_level=True,
    )

API_URL = "http://localhost:8000"
REQUEST_TIMEOUT_SECONDS = 30


def test_presets():
    """Validate presets endpoint returns a non-empty list."""
    response = requests.get(f"{API_URL}/presets", timeout=REQUEST_TIMEOUT_SECONDS)
    assert response.status_code == 200
    data = response.json()
    assert "presets" in data
    assert isinstance(data["presets"], list)
    assert data["presets"]


@pytest.mark.parametrize("preset", ["balanced", "fast_preview", "high_quality"])
def test_pipeline_preview(preset):
    """Validate pipeline preview for supported presets."""
    response = requests.get(
        f"{API_URL}/pipeline/preview",
        params={"preset": preset},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    assert response.status_code == 200
    data = response.json()
    assert "nodes" in data
    assert "edges" in data
    assert isinstance(data["nodes"], list)
    assert isinstance(data["edges"], list)


def test_health():
    """Validate health endpoint is reachable."""
    response = requests.get(f"{API_URL}/health", timeout=REQUEST_TIMEOUT_SECONDS)
    assert response.status_code == 200
    data = response.json()
    assert "services" in data
    assert isinstance(data["services"], dict)
