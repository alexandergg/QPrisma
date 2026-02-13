"""
Celery Application Configuration for QPrisma

This module configures Celery for asynchronous video processing.

Features:
- Redis as broker and result backend
- Automatic retry with exponential backoff
- Rate limiting to protect Azure OpenAI
- Task priority support
- Dead letter queue for permanent failures

Usage:
    # Start worker
    celery -A tasks.celery_app worker --loglevel=info

    # Start worker with specific concurrency
    celery -A tasks.celery_app worker --loglevel=info --concurrency=4

    # Start Flower (dashboard)
    celery -A tasks.celery_app flower --port=5555

    # In Python code
    from tasks.celery_app import celery_app
    from tasks.video_tasks import process_video_task

    # Execute task async
    result = process_video_task.delay(video_id, config)

    # Check status
    result.status  # PENDING, STARTED, SUCCESS, FAILURE
    result.get()   # Wait for result (blocking)
"""

import logging
import os
import sys
from pathlib import Path

# Ensure backend is on the path
backend_path = str(Path(__file__).parent.parent)
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from celery import Celery
from dotenv import load_dotenv
from kombu import Exchange, Queue

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Redis configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Azure Redis uses rediss:// (TLS) — Celery requires ssl_cert_reqs parameter
if REDIS_URL.startswith("rediss://") and "ssl_cert_reqs" not in REDIS_URL:
    separator = "&" if "?" in REDIS_URL else "?"
    REDIS_URL = f"{REDIS_URL}{separator}ssl_cert_reqs=CERT_REQUIRED"

# Create Celery application
celery_app = Celery(
    "qprisma",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "tasks.video_tasks",
    ],
)

# =============================================================================
# Celery Configuration
# =============================================================================

# Azure Redis Enterprise enforces cross-slot constraints in MULTI/EXEC even
# with EnterpriseCluster mode. Hash tags {celery} ensure all Celery/Kombu keys
# map to the same slot, avoiding ClusterCrossSlotError in pipeline transactions.
_redis_transport_opts = (
    {"global_keyprefix": "{celery}."} if REDIS_URL.startswith("rediss://") else {}
)

celery_app.conf.update(
    broker_transport_options=_redis_transport_opts,
    result_backend_transport_options=_redis_transport_opts,
    # -------------------------------------------------------------------------
    # Serialization
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
    # Results
    # -------------------------------------------------------------------------
    result_expires=86400,  # 24 hours
    result_extended=True,  # Include task name, args, kwargs in result
    # -------------------------------------------------------------------------
    # Worker Behavior
    # -------------------------------------------------------------------------
    worker_prefetch_multiplier=1,  # One task at a time per worker (for GPU)
    worker_concurrency=2,  # 2 workers by default (adjust per resources)
    task_acks_late=True,  # ACK after completion (not on receive)
    task_reject_on_worker_lost=True,  # Re-queue if worker dies
    # -------------------------------------------------------------------------
    # Rate Limiting (protect Azure OpenAI)
    # -------------------------------------------------------------------------
    task_annotations={
        "tasks.video_tasks.analyze_frame_task": {"rate_limit": "30/m"},  # Max 30 frames per minute
        "tasks.video_tasks.generate_embedding_task": {
            "rate_limit": "60/m"  # Max 60 embeddings per minute
        },
    },
    # -------------------------------------------------------------------------
    # Retry Policy
    # -------------------------------------------------------------------------
    task_default_retry_delay=60,  # 1 minute between retries
    task_max_retries=3,
    # -------------------------------------------------------------------------
    # Queues and Priorities
    # -------------------------------------------------------------------------
    task_queues=(
        # Main queue for video processing
        Queue(
            "video_processing",
            Exchange("video_processing"),
            routing_key="video.#",
            queue_arguments={"x-max-priority": 10},
        ),
        # Queue for fast tasks (embeddings, cache)
        Queue(
            "fast_tasks",
            Exchange("fast_tasks"),
            routing_key="fast.#",
            queue_arguments={"x-max-priority": 5},
        ),
        # Default queue
        Queue("default", Exchange("default"), routing_key="default"),
    ),
    task_default_queue="default",
    task_default_exchange="default",
    task_default_routing_key="default",
    # Task routing to specific queues
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
    # Monitoring
    # -------------------------------------------------------------------------
    worker_send_task_events=True,
    task_send_sent_event=True,
    # -------------------------------------------------------------------------
    # Security
    # -------------------------------------------------------------------------
    task_always_eager=False,  # True for testing without broker
)


# =============================================================================
# Hooks and Signals
# =============================================================================


@celery_app.task(bind=True)
def debug_task(self):
    """Debug task to verify Celery is working."""
    logger.debug("Request: %r", self.request)
    return {"status": "ok", "worker": self.request.hostname}


# Signal when a task starts
from celery.signals import task_failure, task_postrun, task_prerun


@task_prerun.connect
def task_prerun_handler(task_id, task, args, kwargs, **kw):
    """Runs before each task."""
    logger.info("[TASK START] %s (%s)", task.name, task_id)


@task_postrun.connect
def task_postrun_handler(task_id, task, args, kwargs, retval, state, **kw):
    """Runs after each task."""
    logger.info("[TASK END] %s (%s) -> %s", task.name, task_id, state)


@task_failure.connect
def task_failure_handler(task_id, exception, args, kwargs, traceback, einfo, **kw):
    """Runs when a task fails."""
    logger.error("[TASK FAILED] %s: %s", task_id, exception)


# =============================================================================
# Environment-specific Configuration
# =============================================================================


def configure_for_testing():
    """Configure Celery for testing (synchronous, no broker)."""
    celery_app.conf.update(
        task_always_eager=True,
        task_eager_propagates=True,
    )


def configure_for_production():
    """Additional configuration for production."""
    celery_app.conf.update(
        worker_concurrency=4,
        worker_prefetch_multiplier=2,
    )


# Auto-configure based on environment
APP_ENV = os.getenv("APP_ENV", "development")
if APP_ENV == "testing":
    configure_for_testing()
elif APP_ENV == "production":
    configure_for_production()
