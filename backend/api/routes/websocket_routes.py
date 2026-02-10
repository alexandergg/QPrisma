"""
WebSocket Routes para QPrisma
Endpoints WebSocket para actualizaciones en tiempo real.

Endpoints:
    /ws/jobs/{job_id}  - Seguir un job específico
    /ws/user/{user_id} - Recibir updates de todos los jobs del usuario
    /ws/all            - Recibir todos los updates (admin/debug)

Protocolo de mensajes:
    Client -> Server:
        {"type": "ping"}
        {"type": "subscribe", "payload": {"job_id": "xxx"}}
        {"type": "unsubscribe", "payload": {"job_id": "xxx"}}

    Server -> Client:
        {"type": "connected", "payload": {...}}
        {"type": "job_progress", "job_id": "xxx", "payload": {"progress": 50, "stage": "analyzing"}}
        {"type": "job_completed", "job_id": "xxx", "payload": {"result": {...}}}
        {"type": "job_failed", "job_id": "xxx", "payload": {"error": "..."}}
        {"type": "heartbeat", "payload": {"timestamp": "..."}}

Uso en frontend:
    const ws = new WebSocket('ws://localhost:8000/ws/jobs/my-job-id');

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'job_progress') {
            updateProgress(data.payload.progress);
        }
    };
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from api.routes.websocket_manager import (
    ConnectionManager,
    MessageType,
    WebSocketMessage,
    get_websocket_manager,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# WebSocket Endpoints
# =============================================================================


@router.websocket("/jobs/{job_id}")
async def websocket_job_endpoint(websocket: WebSocket, job_id: str):
    """
    WebSocket para seguir un job específico.

    Recibe actualizaciones de progreso en tiempo real para el job indicado.

    Ejemplo de conexión:
        ws://localhost:8000/ws/jobs/abc123
    """
    manager = get_websocket_manager()

    # Conectar
    connected = await manager.connect(websocket, job_id=job_id)
    if not connected:
        return

    try:
        # Enviar estado actual del job si existe
        await _send_current_job_status(websocket, job_id)

        # Loop principal
        while True:
            try:
                # Esperar mensajes del cliente (con timeout para heartbeat)
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)  # 30 segundos

                # Procesar mensaje
                await _handle_client_message(websocket, data, manager)

            except TimeoutError:
                # Enviar heartbeat
                await manager.send_heartbeat(websocket)

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for job {job_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await manager.disconnect(websocket)


@router.websocket("/user/{user_id}")
async def websocket_user_endpoint(websocket: WebSocket, user_id: str):
    """
    WebSocket para recibir updates de todos los jobs de un usuario.

    Ejemplo:
        ws://localhost:8000/ws/user/user123
    """
    manager = get_websocket_manager()

    connected = await manager.connect(websocket, user_id=user_id)
    if not connected:
        return

    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                await _handle_client_message(websocket, data, manager)

            except TimeoutError:
                await manager.send_heartbeat(websocket)

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for user {user_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await manager.disconnect(websocket)


@router.websocket("/all")
async def websocket_all_endpoint(websocket: WebSocket, token: str | None = Query(None)):
    """
    WebSocket para recibir todos los updates (admin/debug).

    Requiere token de autenticación en query param.
    Ejemplo:
        ws://localhost:8000/ws/all?token=admin-token
    """
    # Admin token validation is deferred (see P0 auth task for endpoint auth)
    # Future: validate_admin_token(token) and close with 4001 if unauthorized

    manager = get_websocket_manager()

    connected = await manager.connect(websocket)
    if not connected:
        return

    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                await _handle_client_message(websocket, data, manager)

            except TimeoutError:
                await manager.send_heartbeat(websocket)

    except WebSocketDisconnect:
        logger.info("Admin WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await manager.disconnect(websocket)


# =============================================================================
# Helpers
# =============================================================================


async def _handle_client_message(websocket: WebSocket, data: str, manager: ConnectionManager):
    """Procesa mensajes recibidos del cliente"""
    try:
        message = json.loads(data)
        msg_type = message.get("type", "")
        payload = message.get("payload", {})

        if msg_type == "ping":
            # Responder con pong
            await websocket.send_text(
                json.dumps({"type": "pong", "timestamp": asyncio.get_event_loop().time()})
            )

        elif msg_type == "subscribe":
            # Suscribirse a un job adicional
            job_id = payload.get("job_id")
            if job_id:
                await manager.subscribe_to_job(websocket, job_id)
                await websocket.send_text(
                    json.dumps({"type": "subscribed", "payload": {"job_id": job_id}})
                )

        elif msg_type == "unsubscribe":
            # Desuscribirse de un job
            job_id = payload.get("job_id")
            if job_id:
                await manager.unsubscribe_from_job(websocket, job_id)
                await websocket.send_text(
                    json.dumps({"type": "unsubscribed", "payload": {"job_id": job_id}})
                )

        else:
            logger.debug(f"Unknown message type: {msg_type}")

    except json.JSONDecodeError:
        logger.warning(f"Invalid JSON received: {data}")
    except Exception as e:
        logger.error(f"Error handling client message: {e}")


async def _send_current_job_status(websocket: WebSocket, job_id: str):
    """Envía el estado actual del job al conectarse"""
    try:
        import os

        import redis.asyncio as aioredis

        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        redis_client = aioredis.from_url(redis_url)

        cache_key = f"job_status:{job_id}"
        status_json = await redis_client.get(cache_key)

        await redis_client.close()

        if status_json:
            status = json.loads(status_json)
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "job_progress",
                        "job_id": job_id,
                        "payload": {
                            "progress": status.get("progress", 0),
                            "stage": status.get("stage", "unknown"),
                            "message": status.get("message"),
                            "status": status.get("status", "unknown"),
                        },
                    }
                )
            )
    except Exception as e:
        logger.warning(f"Could not send current job status: {e}")


# =============================================================================
# REST Endpoints para estadísticas de WebSocket
# =============================================================================


@router.get("/stats")
async def get_websocket_stats():
    """Obtiene estadísticas de conexiones WebSocket"""
    manager = get_websocket_manager()
    return manager.get_stats()


@router.post("/broadcast")
async def broadcast_message(message: str, msg_type: str = "info"):
    """
    Envía un mensaje a todos los clientes conectados.
    Solo para administración/debug.
    """
    manager = get_websocket_manager()

    await manager.broadcast(
        WebSocketMessage(
            type=MessageType.JOB_PROGRESS,  # Usar tipo genérico
            payload={"message": message, "type": msg_type},
        )
    )

    stats = manager.get_stats()
    return {"sent_to": stats["total_connections"], "message": message}


# =============================================================================
# Función para notificar desde Celery tasks
# =============================================================================


async def notify_job_progress(job_id: str, progress: int, stage: str, message: str | None = None):
    """
    Función helper para notificar progreso desde cualquier parte del código.

    Uso desde Celery task:
        import asyncio
        from api.routes.websocket_routes import notify_job_progress

        asyncio.run(notify_job_progress(job_id, 50, "analyzing", "Procesando frames"))
    """
    manager = get_websocket_manager()
    await manager.send_job_progress(job_id, progress, stage, message)


async def notify_job_completed(job_id: str, result: dict | None = None):
    """Notifica que un job se completó"""
    manager = get_websocket_manager()
    await manager.send_job_completed(job_id, result)


async def notify_job_failed(job_id: str, error: str):
    """Notifica que un job falló"""
    manager = get_websocket_manager()
    await manager.send_job_failed(job_id, error)
