import pytest


class TestCacheService:
    """Tests para CacheService"""

    @pytest.fixture
    async def cache_service(self):
        """Fixture que crea un CacheService para tests"""
        from services.cache_service import CacheConfig, CacheService

        config = CacheConfig(key_prefix="test_qprisma", max_memory_items=100)

        cache = CacheService(config=config)
        await cache.connect()

        yield cache

        # Limpiar después del test
        await cache.clear_all()
        await cache.disconnect()

    @pytest.mark.asyncio
    async def test_connection(self, cache_service):
        """Test de conexión al cache"""
        metrics = cache_service.get_metrics()
        assert metrics["connected"] is True
        assert metrics["backend"] == "memory"

    @pytest.mark.asyncio
    async def test_search_result_cache(self, cache_service):
        """Test de cache de resultados de busqueda"""
        query_hash = "query_123"
        result = {"results": [{"id": "video-1"}], "total": 1}

        saved = await cache_service.set_search_result(query_hash, result)
        assert saved is True

        cached = await cache_service.get_search_result(query_hash)
        assert cached == result

        metrics = cache_service.get_metrics()
        assert metrics["hits"] >= 1

    @pytest.mark.asyncio
    async def test_graph_query_cache(self, cache_service):
        """Test de cache de consultas al grafo"""
        query_hash = "graph_123"
        result = {"nodes": [{"id": "n1"}], "relationships": []}

        saved = await cache_service.set_graph_query(query_hash, result)
        assert saved is True

        cached = await cache_service.get_graph_query(query_hash)
        assert cached == result

    @pytest.mark.asyncio
    async def test_invalidation(self, cache_service):
        """Test de invalidación de cache"""
        # Crear varias entradas
        await cache_service.set_search_result("video1_query1", {"results": []})
        await cache_service.set_search_result("video1_query2", {"results": []})
        await cache_service.set_search_result("video2_query1", {"results": []})

        # Invalidar por patrón
        pattern = f"{cache_service.config.key_prefix}:*video1*"
        deleted = await cache_service.invalidate_by_pattern(pattern)
        assert isinstance(deleted, int)

    @pytest.mark.asyncio
    async def test_metrics_tracking(self, cache_service):
        """Test de tracking de métricas"""
        cache_service.reset_metrics()

        # Generar algunos hits y misses
        await cache_service.get_search_result("nonexistent")  # Miss
        await cache_service.set_search_result("test", {"results": []})
        await cache_service.get_search_result("test")  # Hit

        metrics = cache_service.get_metrics()
        assert metrics["hits"] >= 1
        assert metrics["misses"] >= 1
        assert float(metrics["hit_rate"].rstrip("%")) > 0


class TestInMemoryCache:
    """Tests específicos para el cache en memoria (fallback)"""

    @pytest.mark.asyncio
    async def test_memory_fallback(self):
        """Test que el fallback a memoria funciona"""
        from services.cache_service import CacheConfig, CacheService

        config = CacheConfig(key_prefix="test_memory", max_memory_items=10)

        cache = CacheService(config=config)
        await cache.connect()

        assert cache.get_metrics()["backend"] == "memory"

        # Debe funcionar igual
        await cache.set_search_result("test", {"results": [1, 2]})
        result = await cache.get_search_result("test")
        assert result == {"results": [1, 2]}

        await cache.disconnect()

    @pytest.mark.asyncio
    async def test_lru_eviction(self):
        """Test de evicción LRU cuando se llena el cache"""
        from services.cache_service import InMemoryCache

        cache = InMemoryCache(max_items=3)

        # Llenar cache
        await cache.set("key1", b"value1", ex=3600)
        await cache.set("key2", b"value2", ex=3600)
        await cache.set("key3", b"value3", ex=3600)

        # Acceder a key1 para moverlo al final del LRU
        await cache.get("key1")

        # Añadir nueva key (debe evictar key2, el menos usado)
        await cache.set("key4", b"value4", ex=3600)

        # key2 debe haber sido evictado
        result = await cache.get("key2")
        assert result is None

        # key1 debe seguir existiendo
        result = await cache.get("key1")
        assert result == b"value1"
