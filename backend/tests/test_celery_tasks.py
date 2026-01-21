"""
Tests para el sistema de tareas Celery de QPrisma

Ejecutar:
    # Tests unitarios (sin broker real)
    cd backend
    python -m pytest tests/test_celery_tasks.py -v

    # Test con Celery real (requiere Redis + Worker)
    python tests/test_celery_tasks.py --live

    # Solo verificar configuración
    python tests/test_celery_tasks.py --check
"""

import os
import sys
from pathlib import Path

# Agregar parent al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from unittest.mock import MagicMock, patch

import pytest


class TestCeleryConfiguration:
    """Tests para la configuración de Celery"""

    def test_celery_app_creation(self):
        """Test que la app de Celery se crea correctamente"""
        from tasks.celery_app import celery_app

        assert celery_app is not None
        assert celery_app.main == "qprisma"
        print("✓ Celery app creada correctamente")

    def test_celery_config(self):
        """Test que la configuración es correcta"""
        from tasks.celery_app import celery_app

        config = celery_app.conf

        # Verificar configuraciones importantes
        assert config.task_serializer == "json"
        assert config.result_serializer == "json"
        assert config.timezone == "UTC"
        assert config.task_acks_late is True
        print("✓ Configuración de Celery correcta")

    def test_task_routes(self):
        """Test que las rutas de tareas están configuradas"""
        from tasks.celery_app import celery_app

        routes = celery_app.conf.task_routes

        assert "tasks.video_tasks.process_video_pipeline" in routes
        assert routes["tasks.video_tasks.process_video_pipeline"]["queue"] == "video_processing"
        print("✓ Rutas de tareas configuradas")

    def test_task_queues(self):
        """Test que las colas están definidas"""
        from tasks.celery_app import celery_app

        queues = celery_app.conf.task_queues

        queue_names = [q.name for q in queues]
        assert "video_processing" in queue_names
        assert "fast_tasks" in queue_names
        assert "default" in queue_names
        print("✓ Colas de tareas definidas")


class TestVideoTasks:
    """Tests para las tareas de video"""

    def test_tasks_registered(self):
        """Test que las tareas están registradas"""
        # Forzar importación de tasks
        from tasks import video_tasks  # noqa: F401
        from tasks.celery_app import celery_app

        registered = list(celery_app.tasks.keys())

        expected_tasks = [
            "tasks.video_tasks.process_video_pipeline",
            "tasks.video_tasks.download_video_task",
            "tasks.video_tasks.extract_frames_task",
            "tasks.video_tasks.analyze_frame_task",
            "tasks.video_tasks.generate_embeddings_batch_task",
        ]

        for task in expected_tasks:
            assert task in registered, f"Task {task} no registrada"

        print(f"✓ {len(expected_tasks)} tareas registradas correctamente")

    def test_debug_task(self):
        """Test la tarea de debug"""
        from tasks.celery_app import debug_task

        # Ejecutar sincrónico (eager mode)
        result = debug_task()

        assert result["status"] == "ok"
        assert "worker" in result
        print("✓ Task de debug funciona")


class TestTasksEagerMode:
    """Tests con tareas en modo eager (sincrónico)"""

    @pytest.fixture(autouse=True)
    def setup_eager_mode(self):
        """Configura Celery en modo eager para tests"""
        from tasks.celery_app import celery_app

        original_eager = celery_app.conf.task_always_eager
        original_propagate = celery_app.conf.task_eager_propagates

        celery_app.conf.task_always_eager = True
        celery_app.conf.task_eager_propagates = True

        yield

        celery_app.conf.task_always_eager = original_eager
        celery_app.conf.task_eager_propagates = original_propagate

    def test_update_job_status_task(self):
        """Test actualización de estado de job"""
        from tasks.video_tasks import update_job_status

        # Mock del cache
        with patch("tasks.video_tasks._get_cache_service") as mock_cache:
            mock_cache_instance = MagicMock()
            mock_cache.return_value = mock_cache_instance

            # Configurar mock async
            async def mock_set_job_status(*args, **kwargs):
                return True

            mock_cache_instance.set_job_status = mock_set_job_status

            result = update_job_status(
                job_id="test_job_123",
                status="processing",
                progress=50,
                stage="analyzing",
                message="Test message",
            )

            assert result["job_id"] == "test_job_123"
            assert result["status"] == "processing"

        print("✓ Task update_job_status funciona")

    def test_cleanup_task(self):
        """Test limpieza de archivos temporales"""
        import tempfile

        from tasks.video_tasks import cleanup_task

        # Crear archivo temporal
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        assert os.path.exists(tmp_path)

        # Ejecutar cleanup
        cleanup_task(tmp_path)

        assert not os.path.exists(tmp_path)
        print("✓ Task cleanup funciona")


class TestJobsAPI:
    """Tests para los endpoints de jobs"""

    @pytest.fixture
    def client(self):
        """Cliente de test para FastAPI"""
        from fastapi.testclient import TestClient

        # Mock del main para evitar inicialización de Azure
        with patch.dict(
            os.environ,
            {
                "AZURE_STORAGE_CONNECTION_STRING": "",
                "AZURE_OPENAI_ENDPOINT": "",
            },
        ):
            from api.main import app

            return TestClient(app)

    def test_jobs_stats_endpoint(self, client):
        """Test endpoint de estadísticas"""
        response = client.get("/jobs/stats/summary")
        assert response.status_code == 200

        data = response.json()
        assert "celery_available" in data
        print("✓ Endpoint /jobs/stats/summary funciona")

    def test_jobs_list_endpoint(self, client):
        """Test endpoint de listar jobs"""
        response = client.get("/jobs/")
        assert response.status_code == 200

        data = response.json()
        assert "total" in data
        assert "jobs" in data
        print("✓ Endpoint /jobs/ funciona")


# =============================================================================
# Tests de Integración (requieren Redis y Worker)
# =============================================================================


class TestCeleryIntegration:
    """Tests de integración con Celery real"""

    @pytest.fixture
    def celery_app(self):
        """Obtiene la app de Celery"""
        from tasks.celery_app import celery_app

        return celery_app

    @pytest.mark.skip(reason="Requiere Redis y Worker corriendo")
    def test_submit_and_track_job(self, celery_app):
        """Test completo de envío y tracking de job"""
        from tasks.video_tasks import process_video_pipeline

        # Enviar tarea
        result = process_video_pipeline.delay(
            video_id="test_video", blob_name="test/video.mp4", config={"max_frames": 5}
        )

        # Verificar que se envió
        assert result.id is not None

        # Esperar un poco y verificar estado
        import time

        time.sleep(2)

        assert result.state in ["PENDING", "STARTED", "SUCCESS", "FAILURE"]
        print(f"✓ Job enviado: {result.id}, estado: {result.state}")


# =============================================================================
# Demo / CLI
# =============================================================================


def check_celery_setup():
    """Verifica que Celery está configurado correctamente"""
    print("\n" + "=" * 60)
    print("QPrisma Celery Setup Check")
    print("=" * 60 + "\n")

    # 1. Verificar importación
    print("1. Verificando importación de Celery...")
    try:
        from tasks.celery_app import celery_app

        print("   ✓ Celery app importada correctamente")
    except Exception as e:
        print(f"   ✗ Error: {e}")
        return False

    # 2. Verificar tasks
    print("\n2. Verificando tasks registradas...")
    try:
        tasks_count = len([t for t in celery_app.tasks if t.startswith("tasks.")])
        print(f"   ✓ {tasks_count} tasks registradas")
    except Exception as e:
        print(f"   ✗ Error: {e}")
        return False

    # 3. Verificar conexión a Redis
    print("\n3. Verificando conexión a Redis...")
    try:
        import redis

        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = redis.from_url(redis_url)
        r.ping()
        print(f"   ✓ Redis conectado en {redis_url}")
    except Exception as e:
        print(f"   ⚠ Redis no disponible: {e}")
        print("   (El worker no podrá ejecutarse sin Redis)")

    # 4. Verificar colas
    print("\n4. Verificando colas configuradas...")
    queues = [q.name for q in celery_app.conf.task_queues]
    for q in queues:
        print(f"   ✓ Cola: {q}")

    print("\n" + "=" * 60)
    print("Setup verificado correctamente!")
    print("=" * 60)

    print("\nPara iniciar el sistema:")
    print("  1. docker-compose up -d redis")
    print("  2. celery -A tasks.celery_app worker --loglevel=info")
    print("  3. python api/main.py")
    print("\nO con Docker:")
    print("  docker-compose --profile worker up -d")

    return True


def run_live_test():
    """Ejecuta un test en vivo con Celery"""
    print("\n" + "=" * 60)
    print("QPrisma Celery Live Test")
    print("=" * 60 + "\n")

    print("Este test requiere:")
    print("  - Redis corriendo (docker-compose up -d redis)")
    print("  - Worker corriendo (celery -A tasks.celery_app worker)")
    print()

    try:
        from tasks.celery_app import celery_app, debug_task

        # Test 1: Debug task
        print("1. Enviando debug task...")
        result = debug_task.delay()
        print(f"   Task ID: {result.id}")

        # Esperar resultado
        import time

        for i in range(10):
            if result.ready():
                break
            print(f"   Esperando... ({i+1}s)")
            time.sleep(1)

        if result.ready():
            print(f"   ✓ Resultado: {result.result}")
        else:
            print("   ⚠ Timeout esperando resultado")

        # Test 2: Verificar workers
        print("\n2. Verificando workers activos...")
        inspect = celery_app.control.inspect()
        active = inspect.active()
        if active:
            for worker, tasks in active.items():
                print(f"   ✓ Worker: {worker} ({len(tasks)} tasks activas)")
        else:
            print("   ⚠ No hay workers activos")

        print("\n" + "=" * 60)
        print("Live test completado!")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ Error: {e}")
        print("\nAsegúrate de que Redis y el Worker están corriendo.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test Celery para QPrisma")
    parser.add_argument("--check", action="store_true", help="Solo verificar setup")
    parser.add_argument("--live", action="store_true", help="Test en vivo con Celery")

    args = parser.parse_args()

    if args.check:
        check_celery_setup()
    elif args.live:
        run_live_test()
    else:
        # Por defecto, verificar setup
        check_celery_setup()
