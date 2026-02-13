"""
Tests para el sistema WebSocket de QPrisma
"""

import json
from unittest.mock import AsyncMock

import pytest


class TestWebSocketManager:
    """Tests para el ConnectionManager"""

    @pytest.fixture
    def manager(self):
        from api.routes.websocket_manager import ConnectionManager

        return ConnectionManager()

    @pytest.fixture
    def mock_websocket(self):
        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.send_text = AsyncMock()
        ws.receive_text = AsyncMock()
        ws.close = AsyncMock()
        return ws

    @pytest.mark.asyncio
    async def test_connect(self, manager, mock_websocket):
        """Test conexión básica"""
        result = await manager.connect(mock_websocket, job_id="test-job-123")

        assert result is True
        assert mock_websocket in manager._active_connections
        assert "test-job-123" in manager._job_connections
        mock_websocket.accept.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect(self, manager, mock_websocket):
        """Test desconexión"""
        await manager.connect(mock_websocket, job_id="test-job")
        await manager.disconnect(mock_websocket)

        assert mock_websocket not in manager._active_connections
        assert "test-job" not in manager._job_connections

    @pytest.mark.asyncio
    async def test_send_to_job(self, manager, mock_websocket):
        """Test envío de mensaje a job"""
        from api.routes.websocket_manager import MessageType, WebSocketMessage

        await manager.connect(mock_websocket, job_id="job-123")

        message = WebSocketMessage(
            type=MessageType.JOB_PROGRESS, payload={"progress": 50, "stage": "analyzing"}
        )

        await manager.send_to_job("job-123", message)

        mock_websocket.send_text.assert_called()
        sent_data = json.loads(mock_websocket.send_text.call_args[0][0])
        assert sent_data["type"] == "job_progress"
        assert sent_data["payload"]["progress"] == 50

    @pytest.mark.asyncio
    async def test_send_job_progress(self, manager, mock_websocket):
        """Test helper de progreso"""
        await manager.connect(mock_websocket, job_id="job-456")

        await manager.send_job_progress(
            job_id="job-456", progress=75, stage="embedding", message="Generando embeddings..."
        )

        sent_data = json.loads(mock_websocket.send_text.call_args[0][0])
        assert sent_data["payload"]["progress"] == 75
        assert sent_data["payload"]["stage"] == "embedding"

    @pytest.mark.asyncio
    async def test_multiple_connections_same_job(self, manager):
        """Test múltiples clientes en el mismo job"""
        ws1 = AsyncMock()
        ws1.accept = AsyncMock()
        ws1.send_text = AsyncMock()

        ws2 = AsyncMock()
        ws2.accept = AsyncMock()
        ws2.send_text = AsyncMock()

        await manager.connect(ws1, job_id="shared-job")
        await manager.connect(ws2, job_id="shared-job")

        await manager.send_job_progress("shared-job", 50, "test")

        # Ambos deben recibir el mensaje
        ws1.send_text.assert_called()
        ws2.send_text.assert_called()

    @pytest.mark.asyncio
    async def test_stats(self, manager, mock_websocket):
        """Test estadísticas"""
        await manager.connect(mock_websocket, job_id="stats-job")

        stats = manager.get_stats()

        assert stats["total_connections"] == 1
        assert stats["jobs_with_connections"] == 1
        assert "stats-job" in stats["connections_by_job"]


class TestWebSocketMessage:
    """Tests para WebSocketMessage"""

    def test_to_json(self):
        from api.routes.websocket_manager import MessageType, WebSocketMessage

        msg = WebSocketMessage(
            type=MessageType.JOB_PROGRESS, payload={"progress": 25}, job_id="test-123"
        )

        json_str = msg.to_json()
        parsed = json.loads(json_str)

        assert parsed["type"] == "job_progress"
        assert parsed["payload"]["progress"] == 25
        assert parsed["job_id"] == "test-123"

    def test_from_json(self):
        from api.routes.websocket_manager import MessageType, WebSocketMessage

        json_str = json.dumps(
            {"type": "job_progress", "payload": {"progress": 50}, "job_id": "test"}
        )

        msg = WebSocketMessage.from_json(json_str)

        assert msg.type == MessageType.JOB_PROGRESS
        assert msg.payload["progress"] == 50
