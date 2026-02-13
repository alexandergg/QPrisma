"""
QPrisma Tasks Module
Asynchronous Celery tasks for video processing.

Usage:
    # Import Celery app
    from tasks.celery_app import celery_app

    # Import specific tasks
    from tasks.video_tasks import process_video_task
"""

from tasks.celery_app import celery_app

__all__ = ["celery_app"]
