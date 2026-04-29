from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent.a2a import PersistentTaskStore, TaskStore

from models.a2a_models import TaskState


def test_get_task_store_prefers_persistent_when_db_healthy():
    import agent.a2a.task_store as a2a_task_store

    a2a_task_store._task_store = None
    mock_db = MagicMock()
    mock_db.health_check.return_value = {"status": "healthy"}

    with patch("agent.a2a.task_store.get_database_service", return_value=mock_db):
        store = a2a_task_store.get_task_store()

    assert isinstance(store, PersistentTaskStore)


def test_get_task_store_falls_back_when_db_unhealthy():
    import agent.a2a.task_store as a2a_task_store

    a2a_task_store._task_store = None
    mock_db = MagicMock()
    mock_db.health_check.return_value = {"status": "unhealthy"}

    with patch("agent.a2a.task_store.get_database_service", return_value=mock_db):
        store = a2a_task_store.get_task_store()

    assert isinstance(store, TaskStore)


def test_persistent_row_to_task_conversion_roundtrip_shape():
    row = SimpleNamespace(
        id="task-1",
        context_id="ctx-1",
        status_payload={
            "state": TaskState.WORKING.value,
            "timestamp": "2026-02-14T12:00:00Z",
        },
        artifacts=[{"artifactId": "a1", "parts": [{"text": "hello"}]}],
        history=[
            {
                "messageId": "m1",
                "role": "ROLE_USER",
                "parts": [{"text": "hi"}],
            }
        ],
        task_metadata={"source": "test"},
    )

    task = PersistentTaskStore._row_to_task(row)

    assert task.id == "task-1"
    assert task.contextId == "ctx-1"
    assert task.status.state == TaskState.WORKING
    assert task.artifacts is not None
    assert task.history is not None


async def test_in_memory_task_store_filters_by_user_id():
    store = TaskStore()

    user_1_task = await store.create_task(context_id="ctx-1", metadata={"user_id": "user-1"})
    await store.create_task(context_id="ctx-1", metadata={"user_id": "user-2"})

    tasks, total = await store.list_tasks(context_id="ctx-1", user_id="user-1")

    assert total == 1
    assert [task.id for task in tasks] == [user_1_task.id]


async def test_persistent_task_store_passes_user_filter_to_database():
    db = MagicMock()
    db.list_a2a_tasks.return_value = ([], 0)
    store = PersistentTaskStore(db)

    tasks, total = await store.list_tasks(context_id="ctx-1", user_id="user-1")

    assert tasks == []
    assert total == 0
    db.list_a2a_tasks.assert_called_once_with("ctx-1", None, 50, "user-1")
