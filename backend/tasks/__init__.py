"""
QPrisma Tasks Module
Tareas asíncronas con Celery para procesamiento de video.

Uso:
    # Importar la app de Celery
    from tasks.celery_app import celery_app

    # Importar tasks específicas
    from tasks.video_tasks import process_video_task
"""

from tasks.celery_app import celery_app

__all__ = ["celery_app"]
