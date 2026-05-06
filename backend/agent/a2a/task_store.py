"""
A2A Task Store
==============

In-memory and PostgreSQL-backed task stores for A2A task lifecycle management.
"""

import asyncio
import uuid
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from agent.utils.observability import Metrics, get_logger
from models.a2a_models import Task, TaskState, TaskStatus
from services.database_service import DatabaseService, get_database_service

logger = get_logger(__name__)


def _record_phase_latency(phase: str, duration_seconds: float, agent_type: str) -> None:
    """Record standardized A2A phase latency metric."""
    Metrics.observe_histogram(
        "a2a_phase_latency_seconds",
        duration_seconds,
        labels={"phase": phase, "agent": agent_type},
    )


class TaskStore:
    """
    In-memory task store for A2A task management.

    In production, this should be replaced with a persistent store
    such as PostgreSQL for durability and multi-instance support.
    """

    def __init__(self):
        self._tasks: dict[str, Task] = {}
        self._context_tasks: dict[str, list[str]] = {}  # contextId -> [taskIds]
        self._lock = asyncio.Lock()

    async def create_task(
        self,
        context_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Task:
        """Create a new task."""
        async with self._lock:
            task = Task(
                id=str(uuid.uuid4()),
                contextId=context_id or str(uuid.uuid4()),
                status=TaskStatus(state=TaskState.SUBMITTED),
                artifacts=[],
                history=[],
                metadata=metadata or {},
            )
            self._tasks[task.id] = task

            # Track by context
            if task.contextId not in self._context_tasks:
                self._context_tasks[task.contextId] = []
            self._context_tasks[task.contextId].append(task.id)

            return task

    async def get_task(self, task_id: str) -> Task | None:
        """Get a task by ID."""
        return self._tasks.get(task_id)

    async def update_task(self, task: Task) -> Task:
        """Update a task."""
        async with self._lock:
            self._tasks[task.id] = task
            return task

    async def list_tasks(
        self,
        context_id: str | None = None,
        status: TaskState | None = None,
        page_size: int = 50,
        include_artifacts: bool = False,
        user_id: str | None = None,
    ) -> tuple[list[Task], int]:
        """List tasks with optional filtering."""
        tasks = list(self._tasks.values())

        if context_id:
            task_ids = self._context_tasks.get(context_id, [])
            tasks = [t for t in tasks if t.id in task_ids]

        if status:
            tasks = [t for t in tasks if t.status.state == status]

        if user_id:
            tasks = [t for t in tasks if (t.metadata or {}).get("user_id") == user_id]

        # Sort by timestamp descending
        tasks.sort(
            key=lambda t: t.status.timestamp or datetime.min,
            reverse=True,
        )

        total = len(tasks)
        tasks = tasks[:page_size]

        if not include_artifacts:
            # Strip artifacts for response size
            tasks = [
                Task(
                    id=t.id,
                    contextId=t.contextId,
                    status=t.status,
                    history=t.history,
                    metadata=t.metadata,
                )
                for t in tasks
            ]

        return tasks, total

    async def cancel_task(self, task_id: str) -> Task | None:
        """Cancel a task if possible."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None

            # Check if cancellable
            terminal_states = {
                TaskState.COMPLETED,
                TaskState.FAILED,
                TaskState.CANCELED,
                TaskState.REJECTED,
            }
            if task.status.state in terminal_states:
                return None  # Not cancellable

            task.status = TaskStatus(
                state=TaskState.CANCELED,
                timestamp=datetime.now(UTC),
            )
            self._tasks[task_id] = task
            return task


class PersistentTaskStore:
    """PostgreSQL-backed task store for durable A2A task lifecycle state."""

    def __init__(self, db: DatabaseService):
        self._db = db
        self._lock = asyncio.Lock()

    @staticmethod
    def _task_to_row(task: Task) -> dict[str, Any]:
        return {
            "id": task.id,
            "context_id": task.contextId,
            "status_state": str(task.status.state),
            "status_timestamp": task.status.timestamp,
            "status_payload": task.status.model_dump(mode="json"),
            "artifacts": [a.model_dump(mode="json") for a in (task.artifacts or [])],
            "history": [m.model_dump(mode="json") for m in (task.history or [])],
            "task_metadata": task.metadata or {},
        }

    @staticmethod
    def _row_to_task(row: Any, include_artifacts: bool = True) -> Task:
        status_payload = row.status_payload or {"state": TaskState.SUBMITTED}
        artifacts_payload = row.artifacts if include_artifacts else None

        return Task.model_validate(
            {
                "id": row.id,
                "contextId": row.context_id,
                "status": status_payload,
                "artifacts": artifacts_payload,
                "history": row.history,
                "metadata": row.task_metadata,
            }
        )

    async def create_task(
        self,
        context_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Task:
        start = perf_counter()
        task = Task(
            id=str(uuid.uuid4()),
            contextId=context_id or str(uuid.uuid4()),
            status=TaskStatus(state=TaskState.SUBMITTED),
            artifacts=[],
            history=[],
            metadata=metadata or {},
        )

        async with self._lock:
            await asyncio.to_thread(self._db.upsert_a2a_task, self._task_to_row(task))
            _record_phase_latency("task_persist", perf_counter() - start, "persistent_store")
            return task

    async def get_task(self, task_id: str) -> Task | None:
        row = await asyncio.to_thread(self._db.get_a2a_task, task_id)
        if not row:
            return None
        return self._row_to_task(row)

    async def update_task(self, task: Task) -> Task:
        start = perf_counter()
        async with self._lock:
            await asyncio.to_thread(self._db.upsert_a2a_task, self._task_to_row(task))
            _record_phase_latency("task_persist", perf_counter() - start, "persistent_store")
            return task

    async def list_tasks(
        self,
        context_id: str | None = None,
        status: TaskState | None = None,
        page_size: int = 50,
        include_artifacts: bool = False,
        user_id: str | None = None,
    ) -> tuple[list[Task], int]:
        rows, total = await asyncio.to_thread(
            self._db.list_a2a_tasks,
            context_id,
            str(status) if status is not None else None,
            page_size,
            user_id,
        )
        tasks = [self._row_to_task(row, include_artifacts=include_artifacts) for row in rows]
        return tasks, total

    async def cancel_task(self, task_id: str) -> Task | None:
        async with self._lock:
            task = await self.get_task(task_id)
            if not task:
                return None

            terminal_states = {
                TaskState.COMPLETED,
                TaskState.FAILED,
                TaskState.CANCELED,
                TaskState.REJECTED,
            }
            if task.status.state in terminal_states:
                return None

            task.status = TaskStatus(
                state=TaskState.CANCELED,
                timestamp=datetime.now(UTC),
            )
            persist_start = perf_counter()
            await asyncio.to_thread(self._db.upsert_a2a_task, self._task_to_row(task))
            _record_phase_latency(
                "task_persist", perf_counter() - persist_start, "persistent_store"
            )
            return task


# Global task store instance
_task_store: TaskStore | PersistentTaskStore | None = None


def get_task_store() -> TaskStore | PersistentTaskStore:
    """Get or create the global task store."""
    global _task_store
    if _task_store is None:
        try:
            db = get_database_service()
            health = db.health_check()
            if health.get("status") == "healthy":
                _task_store = PersistentTaskStore(db)
                logger.info("Using persistent PostgreSQL A2A TaskStore")
            else:
                logger.warning("Database not healthy, using in-memory A2A TaskStore fallback")
                _task_store = TaskStore()
        except Exception as exc:
            logger.warning(f"Failed to initialize persistent A2A TaskStore: {exc}")
            _task_store = TaskStore()
    return _task_store
