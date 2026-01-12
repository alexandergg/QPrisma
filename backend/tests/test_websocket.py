"""
Tests para el sistema WebSocket de QPrisma

Ejecutar:
    cd backend
    python -m pytest tests/test_websocket.py -v

    # Test interactivo
    python tests/test_websocket.py --interactive
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
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
        print("✓ Conexión WebSocket funciona")

    @pytest.mark.asyncio
    async def test_disconnect(self, manager, mock_websocket):
        """Test desconexión"""
        await manager.connect(mock_websocket, job_id="test-job")
        await manager.disconnect(mock_websocket)

        assert mock_websocket not in manager._active_connections
        assert "test-job" not in manager._job_connections
        print("✓ Desconexión WebSocket funciona")

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
        print("✓ Envío a job funciona")

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
        print("✓ Helper send_job_progress funciona")

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
        print("✓ Múltiples clientes en mismo job funciona")

    @pytest.mark.asyncio
    async def test_stats(self, manager, mock_websocket):
        """Test estadísticas"""
        await manager.connect(mock_websocket, job_id="stats-job")

        stats = manager.get_stats()

        assert stats["total_connections"] == 1
        assert stats["jobs_with_connections"] == 1
        assert "stats-job" in stats["connections_by_job"]
        print("✓ Estadísticas funcionan")


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
        print("✓ WebSocketMessage serialización funciona")

    def test_from_json(self):
        from api.routes.websocket_manager import MessageType, WebSocketMessage

        json_str = json.dumps(
            {"type": "job_progress", "payload": {"progress": 50}, "job_id": "test"}
        )

        msg = WebSocketMessage.from_json(json_str)

        assert msg.type == MessageType.JOB_PROGRESS
        assert msg.payload["progress"] == 50
        print("✓ WebSocketMessage deserialización funciona")


# =============================================================================
# Test Interactivo
# =============================================================================


async def interactive_test():
    """Test interactivo del WebSocket"""
    import websockets

    print("\n" + "=" * 60)
    print("QPrisma WebSocket Interactive Test")
    print("=" * 60)
    print("\nEste test requiere:")
    print("  - API corriendo (python api/main.py)")
    print("  - Redis corriendo (docker-compose up -d redis)")
    print()

    job_id = input("Ingresa un job_id para monitorear (o Enter para 'test-job'): ").strip()
    if not job_id:
        job_id = "test-job"

    ws_url = f"ws://localhost:8000/ws/jobs/{job_id}"
    print(f"\nConectando a {ws_url}...")

    try:
        async with websockets.connect(ws_url) as ws:
            print("✓ Conectado!")
            print("\nEsperando mensajes (Ctrl+C para salir)...\n")

            while True:
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=35)
                    data = json.loads(message)

                    print(f"[{data.get('type', 'unknown')}]", end=" ")

                    if data["type"] == "job_progress":
                        payload = data["payload"]
                        print(
                            f"Progress: {payload.get('progress', 0)}% - {payload.get('stage', '')}"
                        )
                        if payload.get("message"):
                            print(f"  Message: {payload['message']}")
                    elif data["type"] == "job_completed":
                        print("Job completado!")
                        break
                    elif data["type"] == "job_failed":
                        print(f"Job fallido: {data['payload'].get('error')}")
                        break
                    elif data["type"] == "heartbeat":
                        print("(heartbeat)")
                    elif data["type"] == "connected":
                        print("Conexión confirmada")
                    else:
                        print(json.dumps(data, indent=2))

                except TimeoutError:
                    # Enviar ping
                    await ws.send(json.dumps({"type": "ping"}))
                    print("[ping enviado]")

    except ConnectionRefusedError:
        print("\n✗ Error: No se pudo conectar al servidor")
        print("  Asegúrate de que la API está corriendo en localhost:8000")
    except KeyboardInterrupt:
        print("\n\nTest interrumpido por usuario")
    except Exception as e:
        print(f"\n✗ Error: {e}")


async def simulate_progress():
    """Simula progreso de un job para testing"""
    print("\n" + "=" * 60)
    print("Simulador de Progreso de Job")
    print("=" * 60)

    job_id = input("\nIngresa job_id a simular (o Enter para 'test-job'): ").strip()
    if not job_id:
        job_id = "test-job"

    print(f"\nSimulando progreso para job: {job_id}")
    print("Conecta un cliente WebSocket a ws://localhost:8000/ws/jobs/{job_id}")
    print("para ver las actualizaciones.\n")

    # Importar el manager
    from api.routes.websocket_manager import get_websocket_manager

    manager = get_websocket_manager()

    stages = [
        (10, "downloading", "Descargando video..."),
        (25, "extracting", "Extrayendo frames..."),
        (40, "analyzing", "Analizando con GPT-4V..."),
        (60, "analyzing", "Analizando frames 10/20..."),
        (75, "embedding", "Generando embeddings..."),
        (85, "transcribing", "Transcribiendo audio..."),
        (90, "indexing", "Indexando en Knowledge Graph..."),
        (100, "completed", "Procesamiento completado"),
    ]

    for progress, stage, message in stages:
        print(f"  [{progress:3d}%] {stage}: {message}")
        await manager.send_job_progress(job_id, progress, stage, message)
        await asyncio.sleep(1)

    await manager.send_job_completed(job_id, {"frames_processed": 20})
    print("\n✓ Simulación completada")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test WebSocket para QPrisma")
    parser.add_argument("--interactive", "-i", action="store_true", help="Test interactivo")
    parser.add_argument("--simulate", "-s", action="store_true", help="Simular progreso")

    args = parser.parse_args()

    if args.interactive:
        asyncio.run(interactive_test())
    elif args.simulate:
        asyncio.run(simulate_progress())
    else:
        print("Uso: python test_websocket.py [--interactive | --simulate]")
        print()
        print("  --interactive  Conectar a WebSocket y mostrar mensajes")
        print("  --simulate     Simular progreso de un job")
        print()
        print("Para tests unitarios: pytest tests/test_websocket.py -v")

