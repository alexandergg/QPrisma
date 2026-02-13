"""
Tests for core/config.py

Covers settings classes, validators, property methods,
production safety checks, and client factory functions.
"""

import os
from unittest.mock import patch

import pytest

from core.config import (
    AppSettings,
    AuthSettings,
    AzureSettings,
    Neo4jSettings,
    PostgresSettings,
    RedisSettings,
    Settings,
    get_settings,
)

# =============================================================================
# AzureSettings
# =============================================================================


@pytest.mark.unit
class TestAzureSettings:
    def test_is_openai_configured_false(self):
        s = AzureSettings(openai_endpoint=None, openai_api_key=None)
        assert s.is_openai_configured is False

    def test_is_openai_configured_true(self):
        s = AzureSettings(openai_endpoint="https://foo.openai.azure.com", openai_api_key="key123")
        assert s.is_openai_configured is True

    def test_is_openai_configured_partial(self):
        s = AzureSettings(openai_endpoint="https://foo.openai.azure.com", openai_api_key=None)
        assert s.is_openai_configured is False

    def test_is_storage_configured_false(self):
        s = AzureSettings(storage_connection_string=None)
        assert s.is_storage_configured is False

    def test_is_storage_configured_true(self):
        s = AzureSettings(storage_connection_string="DefaultEndpointsProtocol=https;...")
        assert s.is_storage_configured is True

    def test_is_batch_configured_false(self):
        s = AzureSettings(openai_deployment_gpt_batch=None)
        assert s.is_batch_configured is False

    def test_is_batch_configured_true(self):
        s = AzureSettings(openai_deployment_gpt_batch="gpt-4o-global-batch")
        assert s.is_batch_configured is True

    def test_default_container_name(self):
        s = AzureSettings()
        assert s.storage_container_name == "media"


# =============================================================================
# PostgresSettings
# =============================================================================


@pytest.mark.unit
class TestPostgresSettings:
    def test_default_url(self):
        s = PostgresSettings()
        assert "qprisma" in s.database_url
        assert "postgresql://" in s.database_url

    def test_is_configured(self):
        s = PostgresSettings()
        assert s.is_configured is True

    def test_production_rejects_default_credentials(self):
        with (
            patch.dict(os.environ, {"APP_ENV": "production"}),
            pytest.raises(ValueError, match="Default database credentials"),
        ):
            PostgresSettings(database_url="postgresql://qprisma:qprisma123@localhost:5432/qprisma")

    def test_production_accepts_secure_credentials(self):
        with patch.dict(os.environ, {"APP_ENV": "production"}):
            s = PostgresSettings(
                database_url="postgresql://prod_user:s3cur3p@ss@db.host:5432/qprisma"
            )
            assert "prod_user" in s.database_url


# =============================================================================
# Neo4jSettings
# =============================================================================


@pytest.mark.unit
class TestNeo4jSettings:
    def test_defaults(self):
        s = Neo4jSettings()
        assert s.uri == "bolt://localhost:7687"
        assert s.user == "neo4j"
        assert s.database == "neo4j"

    def test_is_configured(self):
        s = Neo4jSettings()
        assert s.is_configured is True

    def test_production_rejects_default_password(self):
        with (
            patch.dict(os.environ, {"APP_ENV": "production"}),
            pytest.raises(ValueError, match="Default Neo4j password"),
        ):
            Neo4jSettings(password="qprisma123")

    def test_production_accepts_secure_password(self):
        with patch.dict(os.environ, {"APP_ENV": "production"}):
            s = Neo4jSettings(password="a_very_secure_password_123!")
            assert s.password == "a_very_secure_password_123!"


# =============================================================================
# AuthSettings
# =============================================================================


@pytest.mark.unit
class TestAuthSettings:
    def test_defaults(self):
        s = AuthSettings()
        assert s.jwt_algorithm == "HS256"
        assert s.jwt_access_token_expire_minutes == 1440
        assert s.jwt_refresh_token_expire_days == 30

    def test_production_rejects_default_secret(self):
        with (
            patch.dict(os.environ, {"APP_ENV": "production"}),
            pytest.raises(ValueError, match="Default JWT secret"),
        ):
            AuthSettings(jwt_secret_key="your-secret-key-change-in-production")

    def test_production_rejects_short_secret(self):
        with (
            patch.dict(os.environ, {"APP_ENV": "production"}),
            pytest.raises(ValueError, match="at least 32 characters"),
        ):
            AuthSettings(jwt_secret_key="tooshort")

    def test_production_accepts_secure_secret(self):
        with patch.dict(os.environ, {"APP_ENV": "production"}):
            secret = "a" * 32
            s = AuthSettings(jwt_secret_key=secret)
            assert s.jwt_secret_key == secret

    def test_dev_mode_warns_on_default_secret(self):
        with pytest.warns(UserWarning, match="default JWT secret"):
            AuthSettings(jwt_secret_key="your-secret-key-change-in-production")


# =============================================================================
# AppSettings
# =============================================================================


@pytest.mark.unit
class TestAppSettings:
    def test_defaults(self):
        s = AppSettings()
        assert s.app_name == "QPrisma API"
        assert s.environment == "dev"
        assert s.port == 8000
        assert s.debug is False

    def test_cors_origins_default(self):
        s = AppSettings()
        assert "http://localhost:3000" in s.cors_origins

    def test_cors_origins_from_string(self):
        s = AppSettings(cors_origins="http://a.com,http://b.com")
        assert s.cors_origins == ["http://a.com", "http://b.com"]

    def test_cors_origins_from_list(self):
        s = AppSettings(cors_origins=["http://a.com", "http://b.com"])
        assert len(s.cors_origins) == 2


# =============================================================================
# RedisSettings
# =============================================================================


@pytest.mark.unit
class TestRedisSettings:
    def test_defaults(self):
        s = RedisSettings()
        assert s.url == "redis://localhost:6379/0"

    def test_is_configured(self):
        s = RedisSettings()
        assert s.is_configured is True


# =============================================================================
# Root Settings
# =============================================================================


@pytest.mark.unit
class TestSettings:
    def test_creation(self):
        s = Settings()
        assert s.app is not None
        assert s.azure is not None
        assert s.auth is not None

    def test_apply_env_overrides(self):
        s = Settings()
        with patch.dict(
            os.environ, {"APP_ENV": "staging", "LOG_LEVEL": "DEBUG", "API_PORT": "9000"}
        ):
            s.apply_env_overrides()
        assert s.app.environment == "staging"
        assert s.app.log_level == "DEBUG"
        assert s.app.port == 9000

    def test_apply_env_overrides_cors(self):
        s = Settings()
        with patch.dict(os.environ, {"ALLOWED_ORIGINS": "http://x.com,http://y.com"}):
            s.apply_env_overrides()
        assert "http://x.com" in s.app.cors_origins

    def test_apply_env_overrides_invalid_port(self):
        s = Settings()
        original_port = s.app.port
        with patch.dict(os.environ, {"API_PORT": "notanumber"}):
            s.apply_env_overrides()
        assert s.app.port == original_port  # unchanged

    def test_get_settings_cached(self, reset_settings):
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2


# =============================================================================
# Client Factories
# =============================================================================


@pytest.mark.unit
class TestClientFactories:
    def test_create_azure_openai_client_raises_without_config(self, reset_settings):
        from unittest.mock import MagicMock

        from core.config import create_azure_openai_client

        mock_settings = MagicMock()
        mock_settings.azure.is_openai_configured = False

        with (
            patch("core.config.get_settings", return_value=mock_settings),
            pytest.raises(ValueError, match="not configured"),
        ):
            create_azure_openai_client()

    def test_create_async_azure_openai_client_raises_without_config(self, reset_settings):
        from unittest.mock import MagicMock

        from core.config import create_async_azure_openai_client

        mock_settings = MagicMock()
        mock_settings.azure.is_openai_configured = False

        with (
            patch("core.config.get_settings", return_value=mock_settings),
            pytest.raises(ValueError, match="not configured"),
        ):
            create_async_azure_openai_client()
