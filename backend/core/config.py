"""
Application Configuration

Centralized configuration using Pydantic Settings.
All environment variables are loaded and validated here.
"""

import os
from functools import lru_cache
from typing import TYPE_CHECKING

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from openai import AzureOpenAI


def _is_production() -> bool:
    """Check if running in production environment."""
    env = os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "dev"))
    return env.lower() in ("production", "prod")


class AzureSettings(BaseSettings):
    """Azure service configuration."""

    model_config = SettingsConfigDict(env_prefix="AZURE_", extra="ignore")

    # Storage
    storage_connection_string: str | None = Field(default=None)
    storage_container_name: str = Field(default="media")

    # OpenAI
    openai_endpoint: str | None = Field(default=None)
    openai_api_key: str | None = Field(default=None)
    openai_api_version: str = Field(default="2024-08-01-preview")
    openai_deployment_gpt: str = Field(default="gpt-4o")
    openai_deployment_embedding: str = Field(default="text-embedding-3-large")
    openai_deployment_whisper: str = Field(default="whisper")
    openai_whisper_rpm: int = Field(default=3, description="Whisper requests per minute limit")
    # Global Batch deployment for 50% cost savings on bulk processing
    openai_deployment_gpt_batch: str | None = Field(
        default=None,
        description="Azure OpenAI Global Batch deployment name (e.g., 'gpt-4o-global-batch')"
    )

    @property
    def is_openai_configured(self) -> bool:
        return bool(self.openai_endpoint and self.openai_api_key)

    @property
    def is_storage_configured(self) -> bool:
        return bool(self.storage_connection_string)

    @property
    def is_batch_configured(self) -> bool:
        """Check if Global Batch deployment is configured."""
        return bool(self.openai_deployment_gpt_batch)


class BatchAPISettings(BaseSettings):
    """Azure OpenAI Batch API configuration."""

    model_config = SettingsConfigDict(env_prefix="BATCH_", extra="ignore")

    # Batch processing settings
    check_interval_seconds: int = Field(default=30, description="Polling interval for batch status")
    max_wait_time_seconds: int = Field(default=3600, description="Maximum wait time (1 hour)")


class PostgresSettings(BaseSettings):
    """PostgreSQL database configuration (replaces Cosmos DB)."""

    model_config = SettingsConfigDict(extra="ignore")

    # In production, DATABASE_URL must be set via environment variable
    database_url: str = Field(
        default="postgresql://qprisma:qprisma123@localhost:5432/qprisma",
        description="PostgreSQL connection URL. Override in production!",
    )

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """Warn about default credentials in production."""
        if _is_production() and "qprisma123" in v:
            raise ValueError(
                "Default database credentials detected in production. "
                "Set DATABASE_URL environment variable with secure credentials."
            )
        return v

    @property
    def is_configured(self) -> bool:
        return bool(self.database_url)


class Neo4jSettings(BaseSettings):
    """Neo4j Knowledge Graph configuration."""

    model_config = SettingsConfigDict(env_prefix="NEO4J_", extra="ignore")

    uri: str = Field(default="bolt://localhost:7687")
    user: str = Field(default="neo4j")
    # Password should be set via NEO4J_PASSWORD environment variable
    password: str = Field(
        default="qprisma123",
        description="Neo4j password. Override via NEO4J_PASSWORD in production!",
    )
    database: str = Field(default="neo4j")

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Warn about default password in production."""
        if _is_production() and v == "qprisma123":
            raise ValueError(
                "Default Neo4j password detected in production. "
                "Set NEO4J_PASSWORD environment variable."
            )
        return v

    @property
    def is_configured(self) -> bool:
        return bool(self.uri)


class RedisSettings(BaseSettings):
    """Redis configuration for Celery."""

    model_config = SettingsConfigDict(env_prefix="REDIS_", extra="ignore")

    url: str = Field(default="redis://localhost:6379/0")

    @property
    def is_configured(self) -> bool:
        return bool(self.url)


class AuthSettings(BaseSettings):
    """Authentication configuration."""

    model_config = SettingsConfigDict(extra="ignore")

    # JWT secret MUST be set via JWT_SECRET_KEY environment variable in production
    jwt_secret_key: str = Field(
        default="your-secret-key-change-in-production",
        description="JWT signing secret. MUST be changed in production!",
    )
    jwt_algorithm: str = Field(default="HS256")
    jwt_access_token_expire_minutes: int = Field(default=1440)  # 24 hours

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        """Enforce secure JWT secret in production."""
        if _is_production():
            if v == "your-secret-key-change-in-production":
                raise ValueError(
                    "Default JWT secret detected in production. "
                    "Set JWT_SECRET_KEY environment variable with a secure random string."
                )
            if len(v) < 32:
                raise ValueError(
                    "JWT_SECRET_KEY must be at least 32 characters in production."
                )
        elif v == "your-secret-key-change-in-production":
            import warnings
            warnings.warn(
                "Using default JWT secret key. Set JWT_SECRET_KEY in production!",
                UserWarning,
                stacklevel=2,
            )
        return v


class AppSettings(BaseSettings):
    """Main application settings."""

    model_config = SettingsConfigDict(extra="ignore")

    # App info
    app_name: str = Field(default="QPrisma API")
    app_version: str = Field(default="0.2.0")
    environment: str = Field(default="dev")
    log_level: str = Field(default="INFO")
    debug: bool = Field(default=False)

    # Server
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)

    # Processing defaults
    default_max_frames: int = Field(default=20)
    default_frame_interval: int = Field(default=30)

    # CORS
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v


class Settings(BaseSettings):
    """Root settings container."""

    model_config = SettingsConfigDict(extra="ignore")

    app: AppSettings = Field(default_factory=AppSettings)
    azure: AzureSettings = Field(default_factory=AzureSettings)
    batch: BatchAPISettings = Field(default_factory=BatchAPISettings)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    neo4j: Neo4jSettings = Field(default_factory=Neo4jSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)

    def apply_env_overrides(self) -> None:
        env = os.getenv("APP_ENV") or os.getenv("ENVIRONMENT")
        if env:
            self.app.environment = env
        log_level = os.getenv("LOG_LEVEL")
        if log_level:
            self.app.log_level = log_level
        port = os.getenv("API_PORT") or os.getenv("PORT")
        if port:
            try:
                self.app.port = int(port)
            except ValueError:
                pass
        env_origins = os.getenv("ALLOWED_ORIGINS") or os.getenv("CORS_ORIGINS")
        if env_origins:
            self.app.cors_origins = [
                origin.strip() for origin in env_origins.split(",") if origin.strip()
            ]
        neo4j_uri = os.getenv("NEO4J_URI")
        if neo4j_uri:
            self.neo4j.uri = neo4j_uri
        redis_url = os.getenv("REDIS_URL")
        if redis_url:
            self.redis.url = redis_url


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Uses lru_cache to ensure settings are only loaded once.
    """
    settings_obj = Settings()
    settings_obj.apply_env_overrides()
    return settings_obj


def create_azure_openai_client() -> "AzureOpenAI":
    """
    Create and return an Azure OpenAI client using environment configuration.
    
    This is the canonical factory function for creating Azure OpenAI clients.
    Use this instead of creating clients directly to ensure consistent configuration.
    
    Returns:
        Configured AzureOpenAI client instance.
        
    Raises:
        ValueError: If required Azure OpenAI configuration is missing.
    """
    from openai import AzureOpenAI
    
    azure_settings = get_settings().azure
    
    if not azure_settings.is_openai_configured:
        raise ValueError(
            "Azure OpenAI not configured. Set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY."
        )
    
    return AzureOpenAI(
        api_key=azure_settings.openai_api_key,
        api_version=azure_settings.openai_api_version,
        azure_endpoint=azure_settings.openai_endpoint,
    )


# Convenience exports
settings = get_settings()
