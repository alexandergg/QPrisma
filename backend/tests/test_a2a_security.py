from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from models.a2a_models import Message, Part, Role, Task, TaskState, TaskStatus


def _make_send_body(
    metadata: dict | None = None,
    request_metadata: dict | None = None,
    task_id: str | None = None,
    context_id: str | None = None,
) -> dict:
    body = {
        "message": {
            "role": "ROLE_USER",
            "parts": [{"text": "hello"}],
        }
    }
    if metadata is not None:
        body["message"]["metadata"] = metadata
    if task_id is not None:
        body["message"]["taskId"] = task_id
    if context_id is not None:
        body["message"]["contextId"] = context_id
    if request_metadata is not None:
        body["metadata"] = request_metadata
    return body


def _make_task(
    task_id: str = "task-1",
    state: TaskState = TaskState.COMPLETED,
    user_id: str = "user_test123",
    context_id: str = "ctx-1",
) -> Task:
    return Task(
        id=task_id,
        contextId=context_id,
        status=TaskStatus(
            state=state,
            message=Message(role=Role.AGENT, parts=[Part(text="done")]),
        ),
        metadata={"user_id": user_id},
    )


@pytest.mark.unit
class TestA2AMessageSecurity:
    def test_send_message_requires_authentication(self, client):
        resp = client.post("/a2a/message:send", json=_make_send_body())

        assert resp.status_code in {401, 403}

    def test_send_message_overrides_client_user_id_and_persists_owner(
        self, authenticated_client, test_user
    ):
        mock_executor = MagicMock()
        mock_executor.send_message = AsyncMock(return_value=_make_task(user_id=test_user.id))

        with (
            patch("api.routes.a2a_message_routes.get_executor", return_value=mock_executor),
            patch("api.routes.a2a_security.get_media_or_404") as mock_get_media,
        ):
            resp = authenticated_client.post(
                "/a2a/message:send",
                json=_make_send_body(
                    metadata={"user_id": "attacker", "media_id": "media-1"},
                    request_metadata={"user_id": "attacker", "client": "test"},
                ),
            )

        assert resp.status_code == 200
        request_arg = mock_executor.send_message.call_args.args[0]
        assert request_arg.message.metadata["user_id"] == test_user.id
        assert request_arg.metadata["user_id"] == test_user.id
        assert request_arg.metadata["media_id"] == "media-1"
        assert request_arg.metadata["client"] == "test"
        mock_get_media.assert_called_once_with("media-1", test_user)

    def test_request_metadata_media_ids_are_dropped_unless_message_validated(
        self, authenticated_client, test_user
    ):
        mock_executor = MagicMock()
        mock_executor.send_message = AsyncMock(return_value=_make_task(user_id=test_user.id))

        with patch("api.routes.a2a_message_routes.get_executor", return_value=mock_executor):
            resp = authenticated_client.post(
                "/a2a/message:send",
                json=_make_send_body(
                    request_metadata={
                        "media_id": "media-other-user",
                        "media_ids": ["media-other-user"],
                        "client": "test",
                    },
                ),
            )

        assert resp.status_code == 200
        request_arg = mock_executor.send_message.call_args.args[0]
        assert "media_id" not in request_arg.metadata
        assert "media_ids" not in request_arg.metadata
        assert request_arg.metadata["client"] == "test"
        assert request_arg.metadata["user_id"] == test_user.id

    def test_send_message_validates_all_media_ids(self, authenticated_client, test_user):
        mock_executor = MagicMock()
        mock_executor.send_message = AsyncMock(return_value=_make_task(user_id=test_user.id))

        with (
            patch("api.routes.a2a_message_routes.get_executor", return_value=mock_executor),
            patch("api.routes.a2a_security.get_media_or_404") as mock_get_media,
        ):
            resp = authenticated_client.post(
                "/a2a/message:send",
                json=_make_send_body(metadata={"media_id": "media-1", "media_ids": ["media-2"]}),
            )

        assert resp.status_code == 200
        mock_get_media.assert_has_calls(
            [call("media-1", test_user), call("media-2", test_user)],
            any_order=True,
        )

    def test_send_message_hides_unowned_task_continuation(self, authenticated_client):
        mock_executor = MagicMock()
        mock_executor.get_task = AsyncMock(
            return_value=_make_task(task_id="task-other", user_id="other-user")
        )
        mock_executor.send_message = AsyncMock()

        with patch("api.routes.a2a_message_routes.get_executor", return_value=mock_executor):
            resp = authenticated_client.post(
                "/a2a/message:send",
                json=_make_send_body(task_id="task-other"),
            )

        assert resp.status_code == 404
        mock_executor.send_message.assert_not_called()

    def test_send_message_allows_owned_task_continuation(self, authenticated_client, test_user):
        mock_executor = MagicMock()
        mock_executor.get_task = AsyncMock(
            return_value=_make_task(task_id="task-owned", user_id=test_user.id)
        )
        mock_executor.send_message = AsyncMock(
            return_value=_make_task(task_id="task-owned", user_id=test_user.id)
        )

        with patch("api.routes.a2a_message_routes.get_executor", return_value=mock_executor):
            resp = authenticated_client.post(
                "/a2a/message:send",
                json=_make_send_body(task_id="task-owned"),
            )

        assert resp.status_code == 200
        mock_executor.send_message.assert_called_once()

    def test_send_message_hides_unowned_foundry_context_continuation(
        self, authenticated_client, test_user
    ):
        mock_executor = MagicMock()
        mock_executor.list_tasks = AsyncMock(return_value=([], 0))
        mock_executor.send_message = AsyncMock()

        with patch("api.routes.a2a_message_routes.get_executor", return_value=mock_executor):
            resp = authenticated_client.post(
                "/a2a/message:send",
                json=_make_send_body(context_id="foundry-conversation-other"),
            )

        assert resp.status_code == 404
        mock_executor.list_tasks.assert_awaited_once_with(
            context_id="foundry-conversation-other",
            page_size=1,
            user_id=test_user.id,
        )
        mock_executor.send_message.assert_not_called()

    def test_send_message_allows_owned_foundry_context_continuation(
        self, authenticated_client, test_user
    ):
        mock_executor = MagicMock()
        mock_executor.list_tasks = AsyncMock(
            return_value=(
                [_make_task(context_id="foundry-conversation-owned", user_id=test_user.id)],
                1,
            )
        )
        mock_executor.send_message = AsyncMock(return_value=_make_task(user_id=test_user.id))

        with patch("api.routes.a2a_message_routes.get_executor", return_value=mock_executor):
            resp = authenticated_client.post(
                "/a2a/message:send",
                json=_make_send_body(context_id="foundry-conversation-owned"),
            )

        assert resp.status_code == 200
        mock_executor.send_message.assert_called_once()

    def test_stream_message_requires_authentication(self, client):
        resp = client.post("/a2a/message:stream", json=_make_send_body())

        assert resp.status_code in {401, 403}

    def test_stream_message_hides_unowned_task_continuation(self, authenticated_client):
        mock_executor = MagicMock()
        mock_executor.get_task = AsyncMock(
            return_value=_make_task(task_id="task-other", user_id="other-user")
        )
        mock_executor.send_streaming_message = AsyncMock()

        with patch("api.routes.a2a_message_routes.get_executor", return_value=mock_executor):
            resp = authenticated_client.post(
                "/a2a/message:stream",
                json=_make_send_body(task_id="task-other"),
            )

        assert resp.status_code == 404
        mock_executor.send_streaming_message.assert_not_called()


@pytest.mark.unit
class TestA2ATaskSecurity:
    def test_get_task_requires_authentication(self, client):
        resp = client.get("/a2a/tasks/task-1")

        assert resp.status_code in {401, 403}

    def test_get_task_hides_other_users_task(self, authenticated_client):
        mock_executor = MagicMock()
        mock_executor.get_task = AsyncMock(return_value=_make_task(user_id="other-user"))

        with patch("api.routes.a2a_task_routes.get_executor", return_value=mock_executor):
            resp = authenticated_client.get("/a2a/tasks/task-1")

        assert resp.status_code == 404

    def test_get_task_returns_owned_task(self, authenticated_client, test_user):
        mock_executor = MagicMock()
        mock_executor.get_task = AsyncMock(return_value=_make_task(user_id=test_user.id))

        with patch("api.routes.a2a_task_routes.get_executor", return_value=mock_executor):
            resp = authenticated_client.get("/a2a/tasks/task-1")

        assert resp.status_code == 200
        assert resp.json()["id"] == "task-1"

    def test_list_tasks_passes_current_user_filter(self, authenticated_client, test_user):
        mock_executor = MagicMock()
        mock_executor.list_tasks = AsyncMock(return_value=([_make_task(user_id=test_user.id)], 1))

        with patch("api.routes.a2a_task_routes.get_executor", return_value=mock_executor):
            resp = authenticated_client.get("/a2a/tasks")

        assert resp.status_code == 200
        assert mock_executor.list_tasks.call_args.kwargs["user_id"] == test_user.id

    def test_cancel_task_hides_other_users_task(self, authenticated_client):
        mock_executor = MagicMock()
        mock_executor.get_task = AsyncMock(
            return_value=_make_task(state=TaskState.WORKING, user_id="other-user")
        )
        mock_executor.cancel_task = AsyncMock()

        with patch("api.routes.a2a_task_routes.get_executor", return_value=mock_executor):
            resp = authenticated_client.post("/a2a/tasks/task-1:cancel")

        assert resp.status_code == 404
        mock_executor.cancel_task.assert_not_called()

    def test_cancel_task_cancels_owned_task(self, authenticated_client, test_user):
        mock_executor = MagicMock()
        mock_executor.get_task = AsyncMock(
            return_value=_make_task(state=TaskState.WORKING, user_id=test_user.id)
        )
        mock_executor.cancel_task = AsyncMock(
            return_value=_make_task(state=TaskState.CANCELED, user_id=test_user.id)
        )

        with patch("api.routes.a2a_task_routes.get_executor", return_value=mock_executor):
            resp = authenticated_client.post("/a2a/tasks/task-1:cancel")

        assert resp.status_code == 200
        mock_executor.cancel_task.assert_awaited_once_with("task-1")

    def test_subscribe_task_hides_other_users_task(self, authenticated_client):
        mock_executor = MagicMock()
        mock_executor.get_task = AsyncMock(
            return_value=_make_task(state=TaskState.WORKING, user_id="other-user")
        )

        with patch("api.routes.a2a_task_routes.get_executor", return_value=mock_executor):
            resp = authenticated_client.post("/a2a/tasks/task-1:subscribe")

        assert resp.status_code == 404
