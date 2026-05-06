"""
Pydantic models for the QPrisma caching system.

These models are used for:
- Cache configuration
- Metrics responses
- Cache endpoint request/response
"""

from enum import Enum

from pydantic import BaseModel, Field


class CacheBackend(str, Enum):
    """Active cache backend"""

    MEMORY = "memory"
    DISABLED = "disabled"


class CacheTypeEnum(str, Enum):
    """Types of cached data"""

    SEARCH_RESULT = "search_result"
    GRAPH_QUERY = "graph_query"


# =============================================================================
# Configuration
# =============================================================================


class CacheTTLConfig(BaseModel):
    """TTL configuration per cache type"""

    search_result_ttl: int = Field(default=300, description="TTL for search results (5 min)")
    graph_query_ttl: int = Field(default=600, description="TTL for graph queries (10 min)")


class CacheConfigResponse(BaseModel):
    """Cache configuration response (credentials redacted for security)."""

    enabled: bool = Field(description="Whether the cache is enabled")
    key_prefix: str = Field(description="Cache key prefix")
    max_memory_items: int = Field(description="Max items in memory cache")
    ttl: CacheTTLConfig = Field(default_factory=CacheTTLConfig)


# =============================================================================
# Metrics
# =============================================================================


class CacheMetricsResponse(BaseModel):
    """Cache metrics endpoint response"""

    connected: bool = Field(description="Whether there is an active connection")
    backend: CacheBackend = Field(description="Active backend (memory/disabled)")
    hits: int = Field(default=0, description="Number of cache hits")
    misses: int = Field(default=0, description="Number of cache misses")
    errors: int = Field(default=0, description="Number of errors")
    hit_rate: str = Field(description="Hit rate (percentage)")
    bytes_saved: int = Field(default=0, description="Estimated bytes saved")
    api_calls_saved: int = Field(default=0, description="API calls avoided")
    estimated_cost_saved: str = Field(description="Estimated cost saved (USD)")

    model_config = {
        "json_schema_extra": {
            "example": {
                "connected": True,
                "backend": "memory",
                "hits": 1250,
                "misses": 320,
                "errors": 2,
                "hit_rate": "79.62%",
                "bytes_saved": 15728640,
                "api_calls_saved": 1250,
                "estimated_cost_saved": "$12.50",
            }
        }
    }

# =============================================================================
# Requests
# =============================================================================


class CacheInvalidateRequest(BaseModel):
    """Request to invalidate cache"""

    pattern: str | None = Field(
        default=None, description="Glob pattern to invalidate (e.g.: 'qprisma:search:*')"
    )
    video_id: str | None = Field(default=None, description="Video ID to invalidate all its cache")
    cache_type: CacheTypeEnum | None = Field(
        default=None, description="Cache type to invalidate completely"
    )
    clear_all: bool = Field(default=False, description="If true, clears ALL cache (dangerous)")

    model_config = {
        "json_schema_extra": {
            "example": {"video_id": "abc123", "cache_type": None, "clear_all": False}
        }
    }


class CacheInvalidateResponse(BaseModel):
    """Cache invalidation response"""

    success: bool
    keys_deleted: int
    message: str
