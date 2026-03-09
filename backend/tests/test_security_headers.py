"""
Tests for the security headers middleware in api/main.py.

Validates that all required security headers are present on every response
and that HSTS is conditionally applied based on the environment setting.
"""

import pytest


@pytest.mark.unit
class TestSecurityHeaders:
    """Verify security headers are attached to every response."""

    def test_x_content_type_options(self, client):
        resp = client.get("/")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"

    def test_x_frame_options(self, client):
        resp = client.get("/")
        assert resp.headers.get("X-Frame-Options") == "DENY"

    def test_x_xss_protection(self, client):
        resp = client.get("/")
        assert resp.headers.get("X-XSS-Protection") == "1; mode=block"

    def test_referrer_policy(self, client):
        resp = client.get("/")
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_permissions_policy(self, client):
        resp = client.get("/")
        assert resp.headers.get("Permissions-Policy") == "camera=(), microphone=(), geolocation=()"

    def test_headers_on_health_endpoint(self, client):
        """Security headers must appear on all endpoints, not just root."""
        resp = client.get("/health")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"


@pytest.mark.unit
class TestHSTSHeader:
    """HSTS should only be present in non-development environments."""

    def test_no_hsts_in_dev(self, client):
        """Default test env is 'test', which is a development-class env."""
        resp = client.get("/")
        assert "Strict-Transport-Security" not in resp.headers

    def test_hsts_in_production(self, reset_settings):
        """When environment is 'production', HSTS header must be present."""
        # We need to patch the settings object used by the middleware at
        # module level.  Easiest: patch the environment attr on the live
        # settings instance that api.main already imported.
        from api.main import app, settings

        original_env = settings.app.environment
        try:
            settings.app.environment = "production"
            from fastapi.testclient import TestClient

            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get("/")
            assert resp.headers.get("Strict-Transport-Security") == (
                "max-age=31536000; includeSubDomains"
            )
        finally:
            settings.app.environment = original_env

    def test_no_hsts_in_local(self, reset_settings):
        """Environments like 'local' should not include HSTS."""
        from api.main import app, settings

        original_env = settings.app.environment
        try:
            settings.app.environment = "local"
            from fastapi.testclient import TestClient

            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get("/")
            assert "Strict-Transport-Security" not in resp.headers
        finally:
            settings.app.environment = original_env


@pytest.mark.unit
class TestCORSMiddlewareConfig:
    """Verify CORS middleware configuration changes."""

    def test_patch_method_allowed(self, client):
        """PATCH should be in the allowed CORS methods."""
        resp = client.options(
            "/",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "PATCH",
            },
        )
        allowed = resp.headers.get("Access-Control-Allow-Methods", "")
        assert "PATCH" in allowed

    def test_preflight_max_age(self, client):
        """Preflight responses should include max-age=600."""
        resp = client.options(
            "/",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("Access-Control-Max-Age") == "600"
