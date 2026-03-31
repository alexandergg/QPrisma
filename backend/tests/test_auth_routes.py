"""
Tests for api/routes/auth_routes.py

Covers /me (authenticated profile) and /config (public Entra ID config) endpoints.
"""

from unittest.mock import patch

import pytest


@pytest.mark.unit
class TestGetMe:
    def test_authenticated(self, authenticated_client, test_user):
        resp = authenticated_client.get("/auth/me")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == test_user.id
        assert body["email"] == test_user.email

    def test_unauthenticated(self, client):
        resp = client.get("/auth/me")
        assert resp.status_code in (401, 403)  # HTTPBearer auto_error


@pytest.mark.unit
class TestGetAuthConfig:
    def test_returns_entra_config(self, client):
        with patch("api.routes.auth_routes.settings") as mock_settings:
            mock_settings.auth.entra_tenant_id = "test-tenant"
            mock_settings.auth.entra_client_id = "test-client"
            mock_settings.auth.entra_api_scope = "api://test/access"
            resp = client.get("/auth/config")

        assert resp.status_code == 200
        body = resp.json()
        assert body["tenant_id"] == "test-tenant"
        assert body["client_id"] == "test-client"
        assert body["api_scope"] == "api://test/access"

    def test_config_is_public(self, client):
        """Config endpoint should not require authentication."""
        with patch("api.routes.auth_routes.settings") as mock_settings:
            mock_settings.auth.entra_tenant_id = "t"
            mock_settings.auth.entra_client_id = "c"
            mock_settings.auth.entra_api_scope = "s"
            resp = client.get("/auth/config")

        assert resp.status_code == 200


@pytest.mark.unit
class TestRemovedEndpoints:
    """Verify legacy auth endpoints no longer exist."""

    def test_register_gone(self, client):
        resp = client.post(
            "/auth/register", json={"email": "a@b.com", "password": "x", "name": "Y"}
        )
        assert resp.status_code in (404, 405)

    def test_login_gone(self, client):
        resp = client.post("/auth/login", json={"email": "a@b.com", "password": "x"})
        assert resp.status_code in (404, 405)

    def test_refresh_gone(self, client):
        resp = client.post("/auth/refresh")
        assert resp.status_code in (404, 405)

    def test_logout_gone(self, client):
        resp = client.post("/auth/logout")
        assert resp.status_code in (404, 405)
