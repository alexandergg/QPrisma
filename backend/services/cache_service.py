"""
Cache Service for QPrisma
Implements caching strategies to reduce Azure OpenAI costs and improve latency.

Implemented strategies:
1. Cache-Aside Pattern: Read cache first, if miss -> compute and save
2. Perceptual Hashing: Reuse embeddings for visually similar frames
3. Intelligent TTL: Different TTLs depending on content type
4. Memory Fallback: If Redis is unavailable, use local cache

Usage:
    cache = CacheService()

    # Embedding cache
    embedding = await cache.get_embedding(content_hash)
    if not embedding:
        embedding = compute_embedding(...)
        await cache.set_embedding(content_hash, embedding)

    # Analysis cache with similar-frame deduplication
    analysis = await cache.get_or_compute_frame_analysis(
        frame_bytes,
        compute_fn=lambda: analyze_with_gpt4v(frame)
    )
"""

import hashlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
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

# Perceptual hashing for images
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
    """Cache types with different TTLs and strategies"""

    EMBEDDING = "embedding"  # Text/image embeddings
    FRAME_ANALYSIS = "frame_analysis"  # GPT-4V frame analysis
    FRAME_HASH = "frame_hash"  # Perceptual hash -> embedding key
    VIDEO_METADATA = "video_metadata"  # Video metadata
    SEARCH_RESULT = "search_result"  # Search results
    JOB_STATUS = "job_status"  # Processing job status


@dataclass
class CacheConfig:
    """TTL configuration per cache type"""

    ttl_seconds: dict[CacheType, int] = field(
        default_factory=lambda: {
            CacheType.EMBEDDING: 86400 * 7,  # 7 days - embeddings are stable
            CacheType.FRAME_ANALYSIS: 86400 * 3,  # 3 days - analysis may change with prompts
            CacheType.FRAME_HASH: 86400 * 7,  # 7 days - hash mappings
            CacheType.VIDEO_METADATA: 3600,  # 1 hour - metadata may be updated
            CacheType.SEARCH_RESULT: 300,  # 5 min - results change with indexing
            CacheType.JOB_STATUS: 3600,  # 1 hour - job states
        }
    )

    # Similarity threshold for perceptual hashing (0-64, lower = more similar)
    similarity_threshold: int = 8

    # Maximum in-memory cache size (fallback)
    max_memory_items: int = 1000

    # Prefix for all Redis keys
    key_prefix: str = "qprisma"


@dataclass
class CacheMetrics:
    """Cache performance metrics"""

    hits: int = 0
    misses: int = 0
    errors: int = 0
    bytes_saved: int = 0  # Estimate of data not transferred
    api_calls_saved: int = 0  # Azure OpenAI calls avoided

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
            "estimated_cost_saved": f"${self.api_calls_saved * 0.01:.2f}",  # ~$0.01 per call
        }


class InMemoryCache:
    """
    In-memory cache as fallback when Redis is unavailable.
    Implements simple LRU with TTL.
    """

    def __init__(self, max_items: int = 1000):
        self._cache: dict[str, tuple[Any, float]] = {}  # key -> (value, expiry_timestamp)
        self._max_items = max_items
        self._access_order: list[str] = []  # For LRU

    async def get(self, key: str) -> bytes | None:
        if key in self._cache:
            value, expiry = self._cache[key]
            if time.time() < expiry:
                # Update access order (LRU)
                if key in self._access_order:
                    self._access_order.remove(key)
                self._access_order.append(key)
                return value
            else:
                # Expired
                del self._cache[key]
                if key in self._access_order:
                    self._access_order.remove(key)
        return None

    async def set(self, key: str, value: bytes, ex: int = 3600) -> bool:
        # Evict if we hit the limit
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
        """Simple prefix search (does not support full wildcards)"""
        prefix = pattern.rstrip("*")
        return [k for k in self._cache if k.startswith(prefix)]

    async def flushdb(self) -> bool:
        self._cache.clear()
        self._access_order.clear()
        return True


class CacheService:
    """
    Unified cache service for QPrisma.

    Features:
    - Async Redis connection with memory fallback
    - Multiple caching strategies per data type
    - Perceptual hashing for frame deduplication
    - Performance metrics
    - Automatic JSON serialization
    """

    def __init__(self, redis_url: str | None = None, config: CacheConfig | None = None):
        from core.config import settings

        self.redis_url = redis_url or settings.redis.url
        self.config = config or CacheConfig()
        self.metrics = CacheMetrics()

        self._redis: aioredis.Redis | None = None
        self._memory_cache: InMemoryCache | None = None
        self._connected = False
        self._use_memory_fallback = False

    async def connect(self) -> bool:
        """
        Connect to Redis. If it fails, use in-memory cache.
        Returns True if connected to Redis, False if using memory.
        """
        if REDIS_AVAILABLE:
            try:
                self._redis = aioredis.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=False,  # We want bytes for embeddings
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

        # Fallback to memory
        self._memory_cache = InMemoryCache(max_items=self.config.max_memory_items)
        self._connected = True
        return False

    async def disconnect(self):
        """Close the Redis connection"""
        if self._redis:
            await self._redis.aclose()
            self._redis = None
        self._connected = False

    @property
    def client(self) -> aioredis.Redis | InMemoryCache:
        """Return the active client (Redis or memory)"""
        if self._use_memory_fallback:
            return self._memory_cache
        return self._redis

    def _make_key(self, cache_type: CacheType, identifier: str) -> str:
        """Generate key with prefix and type"""
        return f"{self.config.key_prefix}:{cache_type.value}:{identifier}"

    def _get_ttl(self, cache_type: CacheType) -> int:
        """Get TTL for a cache type"""
        return self.config.ttl_seconds.get(cache_type, 3600)

    # =========================================================================
    # Low-level Methods
    # =========================================================================

    async def _get_raw(self, key: str) -> bytes | None:
        """Raw GET from Redis/memory"""
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
        """Raw SET to Redis/memory"""
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
        """DELETE from Redis/memory"""
        if not self._connected:
            await self.connect()

        try:
            await self.client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Cache DELETE error: {e}")
            return False

    # =========================================================================
    # Embedding Cache
    # =========================================================================

    @staticmethod
    def hash_content(content: str) -> str:
        """Generate SHA256 hash of content to use as key"""
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    async def get_embedding(self, content_hash: str) -> list[float] | None:
        """
        Retrieve cached embedding by content hash.

        Args:
            content_hash: Hash of the original content (text or base64 image)

        Returns:
            List of floats for the embedding, or None if not in cache
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
        Save embedding to cache.

        Args:
            content_hash: Hash of the content
            embedding: Embedding vector
            ttl: TTL in seconds (uses default if None)
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
        Cache-Aside pattern for embeddings.

        Args:
            content: Content to embed
            compute_fn: Function that generates the embedding if not in cache

        Returns:
            Embedding (from cache or computed)
        """
        content_hash = self.hash_content(content)

        # Try cache
        cached = await self.get_embedding(content_hash)
        if cached:
            self.metrics.api_calls_saved += 1
            self.metrics.bytes_saved += len(content.encode())
            return cached

        # Compute and cache
        embedding = compute_fn()
        await self.set_embedding(content_hash, embedding)
        return embedding

    # =========================================================================
    # Frame Analysis Cache (GPT-4V)
    # =========================================================================

    async def get_frame_analysis(self, frame_hash: str) -> dict[str, Any] | None:
        """Retrieve cached frame analysis"""
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
        """Save frame analysis to cache"""
        key = self._make_key(CacheType.FRAME_ANALYSIS, frame_hash)
        ttl = ttl or self._get_ttl(CacheType.FRAME_ANALYSIS)

        try:
            data = json.dumps(analysis).encode()
            return await self._set_raw(key, data, ttl)
        except Exception as e:
            logger.error(f"Failed to cache frame analysis: {e}")
            return False

    # =========================================================================
    # Perceptual Hashing for Similar Frames
    # =========================================================================

    @staticmethod
    def compute_perceptual_hash(image_bytes: bytes) -> str | None:
        """
        Compute perceptual hash of an image.
        Visually similar frames will have similar hashes.

        Uses pHash (perceptual hash) which is robust to:
        - Resizing
        - Compression
        - Minor color/brightness changes
        """
        if not IMAGEHASH_AVAILABLE:
            # Fallback to byte hash
            return hashlib.md5(image_bytes).hexdigest()

        try:
            image = Image.open(io.BytesIO(image_bytes))
            # pHash is more robust than aHash or dHash
            phash = imagehash.phash(image)
            return str(phash)
        except Exception as e:
            logger.error(f"Failed to compute perceptual hash: {e}")
            return None

    @staticmethod
    def hash_distance(hash1: str, hash2: str) -> int:
        """
        Compute Hamming distance between two perceptual hashes.
        Lower distance = more similar (0 = identical, 64 = completely different)
        """
        if not IMAGEHASH_AVAILABLE:
            return 64 if hash1 != hash2 else 0

        try:
            h1 = imagehash.hex_to_hash(hash1)
            h2 = imagehash.hex_to_hash(hash2)
            return h1 - h2
        except (ValueError, TypeError):
            return 64

    async def find_similar_frame(self, phash: str) -> str | None:
        """
        Search for a similar frame in cache by perceptual hash.

        Returns:
            Content hash of the similar frame, or None if no match
        """
        key_pattern = self._make_key(CacheType.FRAME_HASH, "*")

        if not self._connected:
            await self.connect()

        try:
            # Get all frame hash keys
            if self._use_memory_fallback:
                keys = await self._memory_cache.keys(key_pattern)
            else:
                keys = []
                async for key in self._redis.scan_iter(match=key_pattern):
                    keys.append(key.decode() if isinstance(key, bytes) else key)

            # Search for similar hash
            for key in keys:
                stored_phash = key.split(":")[-1]
                distance = self.hash_distance(phash, stored_phash)

                if distance <= self.config.similarity_threshold:
                    # Found a similar frame
                    data = await self._get_raw(key)
                    if data:
                        return data.decode()

            return None
        except Exception as e:
            logger.error(f"Error finding similar frame: {e}")
            return None

    async def register_frame_hash(self, phash: str, content_hash: str) -> bool:
        """
        Register mapping of perceptual hash -> content hash.
        Allows quickly finding similar frames.
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
        Complete pattern for frame analysis with deduplication.

        1. Compute perceptual hash of the frame
        2. Search for a similar frame in cache
        3. If found, return cached analysis
        4. If not, compute analysis, cache it, and register hash

        Args:
            frame_bytes: Image bytes
            compute_fn: Function that analyzes the frame with GPT-4V
            use_similarity: Whether to use similarity-based deduplication

        Returns:
            Frame analysis (cached or new)
        """
        # Perceptual hash for similarity
        phash = self.compute_perceptual_hash(frame_bytes)

        # Exact content hash
        content_hash = hashlib.sha256(frame_bytes).hexdigest()[:32]

        # 1. Search for exact analysis
        cached = await self.get_frame_analysis(content_hash)
        if cached:
            self.metrics.api_calls_saved += 1
            logger.debug(f"Frame analysis cache HIT (exact): {content_hash[:8]}")
            return cached

        # 2. Search for similar frame (if enabled)
        if use_similarity and phash:
            similar_hash = await self.find_similar_frame(phash)
            if similar_hash:
                cached = await self.get_frame_analysis(similar_hash)
                if cached:
                    self.metrics.api_calls_saved += 1
                    logger.debug(
                        f"Frame analysis cache HIT (similar): {phash[:8]} -> {similar_hash[:8]}"
                    )
                    # Also cache with exact hash for future lookups
                    await self.set_frame_analysis(content_hash, cached)
                    return cached

        # 3. Compute analysis
        logger.debug(f"Frame analysis cache MISS: {content_hash[:8]}")
        analysis = compute_fn()

        # 4. Cache result
        await self.set_frame_analysis(content_hash, analysis)

        # 5. Register perceptual hash
        if phash:
            await self.register_frame_hash(phash, content_hash)

        return analysis

    # =========================================================================
    # Job Status Cache
    # =========================================================================

    async def get_job_status(self, job_id: str) -> dict[str, Any] | None:
        """Retrieve processing job status"""
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
        Save job status to cache.
        Ideal for WebSocket updates and efficient polling.
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
        """Update job progress (convenience method)"""
        status = await self.get_job_status(job_id) or {}
        status.update(
            {
                "progress": progress,
                "stage": stage,
                "message": message,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
        return await self.set_job_status(job_id, status)

    # =========================================================================
    # Search Result Cache
    # =========================================================================

    async def get_search_result(self, query_hash: str) -> dict[str, Any] | None:
        """Retrieve cached search result"""
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
        """Save search result to cache"""
        key = self._make_key(CacheType.SEARCH_RESULT, query_hash)
        ttl = ttl or self._get_ttl(CacheType.SEARCH_RESULT)

        try:
            data = json.dumps(result).encode()
            return await self._set_raw(key, data, ttl)
        except Exception as e:
            logger.error(f"Failed to cache search result: {e}")
            return False

    # =========================================================================
    # Utilities
    # =========================================================================

    async def invalidate_by_pattern(self, pattern: str) -> int:
        """
        Invalidate (delete) all keys matching a pattern.
        Useful for invalidating cache when a video is updated.

        Returns:
            Number of keys deleted
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
        """Invalidate all cache related to a video"""
        pattern = f"{self.config.key_prefix}:*:{video_id}*"
        return await self.invalidate_by_pattern(pattern)

    async def clear_all(self) -> bool:
        """Clear all cache (use with caution)"""
        if not self._connected:
            await self.connect()

        try:
            if self._use_memory_fallback:
                await self._memory_cache.flushdb()
            else:
                # Only clear keys with our prefix
                pattern = f"{self.config.key_prefix}:*"
                async for key in self._redis.scan_iter(match=pattern):
                    await self._redis.delete(key)
            return True
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")
            return False

    def get_metrics(self) -> dict[str, Any]:
        """Return cache performance metrics"""
        return {
            "connected": self._connected,
            "backend": "memory" if self._use_memory_fallback else "redis",
            **self.metrics.to_dict(),
        }

    def reset_metrics(self):
        """Reset metric counters"""
        self.metrics = CacheMetrics()


# =============================================================================
# Global singleton (optional, for simple usage)
# =============================================================================

_cache_instance: CacheService | None = None


async def get_cache_service() -> CacheService:
    """Get the singleton instance of CacheService"""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = CacheService()
        await _cache_instance.connect()
    return _cache_instance


# =============================================================================
# Decorator for automatic caching
# =============================================================================


def cached(cache_type: CacheType, ttl: int | None = None, key_fn: Callable[..., str] | None = None):
    """
    Decorator for caching results of async functions.

    Usage:
        @cached(CacheType.EMBEDDING)
        async def get_embedding(text: str) -> List[float]:
            ...
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            cache = await get_cache_service()

            # Generate key
            if key_fn:
                cache_key = key_fn(*args, **kwargs)
            else:
                # Default key: hash of arguments
                key_parts = (
                    [func.__name__]
                    + [str(a) for a in args]
                    + [f"{k}={v}" for k, v in kwargs.items()]
                )
                cache_key = CacheService.hash_content(":".join(key_parts))

            full_key = cache._make_key(cache_type, cache_key)

            # Try cache
            data = await cache._get_raw(full_key)
            if data:
                try:
                    return json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    pass

            # Execute function
            result = await func(*args, **kwargs)

            # Cache result
            try:
                data = json.dumps(result).encode()
                await cache._set_raw(full_key, data, ttl or cache._get_ttl(cache_type))
            except (TypeError, ConnectionError) as e:
                logger.debug(f"Cache write failed for {full_key}: {e}")

            return result

        return wrapper

    return decorator
