"""
Tests for api/main.py core endpoints.

Covers root health check, detailed health, and config endpoints.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.mark.unit
class TestRootEndpoint:
    def test_returns_healthy(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert "version" in body

    def test_azure_configured_field(self, client):
        resp = client.get("/")
        body = resp.json()
        assert "azure_configured" in body
        assert isinstance(body["azure_configured"], bool)


@pytest.mark.unit
class TestHealthEndpoint:
    def test_returns_services_status(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert "services" in body
        assert "timestamp" in body
        services = body["services"]
        assert "api" in services
        assert services["api"] == "healthy"


@pytest.mark.unit
class TestConfigEndpoint:
    def test_returns_config_status(self, client):
        resp = client.get("/config")
        assert resp.status_code == 200
        body = resp.json()
        assert "azure_openai_configured" in body
        assert "azure_storage_configured" in body
        assert "postgresql_configured" in body
        assert "knowledge_graph_configured" in body
        assert "redis_configured" in body
        assert "environment" in body
        assert isinstance(body["azure_openai_configured"], bool)
