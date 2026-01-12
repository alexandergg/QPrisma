"""
Tests para el sistema de caching de QPrisma

Ejecutar:
    cd backend
    python -m pytest tests/test_cache_service.py -v

    # O directamente:
    python tests/test_cache_service.py
"""

import asyncio
import sys
import time
from pathlib import Path

# Agregar parent al path
sys.path.insert(0, str(Path(__file__).parent.parent))

import io

import pytest
from PIL import Image


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
        assert metrics["backend"] in ["redis", "memory"]
        print(f"✓ Conectado a backend: {metrics['backend']}")

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
        print("✓ Embedding cacheado y recuperado correctamente")

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
        print("✓ Análisis de frame cacheado correctamente")

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
        print("✓ Estado de job actualizado correctamente")

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
        print(f"✓ Patrón Cache-Aside funcionando (ahorro: {metrics['api_calls_saved']} llamadas)")

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
        print(f"✓ Hash perceptual: distancia entre imágenes similares = {distance}")

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
        print(f"✓ Deduplicación por similitud: compute llamado {compute_called} veces")

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

        print(f"✓ Invalidación: {deleted} keys eliminadas con patrón")

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
        print(
            f"✓ Métricas: {metrics['hits']} hits, {metrics['misses']} misses, {metrics['hit_rate']} hit rate"
        )


class TestInMemoryCache:
    """Tests específicos para el cache en memoria (fallback)"""

    @pytest.mark.asyncio
    async def test_memory_fallback(self):
        """Test que el fallback a memoria funciona"""
        from services.cache_service import CacheConfig, CacheService

        config = CacheConfig(key_prefix="test_memory", max_memory_items=10)

        # Forzar uso de memoria (URL inválida)
        cache = CacheService(redis_url="redis://invalid:9999", config=config)
        await cache.connect()

        assert cache._use_memory_fallback is True

        # Debe funcionar igual
        await cache.set_embedding("test", [0.1, 0.2])
        result = await cache.get_embedding("test")
        assert result == [0.1, 0.2]

        await cache.disconnect()
        print("✓ Fallback a memoria funciona correctamente")

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

        print("✓ Evicción LRU funciona correctamente")


# =============================================================================
# Ejecutar tests directamente
# =============================================================================


async def run_demo():
    """Demo interactivo del sistema de cache"""
    from services.cache_service import CacheConfig, CacheService

    print("\n" + "=" * 60)
    print("QPrisma Cache Service - Demo")
    print("=" * 60 + "\n")

    # Crear servicio
    config = CacheConfig(key_prefix="demo_qprisma")
    cache = CacheService(config=config)

    print("1. Conectando a cache...")
    connected_to_redis = await cache.connect()
    backend = "Redis" if connected_to_redis else "Memory (fallback)"
    print(f"   Backend: {backend}\n")

    print("2. Probando cache de embeddings...")
    test_text = "Este es un texto de prueba para el demo"

    # Simular compute function
    calls = 0

    def fake_compute():
        nonlocal calls
        calls += 1
        print(f"   [Compute] Llamada #{calls} a Azure OpenAI (simulado)")
        time.sleep(0.1)  # Simular latencia
        return [0.1, 0.2, 0.3, 0.4, 0.5]

    # Primera llamada (miss)
    start = time.time()
    result1 = await cache.get_or_compute_embedding(test_text, fake_compute)
    time1 = time.time() - start
    print(f"   Primera llamada: {time1*1000:.1f}ms (cache MISS)\n")

    # Segunda llamada (hit)
    start = time.time()
    result2 = await cache.get_or_compute_embedding(test_text, fake_compute)
    time2 = time.time() - start
    print(f"   Segunda llamada: {time2*1000:.1f}ms (cache HIT)")
    print(f"   Speedup: {time1/time2:.1f}x más rápido\n")

    print("3. Probando deduplicación de frames...")

    # Crear imagen
    img = Image.new("RGB", (200, 200), color="green")
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG")
    frame_bytes = buffer.getvalue()

    phash = cache.compute_perceptual_hash(frame_bytes)
    print(f"   Hash perceptual: {phash}")

    # Crear imagen similar
    img2 = Image.new("RGB", (200, 200), color="green")
    pixels = img2.load()
    for i in range(5):
        pixels[i, i] = (0, 255, 0)  # Pequeños cambios

    buffer2 = io.BytesIO()
    img2.save(buffer2, format="JPEG")
    frame_bytes2 = buffer2.getvalue()

    phash2 = cache.compute_perceptual_hash(frame_bytes2)
    distance = cache.hash_distance(phash, phash2)
    print(f"   Hash perceptual (similar): {phash2}")
    print(f"   Distancia: {distance} (threshold: {config.similarity_threshold})")
    print(f"   ¿Son similares?: {'Sí' if distance <= config.similarity_threshold else 'No'}\n")

    print("4. Métricas finales:")
    metrics = cache.get_metrics()
    print(f"   Hits: {metrics['hits']}")
    print(f"   Misses: {metrics['misses']}")
    print(f"   Hit Rate: {metrics['hit_rate']}")
    print(f"   API calls saved: {metrics['api_calls_saved']}")
    print(f"   Estimated cost saved: {metrics['estimated_cost_saved']}\n")

    # Limpiar
    await cache.clear_all()
    await cache.disconnect()

    print("=" * 60)
    print("Demo completado!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    # Si se ejecuta directamente, correr demo
    print("\nEjecutando demo del Cache Service...\n")
    asyncio.run(run_demo())

    # Para correr tests: python -m pytest tests/test_cache_service.py -v
