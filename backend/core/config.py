"""
Application Configuration

Centralized configuration using Pydantic Settings.
All environment variables are loaded and validated here.
"""

import importlib.metadata
import os
from functools import lru_cache
from typing import TYPE_CHECKING

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, EnvSettingsSource, SettingsConfigDict

if TYPE_CHECKING:
    from openai import AsyncAzureOpenAI, AzureOpenAI

try:
    _PKG_VERSION = importlib.metadata.version("qprisma-backend")
except importlib.metadata.PackageNotFoundError:
    _PKG_VERSION = "0.0.0-dev"


def _is_production() -> bool:
    """Check if running in production environment."""
    env = os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "dev"))
    return env.lower() in ("production", "prod")


class _GracefulEnvSource(EnvSettingsSource):
    """Env source that falls back to raw strings when JSON parsing fails.

    pydantic-settings tries to JSON-decode complex types (list, dict) from
    env vars. Comma-separated values like ``http://a.com,http://b.com`` are
    not valid JSON and would raise. This subclass catches the decode error
    and passes the raw string through so field validators can handle it.
    """

    def decode_complex_value(self, field_name, field_info, value):  # type: ignore[override]
        try:
            return super().decode_complex_value(field_name, field_info, value)
        except ValueError:
            return value


class AzureSettings(BaseSettings):
    """Azure service configuration."""

    model_config = SettingsConfigDict(env_prefix="AZURE_", extra="ignore")

    # Storage
    use_managed_identity: bool = Field(default=False)
    storage_account_url: str | None = Field(default=None)
    storage_connection_string: str | None = Field(default=None)
    storage_container_name: str = Field(default="media")

    # OpenAI
    openai_endpoint: str | None = Field(default=None)
    openai_api_key: str | None = Field(default=None)
    openai_api_version: str = Field(default="2024-08-01-preview")
    openai_deployment_gpt: str = Field(default="gpt-5.4-pro")
    openai_deployment_embedding: str = Field(default="text-embedding-3-large")
    openai_deployment_whisper: str = Field(default="whisper")
    openai_agent_temperature: float = Field(
        default=0.2,
        ge=0.0,
        le=2.0,
        description="Temperature for hosted video-agent answer generation.",
    )
    openai_reasoning_models: str = Field(
        default="gpt-5.4-pro,gpt-5.3-chat,gpt-5.2-chat,gpt-5",
        description=(
            "Comma-separated deployment names for reasoning-class models that reject "
            "custom temperature values. Matched as exact name or as prefix (e.g. 'gpt-5')."
        ),
    )
    openai_whisper_rpm: int = Field(default=3, description="Whisper requests per minute limit")
    max_concurrent_transcriptions: int = Field(
        default=3,
        description="Maximum concurrent Whisper transcription requests (match RPM limit)",
    )
    # Global Batch deployment for 50% cost savings on bulk processing
    openai_deployment_gpt_batch: str | None = Field(
        default=None,
        description="Azure OpenAI Global Batch deployment name (e.g., 'gpt-4o-global-batch')",
    )

    # Whisper backend: "azure" (default) or "faster_whisper" (local CTranslate2)
    whisper_backend: str = Field(
        default="azure",
        description="Transcription backend: 'azure' for Azure OpenAI Whisper API, "
        "'faster_whisper' for local CTranslate2-based inference",
    )
    faster_whisper_model: str = Field(
        default="large-v3",
        description="faster-whisper model size "
        "(e.g., 'tiny', 'base', 'small', 'medium', 'large-v3')",
    )
    faster_whisper_device: str = Field(
        default="auto",
        description="Device for faster-whisper: 'auto', 'cpu', or 'cuda'",
    )
    faster_whisper_compute_type: str = Field(
        default="int8",
        description="Compute type for faster-whisper: 'int8', 'float16', or 'float32'",
    )
    faster_whisper_batch_size: int = Field(
        default=16,
        description="Batch size for faster-whisper batched inference pipeline",
    )

    @property
    def is_openai_configured(self) -> bool:
        return bool(self.openai_endpoint and (self.openai_api_key or self.use_managed_identity))

    @property
    def is_storage_configured(self) -> bool:
        return bool(
            self.storage_connection_string
            or (self.use_managed_identity and self.storage_account_url)
        )

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

    # DATABASE_URL must be set via environment variable or .env file
    database_url: str = Field(
        default="postgresql://qprisma:qprisma123@localhost:5432/qprisma",
        description="PostgreSQL connection URL. Must be set via DATABASE_URL env var.",
    )

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """Reject hardcoded default credentials in production."""
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

    # Local dev: bolt://localhost:7687 | AuraDB: neo4j+s://xxxx.databases.neo4j.io
    uri: str = Field(default="bolt://localhost:7687")
    user: str = Field(default="neo4j")
    # Password must be set via NEO4J_PASSWORD environment variable or .env file
    password: str = Field(
        default="",
        description="Neo4j password. Must be set via NEO4J_PASSWORD env var.",
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


class BenchmarkSettings(BaseSettings):
    """Benchmark automation configuration."""

    model_config = SettingsConfigDict(env_prefix="BENCHMARK_", extra="ignore")

    default_user_id: str = Field(default="user_7541242e88e3")
    api_token: str | None = Field(
        default=None,
        description="Shared secret for GitHub Actions benchmark orchestration.",
    )


class ProcessingSettings(BaseSettings):
    """Video processing performance configuration."""

    model_config = SettingsConfigDict(env_prefix="PROCESSING_", extra="ignore")

    # Embedding batching
    embedding_batch_size: int = Field(
        default=512,
        description="Batch size for embedding API calls (adaptive retry halves on failure)",
    )

    # Thread pool sizing for FFmpeg extraction
    max_extraction_workers: int | None = Field(
        default=None,
        description="Max FFmpeg extraction workers. None = auto-detect from CPU count.",
    )

    # Frame encoding for Vision API
    frame_encoding_format: str = Field(
        default="webp",
        description="Frame encoding format for Vision API: 'webp' (smaller) or 'jpeg'",
    )
    frame_encoding_quality: int = Field(
        default=80,
        description="Frame encoding quality (1-100)",
        ge=1,
        le=100,
    )
    frame_max_dimension: int = Field(
        default=2048,
        description="Maximum dimension (width or height) for frames sent to Vision API",
        gt=0,
    )

    # Streaming pipeline (opt-in; batch extraction remains default)
    streaming_pipeline_enabled: bool = Field(
        default=False,
        description=(
            "Enable async-generator streaming pipeline for frame extraction. "
            "Reduces peak memory from O(all_frames) to O(streaming_batch_size)."
        ),
    )
    streaming_batch_size: int = Field(
        default=32,
        description="Number of frames to accumulate before processing a batch in streaming mode.",
        gt=0,
    )

    # Entity extraction gleaning (GraphRAG multi-pass)
    max_gleanings: int = Field(
        default=1,
        description="Number of gleaning passes for entity extraction "
        "(0 = disabled, 1 = recommended).",
        ge=0,
        le=3,
    )


class ArtifactSettings(BaseSettings):
    """Tool artifact storage configuration."""

    model_config = SettingsConfigDict(env_prefix="ARTIFACT_", extra="ignore")

    cache_ttl_seconds: int = Field(default=21600)
    cache_key_prefix: str = Field(default="tool_artifact")
    blob_prefix: str = Field(default="tool-artifacts")


class CommunitySettings(BaseSettings):
    """Community detection & hierarchical graph summarization configuration."""

    model_config = SettingsConfigDict(env_prefix="COMMUNITY_", extra="ignore")

    enabled: bool = Field(
        default=True,
        description="Enable community detection during video processing pipeline.",
    )
    algorithm: str = Field(
        default="leiden",
        description="Community detection algorithm: "
        "'leiden', 'louvain', or 'connected_components'.",
    )
    resolution: float = Field(
        default=1.0,
        description="Resolution parameter for Leiden/Louvain (higher = smaller communities).",
        gt=0.0,
    )
    hierarchical_levels: int = Field(
        default=2,
        description="Number of hierarchical levels for Leiden "
        "community detection (1 = flat, 2+ = hierarchical).",
        ge=1,
        le=5,
    )
    min_community_size: int = Field(
        default=3,
        description="Minimum number of entities required to form a community.",
        ge=2,
    )
    min_entity_occurrences: int = Field(
        default=2,
        description="Minimum entity occurrence count to include in community graph.",
        ge=1,
    )
    max_communities_per_video: int = Field(
        default=20,
        description="Maximum number of communities to generate per video.",
        ge=1,
    )
    summary_max_tokens: int = Field(
        default=300,
        description="Max tokens for each community summary generation.",
        ge=50,
    )


class FoundrySettings(BaseSettings):
    """Azure AI Foundry Hosted Agent settings."""

    model_config = SettingsConfigDict(env_prefix="FOUNDRY_", extra="ignore")

    project_endpoint: str | None = Field(
        default=None,
        description="Azure AI Foundry project endpoint URL",
    )
    agent_name: str | None = Field(
        default=None,
        description="Name of the hosted agent in Foundry",
    )
    # Memory-store fields use a non-reserved env name (MEMORY_*) because
    # the FOUNDRY_* prefix is reserved by the Foundry hosted-agent platform.
    # The legacy FOUNDRY_MEMORY_* names remain accepted for local dev / .env.
    memory_store_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MEMORY_STORE_NAME", "FOUNDRY_MEMORY_STORE_NAME"),
        description="Name of the Foundry Memory Store for long-term user memory",
    )
    memory_chat_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MEMORY_CHAT_MODEL", "FOUNDRY_MEMORY_CHAT_MODEL"),
        description="Chat model deployment for memory extraction (e.g., gpt-5.4-pro)",
    )
    memory_embedding_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MEMORY_EMBEDDING_MODEL", "FOUNDRY_MEMORY_EMBEDDING_MODEL"),
        description="Embedding model deployment for memory search (e.g., text-embedding-3-large)",
    )
    request_timeout_seconds: float = Field(
        default=120.0,
        description="Per-call timeout (seconds) applied to the Foundry Responses API "
        "from the backend client. Wraps `responses.create` in `asyncio.wait_for` so "
        "frontend requests cannot hang indefinitely if the hosted agent stalls.",
        gt=0,
    )


class TelemetrySettings(BaseSettings):
    """Application Insights & OpenTelemetry tracing configuration."""

    model_config = SettingsConfigDict(extra="ignore")

    applicationinsights_connection_string: str | None = Field(
        default=None,
        description="Azure Application Insights connection string for distributed tracing",
    )
    otel_service_name: str = Field(
        default="qprisma-api",
        description="OpenTelemetry service name for trace attribution",
    )
    enable_content_recording: bool = Field(
        default=False,
        description="Record GenAI prompt/completion content in traces (may contain PII)",
    )


class SearchSettings(BaseSettings):
    """Hybrid search and HNSW vector index configuration."""

    model_config = SettingsConfigDict(env_prefix="SEARCH_", extra="ignore")

    hnsw_m: int = Field(
        default=16,
        description="HNSW M parameter (max connections per node). "
        "Higher = better recall, more memory.",
        ge=4,
        le=64,
    )
    hnsw_ef_construction: int = Field(
        default=256,
        description="HNSW ef_construction (build-time search width). "
        "Higher = better recall, slower build.",
        ge=64,
        le=1024,
    )


class AuthSettings(BaseSettings):
    """Authentication configuration — Microsoft Entra ID (OIDC)."""

    model_config = SettingsConfigDict(extra="ignore")

    # Microsoft Entra ID settings
    entra_tenant_id: str = Field(
        default="",
        description="Microsoft Entra ID tenant ID. Set via ENTRA_TENANT_ID env var.",
    )
    entra_client_id: str = Field(
        default="",
        description="Backend API app registration client ID. Set via ENTRA_CLIENT_ID env var.",
    )
    entra_api_scope: str = Field(
        default="",
        description="API scope exposed by the backend app registration (e.g. api://<id>/access_as_user).",
    )

    @model_validator(mode="after")
    def _validate_entra_config(self) -> "AuthSettings":
        """Enforce Entra ID configuration in production."""
        if _is_production():
            missing = []
            if not self.entra_tenant_id:
                missing.append("ENTRA_TENANT_ID")
            if not self.entra_client_id:
                missing.append("ENTRA_CLIENT_ID")
            if missing:
                raise ValueError(
                    f"Entra ID not configured for production. Set: {', '.join(missing)}"
                )
        return self


class AppSettings(BaseSettings):
    """Main application settings."""

    model_config = SettingsConfigDict(extra="ignore")

    # App info
    app_name: str = Field(default="QPrisma API")
    app_version: str = Field(default=_PKG_VERSION)
    environment: str = Field(
        default="dev",
        validation_alias=AliasChoices("app_env", "environment"),
    )
    log_level: str = Field(default="INFO")
    debug: bool = Field(default=False)

    # Server
    host: str = Field(default="0.0.0.0")  # noqa: S104
    port: int = Field(
        default=8000,
        validation_alias=AliasChoices("api_port", "port"),
    )

    # Processing defaults
    default_max_frames: int = Field(default=20)
    default_frame_interval: int = Field(default=30)
    video_decoder_backend: str = Field(
        default="pyav",
        description="Video decoder backend: 'pyav' (in-process) or 'ffmpeg_subprocess'",
    )

    # Dev auth
    allow_dev_autologin: bool = Field(
        default=False, description="Enable dev auto-login. NEVER set to True in production!"
    )

    # API base URL (used for A2A agent cards, etc.)
    api_base_url: str = Field(
        default="http://localhost:8000",
        validation_alias=AliasChoices("a2a_base_url", "api_base_url"),
    )

    # Logging
    log_file: str | None = Field(default=None)

    # Startup / runtime toggles
    disable_startup_healthchecks: bool = Field(
        default=False, description="Skip health checks on startup"
    )
    disable_redis_pubsub: bool = Field(default=False, description="Disable Redis pub/sub listener")

    # CORS
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        validation_alias=AliasChoices("allowed_origins", "cors_origins"),
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):  # type: ignore[override]
        return (
            init_settings,
            _GracefulEnvSource(settings_cls),
            dotenv_settings,
            file_secret_settings,
        )


class Settings(BaseSettings):
    """Root settings container."""

    model_config = SettingsConfigDict(extra="ignore")

    app: AppSettings = Field(default_factory=AppSettings)
    azure: AzureSettings = Field(default_factory=AzureSettings)
    batch: BatchAPISettings = Field(default_factory=BatchAPISettings)
    processing: ProcessingSettings = Field(default_factory=ProcessingSettings)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    neo4j: Neo4jSettings = Field(default_factory=Neo4jSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    benchmark: BenchmarkSettings = Field(default_factory=BenchmarkSettings)
    artifacts: ArtifactSettings = Field(default_factory=ArtifactSettings)
    community: CommunitySettings = Field(default_factory=CommunitySettings)
    search: SearchSettings = Field(default_factory=SearchSettings)
    foundry: FoundrySettings = Field(default_factory=FoundrySettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    telemetry: TelemetrySettings = Field(default_factory=TelemetrySettings)

    @model_validator(mode="after")
    def _check_required_secrets(self) -> "Settings":
        """Reject empty credentials in production and staging environments."""
        env = self.app.environment.lower()
        if env not in ("production", "prod", "staging"):
            return self

        errors: list[str] = []
        if not self.postgres.database_url:
            errors.append("DATABASE_URL must be set")
        if not self.neo4j.password:
            errors.append("NEO4J_PASSWORD must be set")
        if not self.auth.entra_tenant_id or not self.auth.entra_client_id:
            errors.append("ENTRA_TENANT_ID and ENTRA_CLIENT_ID must be set")

        # Reject dev-only features in production
        if self.app.allow_dev_autologin:
            errors.append("allow_dev_autologin must be False in production/staging environments")

        if errors:
            raise ValueError(
                f"Missing required secrets for '{env}' environment: " + "; ".join(errors)
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Uses lru_cache to ensure settings are only loaded once.
    """
    return Settings()


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

    from core.azure_credentials import build_openai_client_kwargs

    azure_settings = get_settings().azure

    if not azure_settings.is_openai_configured:
        raise ValueError(
            "Azure OpenAI not configured. Set AZURE_OPENAI_ENDPOINT and either "
            "AZURE_OPENAI_API_KEY or AZURE_USE_MANAGED_IDENTITY=true."
        )

    client_kwargs = build_openai_client_kwargs(
        endpoint=azure_settings.openai_endpoint,
        api_key=azure_settings.openai_api_key,
        api_version=azure_settings.openai_api_version,
        use_managed_identity=azure_settings.use_managed_identity,
    )
    if client_kwargs is None:
        raise ValueError(
            "Azure OpenAI auth not configured. Set AZURE_OPENAI_API_KEY or "
            "AZURE_USE_MANAGED_IDENTITY=true."
        )
    return AzureOpenAI(**client_kwargs)


def create_async_azure_openai_client() -> "AsyncAzureOpenAI":
    """
    Create and return an async Azure OpenAI client using environment configuration.

    Use this for async contexts (FastAPI routes, async services).
    The async client shares the same configuration as the sync client.

    Returns:
        Configured AsyncAzureOpenAI client instance.

    Raises:
        ValueError: If required Azure OpenAI configuration is missing.
    """
    from openai import AsyncAzureOpenAI

    from core.azure_credentials import build_openai_client_kwargs

    azure_settings = get_settings().azure

    if not azure_settings.is_openai_configured:
        raise ValueError(
            "Azure OpenAI not configured. Set AZURE_OPENAI_ENDPOINT and either "
            "AZURE_OPENAI_API_KEY or AZURE_USE_MANAGED_IDENTITY=true."
        )

    client_kwargs = build_openai_client_kwargs(
        endpoint=azure_settings.openai_endpoint,
        api_key=azure_settings.openai_api_key,
        api_version=azure_settings.openai_api_version,
        use_managed_identity=azure_settings.use_managed_identity,
    )
    if client_kwargs is None:
        raise ValueError(
            "Azure OpenAI auth not configured. Set AZURE_OPENAI_API_KEY or "
            "AZURE_USE_MANAGED_IDENTITY=true."
        )
    return AsyncAzureOpenAI(**client_kwargs)


# Convenience exports
settings = get_settings()
