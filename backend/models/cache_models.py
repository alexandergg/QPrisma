"""
Modelos Pydantic para el sistema de caching de QPrisma.

Estos modelos se usan para:
- Configuración del cache
- Respuestas de métricas
- Request/Response de endpoints de cache
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class CacheBackend(str, Enum):
    """Backend de cache activo"""

    REDIS = "redis"
    MEMORY = "memory"
    DISABLED = "disabled"


class CacheTypeEnum(str, Enum):
    """Tipos de datos cacheados"""

    EMBEDDING = "embedding"
    FRAME_ANALYSIS = "frame_analysis"
    FRAME_HASH = "frame_hash"
    VIDEO_METADATA = "video_metadata"
    SEARCH_RESULT = "search_result"
    JOB_STATUS = "job_status"


# =============================================================================
# Configuración
# =============================================================================


class CacheTTLConfig(BaseModel):
    """Configuración de TTL por tipo de cache"""

    embedding_ttl: int = Field(default=604800, description="TTL para embeddings (7 días)")
    frame_analysis_ttl: int = Field(
        default=259200, description="TTL para análisis de frames (3 días)"
    )
    frame_hash_ttl: int = Field(default=604800, description="TTL para hash perceptuales (7 días)")
    video_metadata_ttl: int = Field(default=3600, description="TTL para metadata de video (1 hora)")
    search_result_ttl: int = Field(
        default=300, description="TTL para resultados de búsqueda (5 min)"
    )
    job_status_ttl: int = Field(default=3600, description="TTL para estado de jobs (1 hora)")


class CacheSettings(BaseModel):
    """Configuración general del sistema de cache"""

    enabled: bool = Field(default=True, description="Si el cache está habilitado")
    redis_url: str | None = Field(default=None, description="URL de Redis")
    key_prefix: str = Field(default="qprisma", description="Prefijo para keys")
    similarity_threshold: int = Field(
        default=8,
        ge=0,
        le=64,
        description="Threshold para similitud de frames (0-64, menor = más estricto)",
    )
    max_memory_items: int = Field(
        default=1000, ge=100, description="Max items en cache de memoria (fallback)"
    )
    ttl: CacheTTLConfig = Field(default_factory=CacheTTLConfig)

    model_config = {"json_schema_extra": {
        "example": {
            "enabled": True,
            "redis_url": "redis://localhost:6379/0",
            "key_prefix": "qprisma",
            "similarity_threshold": 8,
            "max_memory_items": 1000,
            "ttl": {"embedding_ttl": 604800, "frame_analysis_ttl": 259200},
        }
    }}


# =============================================================================
# Métricas
# =============================================================================


class CacheMetricsResponse(BaseModel):
    """Respuesta del endpoint de métricas de cache"""

    connected: bool = Field(description="Si hay conexión activa")
    backend: CacheBackend = Field(description="Backend activo (redis/memory)")
    hits: int = Field(default=0, description="Número de cache hits")
    misses: int = Field(default=0, description="Número de cache misses")
    errors: int = Field(default=0, description="Número de errores")
    hit_rate: str = Field(description="Tasa de aciertos (porcentaje)")
    bytes_saved: int = Field(default=0, description="Bytes ahorrados estimados")
    api_calls_saved: int = Field(default=0, description="Llamadas a API evitadas")
    estimated_cost_saved: str = Field(description="Costo estimado ahorrado (USD)")

    model_config = {"json_schema_extra": {
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
    }}


class CacheStatsPerType(BaseModel):
    """Estadísticas detalladas por tipo de cache"""

    type: CacheTypeEnum
    keys_count: int = Field(description="Número de keys de este tipo")
    memory_usage_bytes: int = Field(description="Uso de memoria estimado")
    avg_ttl_remaining: int | None = Field(description="TTL promedio restante en segundos")


class CacheDetailedStats(BaseModel):
    """Estadísticas detalladas del cache"""

    metrics: CacheMetricsResponse
    stats_per_type: list[CacheStatsPerType]
    redis_info: dict[str, Any] | None = Field(
        default=None, description="Info de Redis (solo si backend es redis)"
    )


# =============================================================================
# Requests
# =============================================================================


class CacheInvalidateRequest(BaseModel):
    """Request para invalidar cache"""

    pattern: str | None = Field(
        default=None, description="Patrón glob para invalidar (ej: 'qprisma:embedding:*')"
    )
    video_id: str | None = Field(
        default=None, description="ID de video para invalidar todo su cache"
    )
    cache_type: CacheTypeEnum | None = Field(
        default=None, description="Tipo de cache a invalidar completamente"
    )
    clear_all: bool = Field(default=False, description="Si true, limpia TODO el cache (peligroso)")

    model_config = {"json_schema_extra": {
        "example": {"video_id": "abc123", "cache_type": None, "clear_all": False}
    }}


class CacheInvalidateResponse(BaseModel):
    """Respuesta de invalidación de cache"""

    success: bool
    keys_deleted: int
    message: str


# =============================================================================
# Estado de Jobs (para WebSocket/polling)
# =============================================================================


class ProcessingStage(str, Enum):
    """Etapas del pipeline de procesamiento"""

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
    """Estado de job almacenado en cache"""

    job_id: str
    video_id: str
    status: ProcessingStage
    progress: int = Field(ge=0, le=100, description="Progreso 0-100")
    current_stage: str
    message: str | None = None
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    error: str | None = None
    frames_processed: int = 0
    frames_total: int = 0
    estimated_time_remaining: int | None = Field(
        default=None, description="Segundos estimados restantes"
    )

    model_config = {"json_schema_extra": {
        "example": {
            "job_id": "job_abc123",
            "video_id": "video_xyz789",
            "status": "analyzing_frames",
            "progress": 45,
            "current_stage": "Analizando frames con GPT-4V",
            "message": "Procesando frame 45 de 100",
            "started_at": "2026-01-08T10:00:00Z",
            "updated_at": "2026-01-08T10:05:30Z",
            "frames_processed": 45,
            "frames_total": 100,
            "estimated_time_remaining": 180,
        }
    }}


# =============================================================================
# Embeddings cacheados
# =============================================================================


class CachedEmbedding(BaseModel):
    """Embedding almacenado en cache con metadata"""

    content_hash: str = Field(description="Hash SHA256 del contenido")
    embedding: list[float] = Field(description="Vector de embedding")
    model: str = Field(default="text-embedding-3-large")
    dimensions: int = Field(description="Dimensiones del vector")
    cached_at: datetime
    expires_at: datetime
    source_type: str = Field(description="Tipo de fuente (text, frame, audio)")

    model_config = {"json_schema_extra": {
        "example": {
            "content_hash": "a1b2c3d4e5f6...",
            "embedding": [0.123, -0.456, 0.789],
            "model": "text-embedding-3-large",
            "dimensions": 3072,
            "cached_at": "2026-01-08T10:00:00Z",
            "expires_at": "2026-01-15T10:00:00Z",
            "source_type": "frame",
        }
    }}


class CachedFrameAnalysis(BaseModel):
    """Análisis de frame almacenado en cache"""

    frame_hash: str = Field(description="Hash del frame (contenido)")
    perceptual_hash: str | None = Field(description="Hash perceptual (similitud)")
    analysis: dict[str, Any] = Field(description="Resultado del análisis GPT-4V")
    model: str = Field(default="gpt-4o")
    cached_at: datetime
    expires_at: datetime
    was_deduplicated: bool = Field(default=False, description="Si se reutilizó de un frame similar")

    model_config = {"json_schema_extra": {
        "example": {
            "frame_hash": "abc123...",
            "perceptual_hash": "f0e1d2c3b4a5...",
            "analysis": {
                "description": "Una persona hablando en una presentación",
                "objects": ["persona", "micrófono", "pantalla"],
                "scene_type": "conference",
            },
            "model": "gpt-4o",
            "cached_at": "2026-01-08T10:00:00Z",
            "expires_at": "2026-01-11T10:00:00Z",
            "was_deduplicated": False,
        }
    }}


# =============================================================================
# Warm-up de cache
# =============================================================================


class CacheWarmupRequest(BaseModel):
    """Request para pre-calentar cache"""

    video_ids: list[str] = Field(description="IDs de videos a pre-cargar")
    include_embeddings: bool = Field(default=True)
    include_analysis: bool = Field(default=True)


class CacheWarmupResponse(BaseModel):
    """Respuesta de warm-up de cache"""

    success: bool
    videos_processed: int
    items_cached: int
    duration_seconds: float
    errors: list[str] = Field(default_factory=list)
