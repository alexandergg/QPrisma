"""
Tests for api/routes/auth_routes.py

Covers register, login, /me, and refresh token endpoints.
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestRegister:
    def test_register_success(self, client):
        mock_auth = MagicMock()
        mock_auth.register.return_value = {"access_token": "tok_123"}

        with patch("api.routes.auth_routes.get_auth_service", return_value=mock_auth):
            resp = client.post(
                "/auth/register",
                json={"email": "new@example.com", "password": "SecurePass1", "name": "New User"},
            )

        assert resp.status_code == 200
        assert resp.json()["access_token"] == "tok_123"

    def test_register_duplicate_email(self, client):
        mock_auth = MagicMock()
        mock_auth.register.return_value = {"error": "Email already registered"}

        with patch("api.routes.auth_routes.get_auth_service", return_value=mock_auth):
            resp = client.post(
                "/auth/register",
                json={"email": "dup@example.com", "password": "SecurePass1", "name": "Dup"},
            )

        assert resp.status_code == 400

    def test_register_invalid_body(self, client):
        resp = client.post("/auth/register", json={"email": "bad"})
        assert resp.status_code == 422

    def test_register_short_password(self, client):
        resp = client.post(
            "/auth/register",
            json={"email": "a@b.com", "password": "short", "name": "Test"},
        )
        assert resp.status_code == 422

    def test_register_short_name(self, client):
        resp = client.post(
            "/auth/register",
            json={"email": "a@b.com", "password": "SecurePass1", "name": "A"},
        )
        assert resp.status_code == 422


@pytest.mark.unit
class TestLogin:
    def test_login_success(self, client):
        mock_auth = MagicMock()
        mock_auth.login.return_value = {"access_token": "tok_456"}

        with patch("api.routes.auth_routes.get_auth_service", return_value=mock_auth):
            resp = client.post(
                "/auth/login",
                json={"email": "test@example.com", "password": "SecurePass1"},
            )

        assert resp.status_code == 200
        assert resp.json()["access_token"] == "tok_456"

    def test_login_invalid_credentials(self, client):
        mock_auth = MagicMock()
        mock_auth.login.return_value = {"error": "Invalid email or password"}

        with patch("api.routes.auth_routes.get_auth_service", return_value=mock_auth):
            resp = client.post(
                "/auth/login",
                json={"email": "test@example.com", "password": "wrong"},
            )

        assert resp.status_code == 401

    def test_login_invalid_body(self, client):
        resp = client.post("/auth/login", json={})
        assert resp.status_code == 422


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
class TestRefreshToken:
    def test_refresh_success(self, authenticated_client, test_user):
        resp = authenticated_client.post("/auth/refresh")
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    def test_refresh_unauthenticated(self, client):
        resp = client.post("/auth/refresh")
        assert resp.status_code in (401, 403)
