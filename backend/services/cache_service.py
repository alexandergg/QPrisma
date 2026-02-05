"""
Cache Service para QPrisma
Implementa estrategias de caching para reducir costos de Azure OpenAI y mejorar latencia.

Estrategias implementadas:
1. Cache-Aside Pattern: Lee cache primero, si miss -> computa y guarda
2. Perceptual Hashing: Reutiliza embeddings para frames visualmente similares
3. TTL Inteligente: Diferentes TTL según tipo de contenido
4. Fallback a Memoria: Si Redis no está disponible, usa cache local

Uso:
    cache = CacheService()

    # Cache de embedding
    embedding = await cache.get_embedding(content_hash)
    if not embedding:
        embedding = compute_embedding(...)
        await cache.set_embedding(content_hash, embedding)

    # Cache de análisis con deduplicación de frames similares
    analysis = await cache.get_or_compute_frame_analysis(
        frame_bytes,
        compute_fn=lambda: analyze_with_gpt4v(frame)
    )
"""

import hashlib
import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from functools import wraps
from typing import Any, TypeVar

# Redis async client
try:
    import redis.asyncio as aioredis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    aioredis = None

# Perceptual hashing para imágenes
try:
    import io

    import imagehash
    from PIL import Image

    IMAGEHASH_AVAILABLE = True
except ImportError:
    IMAGEHASH_AVAILABLE = False
    imagehash = None

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CacheType(str, Enum):
    """Tipos de cache con diferentes TTLs y estrategias"""

    EMBEDDING = "embedding"  # Embeddings de texto/imagen
    FRAME_ANALYSIS = "frame_analysis"  # Análisis GPT-4V de frames
    FRAME_HASH = "frame_hash"  # Hash perceptual -> embedding key
    VIDEO_METADATA = "video_metadata"  # Metadata de videos
    SEARCH_RESULT = "search_result"  # Resultados de búsqueda
    JOB_STATUS = "job_status"  # Estado de jobs de procesamiento


@dataclass
class CacheConfig:
    """Configuración de TTL por tipo de cache"""

    ttl_seconds: dict[CacheType, int] = field(
        default_factory=lambda: {
            CacheType.EMBEDDING: 86400 * 7,  # 7 días - embeddings son estables
            CacheType.FRAME_ANALYSIS: 86400 * 3,  # 3 días - análisis puede cambiar con prompts
            CacheType.FRAME_HASH: 86400 * 7,  # 7 días - hash mappings
            CacheType.VIDEO_METADATA: 3600,  # 1 hora - metadata puede actualizarse
            CacheType.SEARCH_RESULT: 300,  # 5 min - resultados cambian con indexación
            CacheType.JOB_STATUS: 3600,  # 1 hora - estados de jobs
        }
    )

    # Threshold de similitud para perceptual hashing (0-64, menor = más similar)
    similarity_threshold: int = 8

    # Tamaño máximo de cache en memoria (fallback)
    max_memory_items: int = 1000

    # Prefijo para todas las keys en Redis
    key_prefix: str = "qprisma"


@dataclass
class CacheMetrics:
    """Métricas de rendimiento del cache"""

    hits: int = 0
    misses: int = 0
    errors: int = 0
    bytes_saved: int = 0  # Estimación de datos no transferidos
    api_calls_saved: int = 0  # Llamadas a Azure OpenAI evitadas

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "errors": self.errors,
            "hit_rate": f"{self.hit_rate:.2%}",
            "bytes_saved": self.bytes_saved,
            "api_calls_saved": self.api_calls_saved,
            "estimated_cost_saved": f"${self.api_calls_saved * 0.01:.2f}",  # ~$0.01 por llamada
        }


class InMemoryCache:
    """
    Cache en memoria como fallback cuando Redis no está disponible.
    Implementa LRU simple con TTL.
    """

    def __init__(self, max_items: int = 1000):
        self._cache: dict[str, tuple[Any, float]] = {}  # key -> (value, expiry_timestamp)
        self._max_items = max_items
        self._access_order: list[str] = []  # Para LRU

    async def get(self, key: str) -> bytes | None:
        if key in self._cache:
            value, expiry = self._cache[key]
            if time.time() < expiry:
                # Actualizar orden de acceso (LRU)
                if key in self._access_order:
                    self._access_order.remove(key)
                self._access_order.append(key)
                return value
            else:
                # Expirado
                del self._cache[key]
                if key in self._access_order:
                    self._access_order.remove(key)
        return None

    async def set(self, key: str, value: bytes, ex: int = 3600) -> bool:
        # Evict si llegamos al límite
        while len(self._cache) >= self._max_items and self._access_order:
            oldest = self._access_order.pop(0)
            if oldest in self._cache:
                del self._cache[oldest]

        expiry = time.time() + ex
        self._cache[key] = (value, expiry)
        self._access_order.append(key)
        return True

    async def delete(self, key: str) -> bool:
        if key in self._cache:
            del self._cache[key]
            if key in self._access_order:
                self._access_order.remove(key)
            return True
        return False

    async def exists(self, key: str) -> bool:
        if key in self._cache:
            _, expiry = self._cache[key]
            return time.time() < expiry
        return False

    async def keys(self, pattern: str) -> list[str]:
        """Búsqueda simple por prefijo (no soporta wildcards completos)"""
        prefix = pattern.rstrip("*")
        return [k for k in self._cache if k.startswith(prefix)]

    async def flushdb(self) -> bool:
        self._cache.clear()
        self._access_order.clear()
        return True


class CacheService:
    """
    Servicio de cache unificado para QPrisma.

    Características:
    - Conexión async a Redis con fallback a memoria
    - Múltiples estrategias de caching por tipo de dato
    - Perceptual hashing para deduplicación de frames
    - Métricas de rendimiento
    - Serialización automática JSON
    """

    def __init__(self, redis_url: str | None = None, config: CacheConfig | None = None):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.config = config or CacheConfig()
        self.metrics = CacheMetrics()

        self._redis: aioredis.Redis | None = None
        self._memory_cache: InMemoryCache | None = None
        self._connected = False
        self._use_memory_fallback = False

    async def connect(self) -> bool:
        """
        Conecta a Redis. Si falla, usa cache en memoria.
        Retorna True si conectó a Redis, False si usa memoria.
        """
        if REDIS_AVAILABLE:
            try:
                self._redis = aioredis.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=False,  # Queremos bytes para embeddings
                )
                # Test connection
                await self._redis.ping()
                self._connected = True
                self._use_memory_fallback = False
                logger.info(f"Connected to Redis at {self.redis_url}")
                return True
            except Exception as e:
                logger.warning(f"Redis connection failed: {e}. Using in-memory cache.")
                self._use_memory_fallback = True
        else:
            logger.warning("Redis library not installed. Using in-memory cache.")
            self._use_memory_fallback = True

        # Fallback a memoria
        self._memory_cache = InMemoryCache(max_items=self.config.max_memory_items)
        self._connected = True
        return False

    async def disconnect(self):
        """Cierra la conexión a Redis"""
        if self._redis:
            await self._redis.aclose()
            self._redis = None
        self._connected = False

    @property
    def client(self) -> aioredis.Redis | InMemoryCache:
        """Retorna el cliente activo (Redis o memoria)"""
        if self._use_memory_fallback:
            return self._memory_cache
        return self._redis

    def _make_key(self, cache_type: CacheType, identifier: str) -> str:
        """Genera key con prefijo y tipo"""
        return f"{self.config.key_prefix}:{cache_type.value}:{identifier}"

    def _get_ttl(self, cache_type: CacheType) -> int:
        """Obtiene TTL para un tipo de cache"""
        return self.config.ttl_seconds.get(cache_type, 3600)

    # =========================================================================
    # Métodos de bajo nivel
    # =========================================================================

    async def _get_raw(self, key: str) -> bytes | None:
        """GET raw de Redis/memoria"""
        if not self._connected:
            await self.connect()

        try:
            result = await self.client.get(key)
            if result:
                self.metrics.hits += 1
            else:
                self.metrics.misses += 1
            return result
        except Exception as e:
            logger.error(f"Cache GET error: {e}")
            self.metrics.errors += 1
            return None

    async def _set_raw(self, key: str, value: bytes, ttl: int) -> bool:
        """SET raw a Redis/memoria"""
        if not self._connected:
            await self.connect()

        try:
            await self.client.set(key, value, ex=ttl)
            return True
        except Exception as e:
            logger.error(f"Cache SET error: {e}")
            self.metrics.errors += 1
            return False

    async def _delete(self, key: str) -> bool:
        """DELETE de Redis/memoria"""
        if not self._connected:
            await self.connect()

        try:
            await self.client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Cache DELETE error: {e}")
            return False

    # =========================================================================
    # Cache de Embeddings
    # =========================================================================

    @staticmethod
    def hash_content(content: str) -> str:
        """Genera hash SHA256 de contenido para usar como key"""
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    async def get_embedding(self, content_hash: str) -> list[float] | None:
        """
        Recupera embedding cacheado por hash de contenido.

        Args:
            content_hash: Hash del contenido original (texto o imagen base64)

        Returns:
            Lista de floats del embedding o None si no está en cache
        """
        key = self._make_key(CacheType.EMBEDDING, content_hash)
        data = await self._get_raw(key)

        if data:
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                logger.error(f"Invalid embedding JSON in cache: {key}")
                return None
        return None

    async def set_embedding(
        self, content_hash: str, embedding: list[float], ttl: int | None = None
    ) -> bool:
        """
        Guarda embedding en cache.

        Args:
            content_hash: Hash del contenido
            embedding: Vector de embedding
            ttl: TTL en segundos (usa default si None)
        """
        key = self._make_key(CacheType.EMBEDDING, content_hash)
        ttl = ttl or self._get_ttl(CacheType.EMBEDDING)

        try:
            data = json.dumps(embedding).encode()
            return await self._set_raw(key, data, ttl)
        except Exception as e:
            logger.error(f"Failed to cache embedding: {e}")
            return False

    async def get_or_compute_embedding(
        self, content: str, compute_fn: Callable[[], list[float]]
    ) -> list[float]:
        """
        Pattern Cache-Aside para embeddings.

        Args:
            content: Contenido a embedir
            compute_fn: Función que genera el embedding si no está en cache

        Returns:
            Embedding (de cache o computado)
        """
        content_hash = self.hash_content(content)

        # Intentar cache
        cached = await self.get_embedding(content_hash)
        if cached:
            self.metrics.api_calls_saved += 1
            self.metrics.bytes_saved += len(content.encode())
            return cached

        # Computar y cachear
        embedding = compute_fn()
        await self.set_embedding(content_hash, embedding)
        return embedding

    # =========================================================================
    # Cache de Análisis de Frames (GPT-4V)
    # =========================================================================

    async def get_frame_analysis(self, frame_hash: str) -> dict[str, Any] | None:
        """Recupera análisis de frame cacheado"""
        key = self._make_key(CacheType.FRAME_ANALYSIS, frame_hash)
        data = await self._get_raw(key)

        if data:
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return None
        return None

    async def set_frame_analysis(
        self, frame_hash: str, analysis: dict[str, Any], ttl: int | None = None
    ) -> bool:
        """Guarda análisis de frame en cache"""
        key = self._make_key(CacheType.FRAME_ANALYSIS, frame_hash)
        ttl = ttl or self._get_ttl(CacheType.FRAME_ANALYSIS)

        try:
            data = json.dumps(analysis).encode()
            return await self._set_raw(key, data, ttl)
        except Exception as e:
            logger.error(f"Failed to cache frame analysis: {e}")
            return False

    # =========================================================================
    # Perceptual Hashing para Frames Similares
    # =========================================================================

    @staticmethod
    def compute_perceptual_hash(image_bytes: bytes) -> str | None:
        """
        Calcula hash perceptual de una imagen.
        Frames visualmente similares tendrán hashes similares.

        Usa pHash (perceptual hash) que es robusto a:
        - Cambios de tamaño
        - Compresión
        - Pequeños cambios de color/brillo
        """
        if not IMAGEHASH_AVAILABLE:
            # Fallback a hash de bytes
            return hashlib.md5(image_bytes).hexdigest()

        try:
            image = Image.open(io.BytesIO(image_bytes))
            # pHash es más robusto que aHash o dHash
            phash = imagehash.phash(image)
            return str(phash)
        except Exception as e:
            logger.error(f"Failed to compute perceptual hash: {e}")
            return None

    @staticmethod
    def hash_distance(hash1: str, hash2: str) -> int:
        """
        Calcula distancia Hamming entre dos hashes perceptuales.
        Menor distancia = más similares (0 = idénticos, 64 = completamente diferentes)
        """
        if not IMAGEHASH_AVAILABLE:
            return 64 if hash1 != hash2 else 0

        try:
            h1 = imagehash.hex_to_hash(hash1)
            h2 = imagehash.hex_to_hash(hash2)
            return h1 - h2
        except:
            return 64

    async def find_similar_frame(self, phash: str) -> str | None:
        """
        Busca un frame similar en cache por hash perceptual.

        Returns:
            Hash del contenido del frame similar, o None si no hay match
        """
        key_pattern = self._make_key(CacheType.FRAME_HASH, "*")

        if not self._connected:
            await self.connect()

        try:
            # Obtener todas las keys de frame hashes
            if self._use_memory_fallback:
                keys = await self._memory_cache.keys(key_pattern)
            else:
                keys = []
                async for key in self._redis.scan_iter(match=key_pattern):
                    keys.append(key.decode() if isinstance(key, bytes) else key)

            # Buscar hash similar
            for key in keys:
                stored_phash = key.split(":")[-1]
                distance = self.hash_distance(phash, stored_phash)

                if distance <= self.config.similarity_threshold:
                    # Encontramos frame similar
                    data = await self._get_raw(key)
                    if data:
                        return data.decode()

            return None
        except Exception as e:
            logger.error(f"Error finding similar frame: {e}")
            return None

    async def register_frame_hash(self, phash: str, content_hash: str) -> bool:
        """
        Registra mapping de hash perceptual -> hash de contenido.
        Permite encontrar frames similares rápidamente.
        """
        key = self._make_key(CacheType.FRAME_HASH, phash)
        ttl = self._get_ttl(CacheType.FRAME_HASH)
        return await self._set_raw(key, content_hash.encode(), ttl)

    async def get_or_compute_frame_analysis(
        self,
        frame_bytes: bytes,
        compute_fn: Callable[[], dict[str, Any]],
        use_similarity: bool = True,
    ) -> dict[str, Any]:
        """
        Pattern completo para análisis de frames con deduplicación.

        1. Calcula hash perceptual del frame
        2. Busca frame similar en cache
        3. Si encuentra, retorna análisis cacheado
        4. Si no, computa análisis, cachea, y registra hash

        Args:
            frame_bytes: Bytes de la imagen
            compute_fn: Función que analiza el frame con GPT-4V
            use_similarity: Si usar deduplicación por similitud

        Returns:
            Análisis del frame (cacheado o nuevo)
        """
        # Hash perceptual para similitud
        phash = self.compute_perceptual_hash(frame_bytes)

        # Hash de contenido exacto
        content_hash = hashlib.sha256(frame_bytes).hexdigest()[:32]

        # 1. Buscar análisis exacto
        cached = await self.get_frame_analysis(content_hash)
        if cached:
            self.metrics.api_calls_saved += 1
            logger.debug(f"Frame analysis cache HIT (exact): {content_hash[:8]}")
            return cached

        # 2. Buscar frame similar (si está habilitado)
        if use_similarity and phash:
            similar_hash = await self.find_similar_frame(phash)
            if similar_hash:
                cached = await self.get_frame_analysis(similar_hash)
                if cached:
                    self.metrics.api_calls_saved += 1
                    logger.debug(
                        f"Frame analysis cache HIT (similar): {phash[:8]} -> {similar_hash[:8]}"
                    )
                    # Cachear también con hash exacto para futuras búsquedas
                    await self.set_frame_analysis(content_hash, cached)
                    return cached

        # 3. Computar análisis
        logger.debug(f"Frame analysis cache MISS: {content_hash[:8]}")
        analysis = compute_fn()

        # 4. Cachear resultado
        await self.set_frame_analysis(content_hash, analysis)

        # 5. Registrar hash perceptual
        if phash:
            await self.register_frame_hash(phash, content_hash)

        return analysis

    # =========================================================================
    # Cache de Estado de Jobs
    # =========================================================================

    async def get_job_status(self, job_id: str) -> dict[str, Any] | None:
        """Recupera estado de job de procesamiento"""
        key = self._make_key(CacheType.JOB_STATUS, job_id)
        data = await self._get_raw(key)

        if data:
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return None
        return None

    async def set_job_status(
        self, job_id: str, status: dict[str, Any], ttl: int | None = None
    ) -> bool:
        """
        Guarda estado de job en cache.
        Ideal para WebSocket updates y polling eficiente.
        """
        key = self._make_key(CacheType.JOB_STATUS, job_id)
        ttl = ttl or self._get_ttl(CacheType.JOB_STATUS)

        try:
            data = json.dumps(status).encode()
            return await self._set_raw(key, data, ttl)
        except Exception as e:
            logger.error(f"Failed to cache job status: {e}")
            return False

    async def update_job_progress(
        self, job_id: str, progress: int, stage: str, message: str | None = None
    ) -> bool:
        """Actualiza progreso de job (convenience method)"""
        status = await self.get_job_status(job_id) or {}
        status.update(
            {
                "progress": progress,
                "stage": stage,
                "message": message,
                "updated_at": datetime.utcnow().isoformat(),
            }
        )
        return await self.set_job_status(job_id, status)

    # =========================================================================
    # Cache de Resultados de Búsqueda
    # =========================================================================

    async def get_search_result(self, query_hash: str) -> dict[str, Any] | None:
        """Recupera resultado de búsqueda cacheado"""
        key = self._make_key(CacheType.SEARCH_RESULT, query_hash)
        data = await self._get_raw(key)

        if data:
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return None
        return None

    async def set_search_result(
        self, query_hash: str, result: dict[str, Any], ttl: int | None = None
    ) -> bool:
        """Guarda resultado de búsqueda en cache"""
        key = self._make_key(CacheType.SEARCH_RESULT, query_hash)
        ttl = ttl or self._get_ttl(CacheType.SEARCH_RESULT)

        try:
            data = json.dumps(result).encode()
            return await self._set_raw(key, data, ttl)
        except Exception as e:
            logger.error(f"Failed to cache search result: {e}")
            return False

    # =========================================================================
    # Utilidades
    # =========================================================================

    async def invalidate_by_pattern(self, pattern: str) -> int:
        """
        Invalida (elimina) todas las keys que coinciden con un patrón.
        Útil para invalidar cache cuando se actualiza un video.

        Returns:
            Número de keys eliminadas
        """
        if not self._connected:
            await self.connect()

        count = 0
        try:
            if self._use_memory_fallback:
                keys = await self._memory_cache.keys(pattern)
                for key in keys:
                    await self._memory_cache.delete(key)
                    count += 1
            else:
                async for key in self._redis.scan_iter(match=pattern):
                    await self._redis.delete(key)
                    count += 1
        except Exception as e:
            logger.error(f"Error invalidating cache: {e}")

        return count

    async def invalidate_video(self, video_id: str) -> int:
        """Invalida todo el cache relacionado con un video"""
        pattern = f"{self.config.key_prefix}:*:{video_id}*"
        return await self.invalidate_by_pattern(pattern)

    async def clear_all(self) -> bool:
        """Limpia todo el cache (usar con precaución)"""
        if not self._connected:
            await self.connect()

        try:
            if self._use_memory_fallback:
                await self._memory_cache.flushdb()
            else:
                # Solo limpia keys con nuestro prefijo
                pattern = f"{self.config.key_prefix}:*"
                async for key in self._redis.scan_iter(match=pattern):
                    await self._redis.delete(key)
            return True
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")
            return False

    def get_metrics(self) -> dict[str, Any]:
        """Retorna métricas de rendimiento del cache"""
        return {
            "connected": self._connected,
            "backend": "memory" if self._use_memory_fallback else "redis",
            **self.metrics.to_dict(),
        }

    def reset_metrics(self):
        """Resetea contadores de métricas"""
        self.metrics = CacheMetrics()


# =============================================================================
# Singleton global (opcional, para uso simple)
# =============================================================================

_cache_instance: CacheService | None = None


async def get_cache_service() -> CacheService:
    """Obtiene instancia singleton del CacheService"""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = CacheService()
        await _cache_instance.connect()
    return _cache_instance


# =============================================================================
# Decorador para caching automático
# =============================================================================


def cached(cache_type: CacheType, ttl: int | None = None, key_fn: Callable[..., str] | None = None):
    """
    Decorador para cachear resultados de funciones async.

    Uso:
        @cached(CacheType.EMBEDDING)
        async def get_embedding(text: str) -> List[float]:
            ...
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            cache = await get_cache_service()

            # Generar key
            if key_fn:
                cache_key = key_fn(*args, **kwargs)
            else:
                # Key por defecto: hash de argumentos
                key_parts = (
                    [func.__name__]
                    + [str(a) for a in args]
                    + [f"{k}={v}" for k, v in kwargs.items()]
                )
                cache_key = CacheService.hash_content(":".join(key_parts))

            full_key = cache._make_key(cache_type, cache_key)

            # Intentar cache
            data = await cache._get_raw(full_key)
            if data:
                try:
                    return json.loads(data)
                except:
                    pass

            # Ejecutar función
            result = await func(*args, **kwargs)

            # Cachear resultado
            try:
                data = json.dumps(result).encode()
                await cache._set_raw(full_key, data, ttl or cache._get_ttl(cache_type))
            except:
                pass

            return result

        return wrapper

    return decorator
