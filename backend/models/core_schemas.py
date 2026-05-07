"""Pydantic models for core API status endpoints."""

from pydantic import BaseModel, Field


class RootStatusResponse(BaseModel):
    """Public API root status response."""

    status: str = Field(..., description="API liveness status.")
    version: str = Field(..., description="Backend package version.")
    azure_configured: bool = Field(
        ...,
        description="Whether the core Azure OpenAI and Blob Storage clients are configured.",
    )


class HealthServicesResponse(BaseModel):
    """Component status summary returned by the public health endpoint."""

    api: str = Field(..., description="API process health.")
    blob_storage: str = Field(..., description="Blob Storage configuration or health status.")
    postgresql: str = Field(..., description="PostgreSQL connectivity status.")
    openai: str = Field(..., description="Azure OpenAI configuration status.")
    knowledge_graph: str = Field(..., description="Neo4j knowledge graph configuration status.")


class HealthCheckResponse(BaseModel):
    """Public API readiness response used by deployment probes."""

    status: str = Field(..., description="Overall API health status.")
    services: HealthServicesResponse
    timestamp: str = Field(..., description="UTC ISO-8601 response timestamp.")


class ConfigStatusResponse(BaseModel):
    """Public configuration status response."""

    azure_openai_configured: bool
    azure_storage_configured: bool
    postgresql_configured: bool
    knowledge_graph_configured: bool
    cache_backend: str
