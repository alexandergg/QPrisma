"""
Tests for WebSocket authentication security fixes.

Covers:
    - authenticate_websocket helper
    - /ws/jobs/{job_id}  — token via query param
    - /ws/user/{user_id} — token via query param + user_id ownership check
    - /ws/all            — first-message auth pattern
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.websockets import WebSocketDisconnect

from api.routes.websocket_routes import authenticate_websocket


def _mock_entra_service(oid="user_abc123", email="alice@example.com", name="Alice"):
    """Create a mock EntraAuthService that returns a given user."""
    from models.user import EntraTokenData

    svc = MagicMock()
    svc.verify_token = AsyncMock(return_value=EntraTokenData(oid=oid, email=email, name=name))
    return svc


def _mock_provisioning_service(user_id="user_abc123", email="alice@example.com"):
    """Create a mock UserProvisioningService that returns a User with given id."""
    from datetime import UTC, datetime

    from models.user import User

    now = datetime.now(UTC)
    svc = MagicMock()
    svc.ensure_user_exists.return_value = User(
        id=user_id,
        email=email,
        full_name="Test User",
        is_active=True,
        is_superuser=False,
        created_at=now,
        updated_at=now,
    )
    return svc


def _failing_entra_service():
    """Create a mock EntraAuthService that always raises."""
    svc = MagicMock()
    svc.verify_token = AsyncMock(side_effect=Exception("Invalid token"))
    return svc


# =============================================================================
# authenticate_websocket helper
# =============================================================================


class TestAuthenticateWebsocket:
    """Unit tests for the authenticate_websocket helper."""

    @pytest.fixture
    def mock_ws(self):
        ws = AsyncMock()
        ws.client = ("127.0.0.1", 9999)
        return ws

    @pytest.mark.asyncio
    async def test_returns_none_when_token_is_none(self, mock_ws):
        result = await authenticate_websocket(mock_ws, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_token_is_empty(self, mock_ws):
        result = await authenticate_websocket(mock_ws, "")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_user_dict_on_valid_token(self, mock_ws):
        mock_svc = _mock_entra_service(oid="entra-oid-123", email="alice@example.com")
        mock_prov = _mock_provisioning_service(
            user_id="internal-user-id", email="alice@example.com"
        )
        with (
            patch(
                "api.routes.websocket_routes.get_entra_auth_service",
                return_value=mock_svc,
            ),
            patch(
                "api.routes.websocket_routes.get_user_provisioning_service",
                return_value=mock_prov,
            ),
        ):
            result = await authenticate_websocket(mock_ws, "valid-entra-token")

        assert result is not None
        assert result["user_id"] == "internal-user-id"
        assert result["email"] == "alice@example.com"

    @pytest.mark.asyncio
    async def test_returns_none_on_invalid_token(self, mock_ws):
        mock_svc = _failing_entra_service()
        with patch(
            "api.routes.websocket_routes.get_entra_auth_service",
            return_value=mock_svc,
        ):
            result = await authenticate_websocket(mock_ws, "not-a-jwt")
        assert result is None


# =============================================================================
# /ws/jobs/{job_id} endpoint
# =============================================================================


def _patch_ws_auth(oid="user_test123", email="test@example.com"):
    """Patch authenticate_websocket to return a fixed user dict."""
    return patch(
        "api.routes.websocket_routes.authenticate_websocket",
        new_callable=AsyncMock,
        return_value={"user_id": oid, "email": email},
    )


def _patch_ws_auth_fail():
    """Patch authenticate_websocket to return None (auth failure)."""
    return patch(
        "api.routes.websocket_routes.authenticate_websocket",
        new_callable=AsyncMock,
        return_value=None,
    )


class TestWebSocketJobAuth:
    """Auth tests for the /ws/jobs/{job_id} endpoint."""

    @pytest.fixture
    def _reset_ws_manager(self):
        """Reset the global websocket manager singleton between tests."""
        import api.routes.websocket_manager as wm

        wm._manager = None
        yield
        wm._manager = None

    @pytest.mark.asyncio
    async def test_job_ws_rejects_without_token(self, client, _reset_ws_manager):
        """Connection without token should be closed with 4001."""
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/jobs/job-123") as ws:
            ws.receive_json()  # pragma: no cover

    @pytest.mark.asyncio
    async def test_job_ws_rejects_invalid_token(self, client, _reset_ws_manager):
        """Connection with a bad token should be closed with 4001."""
        with (
            _patch_ws_auth_fail(),
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect("/ws/jobs/job-123?token=bad-token") as ws,
        ):
            ws.receive_json()  # pragma: no cover

    @pytest.mark.asyncio
    async def test_job_ws_accepts_valid_token(self, client, _reset_ws_manager):
        """Connection with a valid token should succeed and receive 'connected' message."""
        with (
            _patch_ws_auth(),
            client.websocket_connect("/ws/jobs/job-123?token=mock-entra-token") as ws,
        ):
            data = ws.receive_json()
            assert data["type"] == "connected"
            assert data["payload"]["job_id"] == "job-123"


# =============================================================================
# /ws/user/{user_id} endpoint
# =============================================================================


class TestWebSocketUserAuth:
    """Auth tests for the /ws/user/{user_id} endpoint."""

    @pytest.fixture
    def _reset_ws_manager(self):
        import api.routes.websocket_manager as wm

        wm._manager = None
        yield
        wm._manager = None

    @pytest.mark.asyncio
    async def test_user_ws_rejects_without_token(self, client, _reset_ws_manager):
        """No token → 4001 close."""
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect("/ws/user/user_test123") as ws,
        ):
            ws.receive_json()  # pragma: no cover

    @pytest.mark.asyncio
    async def test_user_ws_rejects_wrong_user(self, client, _reset_ws_manager):
        """Token for user A but URL has user B → 4003 Forbidden close."""
        with (
            _patch_ws_auth(oid="user_alice", email="alice@example.com"),
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect("/ws/user/user_bob?token=mock-entra-token") as ws,
        ):
            ws.receive_json()  # pragma: no cover

    @pytest.mark.asyncio
    async def test_user_ws_accepts_matching_user(self, client, _reset_ws_manager):
        """Token user matches URL user → connected."""
        with (
            _patch_ws_auth(),
            client.websocket_connect("/ws/user/user_test123?token=mock-entra-token") as ws,
        ):
            data = ws.receive_json()
            assert data["type"] == "connected"
            assert data["payload"]["user_id"] == "user_test123"


# =============================================================================
# /ws/all endpoint (first-message auth)
# =============================================================================


class TestWebSocketAllAuth:
    """Auth tests for the /ws/all endpoint using first-message auth."""

    @pytest.fixture
    def _reset_ws_manager(self):
        import api.routes.websocket_manager as wm

        wm._manager = None
        yield
        wm._manager = None

    @pytest.mark.asyncio
    async def test_all_ws_rejects_no_auth_message(self, client, _reset_ws_manager):
        """Sending a non-auth first message should close with 4001."""
        with client.websocket_connect("/ws/all") as ws:
            ws.send_json({"type": "ping"})
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()

    @pytest.mark.asyncio
    async def test_all_ws_rejects_invalid_token(self, client, _reset_ws_manager):
        """Auth message with invalid JWT should close with 4001."""
        with _patch_ws_auth_fail(), client.websocket_connect("/ws/all") as ws:
            ws.send_json({"type": "auth", "token": "bad-token"})
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()

    @pytest.mark.asyncio
    async def test_all_ws_rejects_missing_token_field(self, client, _reset_ws_manager):
        """Auth message without 'token' field should close with 4001."""
        with client.websocket_connect("/ws/all") as ws:
            ws.send_json({"type": "auth"})
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()

    @pytest.mark.asyncio
    async def test_all_ws_rejects_malformed_json(self, client, _reset_ws_manager):
        """Non-JSON first message should close with 4001."""
        with client.websocket_connect("/ws/all") as ws:
            ws.send_text("this is not json")
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()

    @pytest.mark.asyncio
    async def test_all_ws_accepts_valid_auth(self, client, _reset_ws_manager):
        """Valid first-message auth should keep the connection alive."""
        with (
            _patch_ws_auth(oid="user_admin", email="admin@example.com"),
            client.websocket_connect("/ws/all") as ws,
        ):
            ws.send_json({"type": "auth", "token": "mock-entra-token"})
            data = ws.receive_json()
            assert data["type"] == "connected"
            assert data["payload"]["user_id"] == "user_admin"

    @pytest.mark.asyncio
    async def test_all_ws_ping_after_auth(self, client, _reset_ws_manager):
        """After auth, normal messages like ping should work."""
        with (
            _patch_ws_auth(oid="user_admin", email="admin@example.com"),
            client.websocket_connect("/ws/all") as ws,
        ):
            # Authenticate
            ws.send_json({"type": "auth", "token": "mock-entra-token"})
            connected = ws.receive_json()
            assert connected["type"] == "connected"

            # Send ping
            ws.send_json({"type": "ping"})
            pong = ws.receive_json()
            assert pong["type"] == "pong"
