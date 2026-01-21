"""
Application Configuration

Centralized configuration using Pydantic Settings.
All environment variables are loaded and validated here.
"""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    database_url: str = Field(
        default="postgresql://qprisma:qprisma123@localhost:5432/qprisma"
    )

    @property
    def is_configured(self) -> bool:
        return bool(self.database_url)


class Neo4jSettings(BaseSettings):
    """Neo4j Knowledge Graph configuration."""

    model_config = SettingsConfigDict(env_prefix="NEO4J_", extra="ignore")

    uri: str = Field(default="bolt://localhost:7687")
    user: str = Field(default="neo4j")
    password: str = Field(default="qprisma123")
    database: str = Field(default="neo4j")


class RedisSettings(BaseSettings):
    """Redis configuration for Celery."""

    model_config = SettingsConfigDict(env_prefix="REDIS_", extra="ignore")

    url: str = Field(default="redis://localhost:6379/0")


class AuthSettings(BaseSettings):
    """Authentication configuration."""

    model_config = SettingsConfigDict(extra="ignore")

    jwt_secret_key: str = Field(default="your-secret-key-change-in-production")
    jwt_algorithm: str = Field(default="HS256")
    jwt_access_token_expire_minutes: int = Field(default=1440)  # 24 hours

    @field_validator("jwt_secret_key")
    @classmethod
    def warn_default_secret(cls, v: str) -> str:
        if v == "your-secret-key-change-in-production":
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
    debug: bool = Field(default=False)

    # Server
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)

    # Processing defaults
    default_max_frames: int = Field(default=20)
    default_frame_interval: int = Field(default=30)

    # CORS
    cors_origins: list[str] = Field(default=["http://localhost:3000", "http://127.0.0.1:3000"])

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


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Uses lru_cache to ensure settings are only loaded once.
    """
    return Settings()


# Convenience exports
settings = get_settings()
