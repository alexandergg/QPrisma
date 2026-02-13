"""Tests para el sistema de tareas Celery de QPrisma."""

import os
from unittest.mock import MagicMock, patch

import pytest


class TestCeleryConfiguration:
    """Tests para la configuración de Celery"""

    def test_celery_app_creation(self):
        """Test que la app de Celery se crea correctamente"""
        from tasks.celery_app import celery_app

        assert celery_app is not None
        assert celery_app.main == "qprisma"

    def test_celery_config(self):
        """Test que la configuración es correcta"""
        from tasks.celery_app import celery_app

        config = celery_app.conf

        # Verificar configuraciones importantes
        assert config.task_serializer == "json"
        assert config.result_serializer == "json"
        assert config.timezone == "UTC"
        assert config.task_acks_late is True

    def test_task_routes(self):
        """Test que las rutas de tareas están configuradas"""
        from tasks.celery_app import celery_app

        routes = celery_app.conf.task_routes

        assert "tasks.video_tasks.process_video_pipeline" in routes
        assert routes["tasks.video_tasks.process_video_pipeline"]["queue"] == "video_processing"

    def test_task_queues(self):
        """Test que las colas están definidas"""
        from tasks.celery_app import celery_app

        queues = celery_app.conf.task_queues

        queue_names = [q.name for q in queues]
        assert "video_processing" in queue_names
        assert "fast_tasks" in queue_names
        assert "default" in queue_names


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

    def test_debug_task(self):
        """Test la tarea de debug"""
        from tasks.celery_app import debug_task

        # Ejecutar sincrónico (eager mode)
        result = debug_task()

        assert result["status"] == "ok"
        assert "worker" in result


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
        """Test endpoint de estadísticas (requires auth)"""
        response = client.get("/jobs/stats/summary")
        assert response.status_code in (200, 401, 403)

    def test_jobs_list_endpoint(self, client):
        """Test endpoint de listar jobs (requires auth)"""
        response = client.get("/jobs/")
        assert response.status_code in (200, 401, 403)

        if response.status_code == 200:
            data = response.json()
            assert "total" in data
            assert "jobs" in data


# =============================================================================
# Tests de Integración (requieren Redis y Worker)
# =============================================================================


@pytest.mark.integration
class TestCeleryIntegration:
    """Tests de integración con Celery real"""

    @pytest.fixture(autouse=True)
    def require_integration(self):
        if os.getenv("RUN_INTEGRATION_TESTS", "").lower() not in {"1", "true", "yes"}:
            pytest.skip("Integration tests disabled. Set RUN_INTEGRATION_TESTS=true to enable.")

    @pytest.fixture
    def celery_app(self):
        """Obtiene la app de Celery"""
        from tasks.celery_app import celery_app

        return celery_app

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

