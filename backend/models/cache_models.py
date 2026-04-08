"""
Pydantic models for the QPrisma caching system.

These models are used for:
- Cache configuration
- Metrics responses
- Cache endpoint request/response
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class CacheBackend(str, Enum):
    """Active cache backend"""

    REDIS = "redis"
    MEMORY = "memory"
    DISABLED = "disabled"


class CacheTypeEnum(str, Enum):
    """Types of cached data"""

    EMBEDDING = "embedding"
    FRAME_ANALYSIS = "frame_analysis"
    FRAME_HASH = "frame_hash"
    VIDEO_METADATA = "video_metadata"
    SEARCH_RESULT = "search_result"
    JOB_STATUS = "job_status"


# =============================================================================
# Configuration
# =============================================================================


class CacheTTLConfig(BaseModel):
    """TTL configuration per cache type"""

    embedding_ttl: int = Field(default=604800, description="TTL for embeddings (7 days)")
    frame_analysis_ttl: int = Field(default=259200, description="TTL for frame analysis (3 days)")
    frame_hash_ttl: int = Field(default=604800, description="TTL for perceptual hashes (7 days)")
    video_metadata_ttl: int = Field(default=3600, description="TTL for video metadata (1 hour)")
    search_result_ttl: int = Field(default=300, description="TTL for search results (5 min)")
    job_status_ttl: int = Field(default=3600, description="TTL for job status (1 hour)")


class CacheSettings(BaseModel):
    """General cache system configuration"""

    enabled: bool = Field(default=True, description="Whether the cache is enabled")
    redis_url: str | None = Field(default=None, description="Redis URL")
    key_prefix: str = Field(default="qprisma", description="Key prefix")
    similarity_threshold: int = Field(
        default=8,
        ge=0,
        le=64,
        description="Frame similarity threshold (0-64, lower = more strict)",
    )
    max_memory_items: int = Field(
        default=1000, ge=100, description="Max items in memory cache (fallback)"
    )
    ttl: CacheTTLConfig = Field(default_factory=CacheTTLConfig)

    model_config = {
        "json_schema_extra": {
            "example": {
                "enabled": True,
                "redis_url": "redis://localhost:6379/0",
                "key_prefix": "qprisma",
                "similarity_threshold": 8,
                "max_memory_items": 1000,
                "ttl": {"embedding_ttl": 604800, "frame_analysis_ttl": 259200},
            }
        }
    }


class CacheConfigResponse(BaseModel):
    """Cache configuration response (credentials redacted for security)."""

    enabled: bool = Field(description="Whether the cache is enabled")
    key_prefix: str = Field(description="Cache key prefix")
    similarity_threshold: int = Field(description="Frame similarity threshold (0-64)")
    max_memory_items: int = Field(description="Max items in memory cache")
    ttl: CacheTTLConfig = Field(default_factory=CacheTTLConfig)


# =============================================================================
# Metrics
# =============================================================================


class CacheMetricsResponse(BaseModel):
    """Cache metrics endpoint response"""

    connected: bool = Field(description="Whether there is an active connection")
    backend: CacheBackend = Field(description="Active backend (redis/memory)")
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
                "backend": "redis",
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


class CacheStatsPerType(BaseModel):
    """Detailed statistics per cache type"""

    type: CacheTypeEnum
    keys_count: int = Field(description="Number of keys of this type")
    memory_usage_bytes: int = Field(description="Estimated memory usage")
    avg_ttl_remaining: int | None = Field(description="Average remaining TTL in seconds")


class CacheDetailedStats(BaseModel):
    """Detailed cache statistics"""

    metrics: CacheMetricsResponse
    stats_per_type: list[CacheStatsPerType]
    redis_info: dict[str, Any] | None = Field(
        default=None, description="Redis info (only if backend is redis)"
    )


# =============================================================================
# Requests
# =============================================================================


class CacheInvalidateRequest(BaseModel):
    """Request to invalidate cache"""

    pattern: str | None = Field(
        default=None, description="Glob pattern to invalidate (e.g.: 'qprisma:embedding:*')"
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


# =============================================================================
# Job Status (for WebSocket/polling)
# =============================================================================


class ProcessingStage(str, Enum):
    """Processing pipeline stages"""

    QUEUED = "queued"
    DOWNLOADING = "downloading"
    EXTRACTING_FRAMES = "extracting_frames"
    ANALYZING_FRAMES = "analyzing_frames"
    GENERATING_EMBEDDINGS = "generating_embeddings"
    TRANSCRIBING_AUDIO = "transcribing_audio"
    INDEXING = "indexing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobStatusCache(BaseModel):
    """Job status stored in cache"""

    job_id: str
    video_id: str
    status: ProcessingStage
    progress: int = Field(ge=0, le=100, description="Progress 0-100")
    current_stage: str
    message: str | None = None
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    error: str | None = None
    frames_processed: int = 0
    frames_total: int = 0
    estimated_time_remaining: int | None = Field(
        default=None, description="Estimated remaining seconds"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "job_id": "job_abc123",
                "video_id": "video_xyz789",
                "status": "analyzing_frames",
                "progress": 45,
                "current_stage": "Analyzing frames with GPT-4V",
                "message": "Processing frame 45 of 100",
                "started_at": "2026-01-08T10:00:00Z",
                "updated_at": "2026-01-08T10:05:30Z",
                "frames_processed": 45,
                "frames_total": 100,
                "estimated_time_remaining": 180,
            }
        }
    }


# =============================================================================
# Cached Embeddings
# =============================================================================


class CachedEmbedding(BaseModel):
    """Embedding stored in cache with metadata"""

    content_hash: str = Field(description="SHA256 hash of the content")
    embedding: list[float] = Field(description="Embedding vector")
    model: str = Field(default="text-embedding-3-large")
    dimensions: int = Field(description="Vector dimensions")
    cached_at: datetime
    expires_at: datetime
    source_type: str = Field(description="Source type (text, frame, audio)")

    model_config = {
        "json_schema_extra": {
            "example": {
                "content_hash": "a1b2c3d4e5f6...",
                "embedding": [0.123, -0.456, 0.789],
                "model": "text-embedding-3-large",
                "dimensions": 3072,
                "cached_at": "2026-01-08T10:00:00Z",
                "expires_at": "2026-01-15T10:00:00Z",
                "source_type": "frame",
            }
        }
    }


class CachedFrameAnalysis(BaseModel):
    """Frame analysis stored in cache"""

    frame_hash: str = Field(description="Frame hash (content)")
    perceptual_hash: str | None = Field(description="Perceptual hash (similarity)")
    analysis: dict[str, Any] = Field(description="GPT-4V analysis result")
    model: str = Field(default="gpt-4o")
    cached_at: datetime
    expires_at: datetime
    was_deduplicated: bool = Field(
        default=False, description="Whether it was reused from a similar frame"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "frame_hash": "abc123...",
                "perceptual_hash": "f0e1d2c3b4a5...",
                "analysis": {
                    "description": "A person speaking at a presentation",
                    "objects": ["person", "microphone", "screen"],
                    "scene_type": "conference",
                },
                "model": "gpt-4o",
                "cached_at": "2026-01-08T10:00:00Z",
                "expires_at": "2026-01-11T10:00:00Z",
                "was_deduplicated": False,
            }
        }
    }


# =============================================================================
# Cache Warm-up
# =============================================================================


class CacheWarmupRequest(BaseModel):
    """Request to pre-warm the cache"""

    video_ids: list[str] = Field(description="Video IDs to pre-load")
    include_embeddings: bool = Field(default=True)
    include_analysis: bool = Field(default=True)


class CacheWarmupResponse(BaseModel):
    """Cache warm-up response"""

    success: bool
    videos_processed: int
    items_cached: int
    duration_seconds: float
    errors: list[str] = Field(default_factory=list)
