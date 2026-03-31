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
        assert s.database_url == "postgresql://qprisma:qprisma123@localhost:5432/qprisma"

    def test_is_configured(self):
        s = PostgresSettings()
        assert s.is_configured is True

    def test_is_configured_when_set(self):
        s = PostgresSettings(database_url="postgresql://user:pass@localhost/db")
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
        assert s.entra_tenant_id == ""
        assert s.entra_client_id == ""
        assert s.entra_api_scope == ""

    def test_production_rejects_missing_entra_config(self):
        with (
            patch.dict(os.environ, {"APP_ENV": "production"}),
            pytest.raises(ValueError, match="Entra ID not configured"),
        ):
            AuthSettings(entra_tenant_id="", entra_client_id="")

    def test_production_accepts_entra_config(self):
        with patch.dict(os.environ, {"APP_ENV": "production"}):
            s = AuthSettings(entra_tenant_id="tenant-123", entra_client_id="client-456")
            assert s.entra_tenant_id == "tenant-123"


# =============================================================================
# AppSettings
# =============================================================================


@pytest.mark.unit
class TestAppSettings:
    def test_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            s = AppSettings()
        assert s.app_name == "QPrisma API"
        assert s.environment == "dev"
        assert s.port == 8000
        assert s.debug is False
        assert s.allow_dev_autologin is False
        assert s.api_base_url == "http://localhost:8000"
        assert s.log_file is None

    def test_cors_origins_default(self):
        s = AppSettings()
        assert "http://localhost:3000" in s.cors_origins

    def test_cors_origins_from_string(self):
        s = AppSettings(cors_origins="http://a.com,http://b.com")
        assert s.cors_origins == ["http://a.com", "http://b.com"]

    def test_cors_origins_from_list(self):
        s = AppSettings(cors_origins=["http://a.com", "http://b.com"])
        assert len(s.cors_origins) == 2

    def test_env_vars_loaded_natively(self):
        with patch.dict(
            os.environ, {"APP_ENV": "staging", "LOG_LEVEL": "DEBUG", "API_PORT": "9000"}
        ):
            s = AppSettings()
        assert s.environment == "staging"
        assert s.log_level == "DEBUG"
        assert s.port == 9000

    def test_env_var_cors_alias(self):
        with patch.dict(os.environ, {"ALLOWED_ORIGINS": "http://x.com,http://y.com"}):
            s = AppSettings()
        assert "http://x.com" in s.cors_origins

    def test_invalid_port_raises_validation_error(self):
        from pydantic import ValidationError

        with (
            patch.dict(os.environ, {"API_PORT": "notanumber"}),
            pytest.raises(ValidationError),
        ):
            AppSettings()

    def test_api_base_url_from_a2a_base_url_env(self):
        with patch.dict(os.environ, {"A2A_BASE_URL": "https://a2a.example.com"}):
            s = AppSettings()
        assert s.api_base_url == "https://a2a.example.com"

    def test_api_base_url_from_api_base_url_env(self):
        with patch.dict(os.environ, {"API_BASE_URL": "https://api.example.com"}):
            s = AppSettings()
        assert s.api_base_url == "https://api.example.com"

    def test_log_file_from_env(self):
        with patch.dict(os.environ, {"LOG_FILE": "/tmp/app.log"}):
            s = AppSettings()
        assert s.log_file == "/tmp/app.log"

    def test_disable_startup_healthchecks_default(self):
        with patch.dict(os.environ, {}, clear=True):
            s = AppSettings()
        assert s.disable_startup_healthchecks is False

    def test_disable_startup_healthchecks_from_env(self):
        with patch.dict(os.environ, {"DISABLE_STARTUP_HEALTHCHECKS": "true"}):
            s = AppSettings()
        assert s.disable_startup_healthchecks is True

    def test_disable_redis_pubsub_default(self):
        with patch.dict(os.environ, {}, clear=True):
            s = AppSettings()
        assert s.disable_redis_pubsub is False

    def test_disable_redis_pubsub_from_env(self):
        with patch.dict(os.environ, {"DISABLE_REDIS_PUBSUB": "1"}):
            s = AppSettings()
        assert s.disable_redis_pubsub is True


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

    def test_get_settings_cached(self, reset_settings):
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_production_rejects_empty_secrets(self):
        with pytest.raises(ValueError, match="Missing required secrets"):
            Settings(
                app=AppSettings(environment="production"),
                postgres=PostgresSettings(database_url=""),
                neo4j=Neo4jSettings(password=""),
                auth=AuthSettings(entra_tenant_id="t", entra_client_id="c"),
            )

    def test_staging_rejects_empty_secrets(self):
        with pytest.raises(ValueError, match="Missing required secrets"):
            Settings(
                app=AppSettings(environment="staging"),
                postgres=PostgresSettings(database_url="postgresql://u:p@h/d"),
                neo4j=Neo4jSettings(password=""),
                auth=AuthSettings(entra_tenant_id="t", entra_client_id="c"),
            )

    def test_production_accepts_all_secrets_set(self):
        s = Settings(
            app=AppSettings(environment="production"),
            postgres=PostgresSettings(database_url="postgresql://prod:secure@host/db"),
            neo4j=Neo4jSettings(password="secure-neo4j-password"),
            auth=AuthSettings(entra_tenant_id="t", entra_client_id="c"),
        )
        assert s.app.environment == "production"

    def test_dev_allows_empty_secrets(self):
        s = Settings(
            postgres=PostgresSettings(database_url=""),
            neo4j=Neo4jSettings(password=""),
            auth=AuthSettings(),
        )
        assert s.postgres.database_url == ""
        assert s.neo4j.password == ""
        assert s.auth.entra_tenant_id == ""

    def test_production_rejects_dev_autologin(self):
        with pytest.raises(ValueError, match="allow_dev_autologin must be False"):
            Settings(
                app=AppSettings(environment="production", allow_dev_autologin=True),
                postgres=PostgresSettings(database_url="postgresql://prod:secure@host/db"),
                neo4j=Neo4jSettings(password="secure-neo4j-password"),
                auth=AuthSettings(entra_tenant_id="t", entra_client_id="c"),
            )

    def test_staging_rejects_dev_autologin(self):
        with pytest.raises(ValueError, match="allow_dev_autologin must be False"):
            Settings(
                app=AppSettings(environment="staging", allow_dev_autologin=True),
                postgres=PostgresSettings(database_url="postgresql://prod:secure@host/db"),
                neo4j=Neo4jSettings(password="secure-neo4j-password"),
                auth=AuthSettings(entra_tenant_id="t", entra_client_id="c"),
            )

    def test_dev_allows_dev_autologin(self):
        s = Settings(
            app=AppSettings(environment="dev", allow_dev_autologin=True),
        )
        assert s.app.allow_dev_autologin is True


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
