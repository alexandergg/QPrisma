"""
Celery Application Configuration para QPrisma

Este módulo configura Celery para procesamiento asíncrono de videos.

Características:
- Redis como broker y backend de resultados
- Retry automático con exponential backoff
- Rate limiting para proteger Azure OpenAI
- Prioridad de tareas
- Dead letter queue para fallos permanentes

Uso:
    # Iniciar worker
    celery -A tasks.celery_app worker --loglevel=info

    # Iniciar worker con concurrencia específica
    celery -A tasks.celery_app worker --loglevel=info --concurrency=4

    # Iniciar Flower (dashboard)
    celery -A tasks.celery_app flower --port=5555

    # En código Python
    from tasks.celery_app import celery_app
    from tasks.video_tasks import process_video_task

    # Ejecutar task async
    result = process_video_task.delay(video_id, config)

    # Verificar estado
    result.status  # PENDING, STARTED, SUCCESS, FAILURE
    result.get()   # Esperar resultado (bloqueante)
"""

import os
import sys
from pathlib import Path

# Asegurar que el backend está en el path
backend_path = str(Path(__file__).parent.parent)
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from celery import Celery
from dotenv import load_dotenv
from kombu import Exchange, Queue

# Cargar variables de entorno
load_dotenv()

# Configuración de Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Crear aplicación Celery
celery_app = Celery(
    "qprisma",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "tasks.video_tasks",
    ],
)

# =============================================================================
# Configuración de Celery
# =============================================================================

celery_app.conf.update(
    # -------------------------------------------------------------------------
    # Serialización
    # -------------------------------------------------------------------------
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # -------------------------------------------------------------------------
    # Timezone
    # -------------------------------------------------------------------------
    timezone="UTC",
    enable_utc=True,
    # -------------------------------------------------------------------------
    # Resultados
    # -------------------------------------------------------------------------
    result_expires=86400,  # 24 horas
    result_extended=True,  # Incluir task name, args, kwargs en resultado
    # -------------------------------------------------------------------------
    # Comportamiento del Worker
    # -------------------------------------------------------------------------
    worker_prefetch_multiplier=1,  # Una tarea a la vez por worker (para GPU)
    worker_concurrency=2,  # 2 workers por defecto (ajustar según recursos)
    task_acks_late=True,  # ACK después de completar (no al recibir)
    task_reject_on_worker_lost=True,  # Re-queue si worker muere
    # -------------------------------------------------------------------------
    # Rate Limiting (proteger Azure OpenAI)
    # -------------------------------------------------------------------------
    task_annotations={
        "tasks.video_tasks.analyze_frame_task": {"rate_limit": "30/m"},  # Max 30 frames por minuto
        "tasks.video_tasks.generate_embedding_task": {
            "rate_limit": "60/m"  # Max 60 embeddings por minuto
        },
    },
    # -------------------------------------------------------------------------
    # Retry Policy
    # -------------------------------------------------------------------------
    task_default_retry_delay=60,  # 1 minuto entre retries
    task_max_retries=3,
    # -------------------------------------------------------------------------
    # Colas y Prioridades
    # -------------------------------------------------------------------------
    task_queues=(
        # Cola principal para procesamiento de video
        Queue(
            "video_processing",
            Exchange("video_processing"),
            routing_key="video.#",
            queue_arguments={"x-max-priority": 10},
        ),
        # Cola para tareas rápidas (embeddings, cache)
        Queue(
            "fast_tasks",
            Exchange("fast_tasks"),
            routing_key="fast.#",
            queue_arguments={"x-max-priority": 5},
        ),
        # Cola por defecto
        Queue("default", Exchange("default"), routing_key="default"),
    ),
    task_default_queue="default",
    task_default_exchange="default",
    task_default_routing_key="default",
    # Routing de tareas a colas específicas
    task_routes={
        "tasks.video_tasks.process_video_task": {
            "queue": "video_processing",
            "routing_key": "video.process",
        },
        "tasks.video_tasks.process_video_pipeline": {
            "queue": "video_processing",
            "routing_key": "video.pipeline",
        },
        "tasks.video_tasks.analyze_frame_task": {
            "queue": "video_processing",
            "routing_key": "video.analyze",
        },
        "tasks.video_tasks.generate_embedding_task": {
            "queue": "fast_tasks",
            "routing_key": "fast.embedding",
        },
        "tasks.video_tasks.index_content_task": {
            "queue": "fast_tasks",
            "routing_key": "fast.index",
        },
    },
    # -------------------------------------------------------------------------
    # Monitoreo
    # -------------------------------------------------------------------------
    worker_send_task_events=True,
    task_send_sent_event=True,
    # -------------------------------------------------------------------------
    # Seguridad
    # -------------------------------------------------------------------------
    task_always_eager=False,  # True para testing sin broker
)


# =============================================================================
# Hooks y Signals
# =============================================================================


@celery_app.task(bind=True)
def debug_task(self):
    """Task de debug para verificar que Celery funciona"""
    print(f"Request: {self.request!r}")
    return {"status": "ok", "worker": self.request.hostname}


# Signal cuando una tarea empieza
from celery.signals import task_failure, task_postrun, task_prerun


@task_prerun.connect
def task_prerun_handler(task_id, task, args, kwargs, **kw):
    """Se ejecuta antes de cada tarea"""
    print(f"[TASK START] {task.name} ({task_id})")


@task_postrun.connect
def task_postrun_handler(task_id, task, args, kwargs, retval, state, **kw):
    """Se ejecuta después de cada tarea"""
    print(f"[TASK END] {task.name} ({task_id}) -> {state}")


@task_failure.connect
def task_failure_handler(task_id, exception, args, kwargs, traceback, einfo, **kw):
    """Se ejecuta cuando una tarea falla"""
    print(f"[TASK FAILED] {task_id}: {exception}")


# =============================================================================
# Configuración para diferentes entornos
# =============================================================================


def configure_for_testing():
    """Configura Celery para testing (sincrónico, sin broker)"""
    celery_app.conf.update(
        task_always_eager=True,
        task_eager_propagates=True,
    )


def configure_for_production():
    """Configuración adicional para producción"""
    celery_app.conf.update(
        worker_concurrency=4,
        worker_prefetch_multiplier=2,
    )


# Auto-configurar según entorno
APP_ENV = os.getenv("APP_ENV", "development")
if APP_ENV == "testing":
    configure_for_testing()
elif APP_ENV == "production":
    configure_for_production()
