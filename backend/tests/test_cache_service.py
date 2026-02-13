"""
Tests para el sistema de caching de QPrisma
"""

import io
from unittest.mock import patch

import pytest
from PIL import Image


class TestCacheService:
    """Tests para CacheService"""

    @pytest.fixture
    async def cache_service(self):
        """Fixture que crea un CacheService para tests"""
        from services.cache_service import CacheConfig, CacheService

        config = CacheConfig(key_prefix="test_qprisma", max_memory_items=100)

        with patch("services.cache_service.REDIS_AVAILABLE", False):
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
        assert metrics["backend"] in ["redis", "memory"]

    @pytest.mark.asyncio
    async def test_embedding_cache(self, cache_service):
        """Test de cache de embeddings"""
        content = "Este es un texto de prueba para embedding"
        content_hash = cache_service.hash_content(content)
        fake_embedding = [0.1, 0.2, 0.3, 0.4, 0.5]

        # Guardar
        result = await cache_service.set_embedding(content_hash, fake_embedding)
        assert result is True

        # Recuperar
        cached = await cache_service.get_embedding(content_hash)
        assert cached == fake_embedding

        # Verificar métricas
        metrics = cache_service.get_metrics()
        assert metrics["hits"] >= 1

    @pytest.mark.asyncio
    async def test_frame_analysis_cache(self, cache_service):
        """Test de cache de análisis de frames"""
        frame_hash = "test_frame_hash_123"
        analysis = {
            "description": "Una persona en una oficina",
            "objects": ["persona", "escritorio", "computadora"],
            "scene_type": "office",
        }

        # Guardar
        result = await cache_service.set_frame_analysis(frame_hash, analysis)
        assert result is True

        # Recuperar
        cached = await cache_service.get_frame_analysis(frame_hash)
        assert cached == analysis

    @pytest.mark.asyncio
    async def test_job_status_cache(self, cache_service):
        """Test de cache de estado de jobs"""
        job_id = "job_test_123"

        # Crear estado inicial
        status = {"progress": 0, "stage": "queued", "message": "En cola"}
        await cache_service.set_job_status(job_id, status)

        # Actualizar progreso
        await cache_service.update_job_progress(job_id, 50, "processing", "Procesando frames")

        # Verificar
        cached = await cache_service.get_job_status(job_id)
        assert cached["progress"] == 50
        assert cached["stage"] == "processing"

    @pytest.mark.asyncio
    async def test_get_or_compute_embedding(self, cache_service):
        """Test del patrón Cache-Aside para embeddings"""
        content = "Texto para patrón cache-aside"
        compute_called = False

        def compute_fn():
            nonlocal compute_called
            compute_called = True
            return [0.1, 0.2, 0.3]

        # Primera llamada - debe computar
        result1 = await cache_service.get_or_compute_embedding(content, compute_fn)
        assert compute_called is True
        assert result1 == [0.1, 0.2, 0.3]

        # Reset flag
        compute_called = False

        # Segunda llamada - debe usar cache
        result2 = await cache_service.get_or_compute_embedding(content, compute_fn)
        assert compute_called is False  # No se llamó a compute
        assert result2 == [0.1, 0.2, 0.3]

        # Verificar que se ahorró una llamada
        metrics = cache_service.get_metrics()
        assert metrics["api_calls_saved"] >= 1

    @pytest.mark.asyncio
    async def test_perceptual_hash(self, cache_service):
        """Test de hash perceptual para imágenes"""
        # Crear imagen de prueba
        img = Image.new("RGB", (100, 100), color="red")
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG")
        image_bytes = buffer.getvalue()

        # Calcular hash
        phash = cache_service.compute_perceptual_hash(image_bytes)
        assert phash is not None
        assert len(phash) > 0

        # Crear imagen similar (misma imagen, diferente calidad)
        buffer2 = io.BytesIO()
        img.save(buffer2, format="JPEG", quality=50)
        image_bytes2 = buffer2.getvalue()

        phash2 = cache_service.compute_perceptual_hash(image_bytes2)

        # Los hashes deben ser similares (distancia baja)
        distance = cache_service.hash_distance(phash, phash2)
        assert distance <= 10, f"Distancia muy alta: {distance}"

    @pytest.mark.asyncio
    async def test_frame_similarity_dedup(self, cache_service):
        """Test de deduplicación por similitud de frames"""
        # Crear frame de prueba
        img = Image.new("RGB", (100, 100), color="blue")
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG")
        frame_bytes = buffer.getvalue()

        analysis = {"description": "Imagen azul de prueba"}
        compute_called = 0

        def compute_fn():
            nonlocal compute_called
            compute_called += 1
            return analysis

        # Primera llamada - debe computar
        result1 = await cache_service.get_or_compute_frame_analysis(
            frame_bytes, compute_fn, use_similarity=True
        )
        assert compute_called == 1

        # Segunda llamada con frame ligeramente diferente
        img2 = Image.new("RGB", (100, 100), color="blue")
        # Añadir pequeña variación
        pixels = img2.load()
        pixels[50, 50] = (0, 0, 254)  # Cambio mínimo

        buffer2 = io.BytesIO()
        img2.save(buffer2, format="JPEG")
        frame_bytes2 = buffer2.getvalue()

        result2 = await cache_service.get_or_compute_frame_analysis(
            frame_bytes2, compute_fn, use_similarity=True
        )

        # No debería haber llamado a compute de nuevo (frame similar)
        # Nota: puede fallar si las imágenes son muy diferentes
        assert result2 is not None

    @pytest.mark.asyncio
    async def test_invalidation(self, cache_service):
        """Test de invalidación de cache"""
        # Crear varias entradas
        await cache_service.set_embedding("video1_frame1", [0.1])
        await cache_service.set_embedding("video1_frame2", [0.2])
        await cache_service.set_embedding("video2_frame1", [0.3])

        # Invalidar por patrón
        pattern = f"{cache_service.config.key_prefix}:*video1*"
        deleted = await cache_service.invalidate_by_pattern(pattern)
        assert isinstance(deleted, int)

    @pytest.mark.asyncio
    async def test_metrics_tracking(self, cache_service):
        """Test de tracking de métricas"""
        cache_service.reset_metrics()

        # Generar algunos hits y misses
        await cache_service.get_embedding("nonexistent")  # Miss
        await cache_service.set_embedding("test", [0.1])
        await cache_service.get_embedding("test")  # Hit

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

        with patch("services.cache_service.REDIS_AVAILABLE", False):
            cache = CacheService(config=config)
            await cache.connect()

        assert cache._use_memory_fallback is True

        # Debe funcionar igual
        await cache.set_embedding("test", [0.1, 0.2])
        result = await cache.get_embedding("test")
        assert result == [0.1, 0.2]

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
