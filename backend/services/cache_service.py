"""
Local Cache Service for QPrisma.
Implements best-effort in-process caching for graph/search hot paths.

Implemented strategies:
1. Cache-Aside Pattern: Read cache first, if miss -> compute and save
2. Intelligent TTL: Different TTLs depending on content type
3. In-process TTL storage: Cache is per API replica and not durable
"""

import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from fnmatch import fnmatch
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CacheType(str, Enum):
    """Cache types with different TTLs and strategies"""

    SEARCH_RESULT = "search_result"  # Search results
    GRAPH_QUERY = "graph_query"  # Graph query results (video data, stats)


@dataclass
class CacheConfig:
    """TTL configuration per cache type"""

    ttl_seconds: dict[CacheType, int] = field(
        default_factory=lambda: {
            CacheType.SEARCH_RESULT: 300,  # 5 min - results change with indexing
            CacheType.GRAPH_QUERY: 600,  # 10 min - graph reads
        }
    )

    # Maximum in-memory cache size (fallback)
    max_memory_items: int = 1000

    # Prefix for all cache keys
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
    In-memory cache with simple LRU and TTL.
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
        """Return keys matching a shell-style wildcard pattern."""
        return [k for k in self._cache if fnmatch(k, pattern)]

    async def flushdb(self) -> bool:
        self._cache.clear()
        self._access_order.clear()
        return True


class CacheService:
    """
    Local cache service for QPrisma.

    Features:
    - In-process memory cache
    - Graph/search result caching
    - Performance metrics
    - Automatic JSON serialization
    """

    def __init__(self, config: CacheConfig | None = None):
        self.config = config or CacheConfig()
        self.metrics = CacheMetrics()

        self._memory_cache = InMemoryCache(max_items=self.config.max_memory_items)
        self._connected = False

    async def connect(self) -> bool:
        """
        Initialize the local cache.
        Returns True when the in-process cache is ready.
        """
        self._connected = True
        logger.info("Initialized in-process cache")
        return True

    async def disconnect(self):
        """Mark the local cache as disconnected."""
        self._connected = False

    @property
    def client(self) -> InMemoryCache:
        """Return the active in-process cache client."""
        return self._memory_cache

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
        """Raw GET from memory."""
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
        """Raw SET to memory."""
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
        """DELETE from memory."""
        if not self._connected:
            await self.connect()

        try:
            await self.client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Cache DELETE error: {e}")
            return False

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
    # Graph Query Cache
    # =========================================================================

    async def get_graph_query(self, query_hash: str) -> dict[str, Any] | None:
        """Retrieve cached graph query result."""
        key = self._make_key(CacheType.GRAPH_QUERY, query_hash)
        data = await self._get_raw(key)
        if data:
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return None
        return None

    async def set_graph_query(
        self, query_hash: str, result: dict[str, Any], ttl: int | None = None
    ) -> bool:
        """Save graph query result to cache."""
        key = self._make_key(CacheType.GRAPH_QUERY, query_hash)
        ttl = ttl or self._get_ttl(CacheType.GRAPH_QUERY)
        try:
            data = json.dumps(result).encode()
            return await self._set_raw(key, data, ttl)
        except Exception as e:
            logger.error(f"Failed to cache graph query: {e}")
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
            keys = await self._memory_cache.keys(pattern)
            for key in keys:
                await self._memory_cache.delete(key)
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
            await self._memory_cache.flushdb()
            return True
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")
            return False

    def get_metrics(self) -> dict[str, Any]:
        """Return cache performance metrics"""
        return {
            "connected": self._connected,
            "backend": "memory",
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
