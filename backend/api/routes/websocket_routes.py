"""
WebSocket Routes for QPrisma
WebSocket endpoints for real-time updates.

Endpoints:
    /ws/jobs/{job_id}  - Follow a specific job
    /ws/user/{user_id} - Receive updates for all jobs of a user
    /ws/all            - Receive all updates (admin/debug)

Message protocol:
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

Frontend usage:
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
    WebSocket for following a specific job.

    Receives real-time progress updates for the specified job.

    Connection example:
        ws://localhost:8000/ws/jobs/abc123
    """
    manager = get_websocket_manager()

    # Connect
    connected = await manager.connect(websocket, job_id=job_id)
    if not connected:
        return

    try:
        # Send current job status if it exists
        await _send_current_job_status(websocket, job_id)

        # Main loop
        while True:
            try:
                # Wait for client messages (with timeout for heartbeat)
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)  # 30 seconds

                # Process message
                await _handle_client_message(websocket, data, manager)

            except TimeoutError:
                # Send heartbeat
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
    WebSocket for receiving updates for all jobs of a user.

    Example:
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
    WebSocket for receiving all updates (admin/debug).

    Requires authentication token as a query parameter.
    Example:
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
    """Processes messages received from the client"""
    try:
        message = json.loads(data)
        msg_type = message.get("type", "")
        payload = message.get("payload", {})

        if msg_type == "ping":
            # Respond with pong
            await websocket.send_text(
                json.dumps({"type": "pong", "timestamp": asyncio.get_event_loop().time()})
            )

        elif msg_type == "subscribe":
            # Subscribe to an additional job
            job_id = payload.get("job_id")
            if job_id:
                await manager.subscribe_to_job(websocket, job_id)
                await websocket.send_text(
                    json.dumps({"type": "subscribed", "payload": {"job_id": job_id}})
                )

        elif msg_type == "unsubscribe":
            # Unsubscribe from a job
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
    """Sends the current job status upon connection"""
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
# REST Endpoints for WebSocket statistics
# =============================================================================


@router.get("/stats")
async def get_websocket_stats():
    """Gets WebSocket connection statistics"""
    manager = get_websocket_manager()
    return manager.get_stats()


@router.post("/broadcast")
async def broadcast_message(message: str, msg_type: str = "info"):
    """
    Sends a message to all connected clients.
    For administration/debug use only.
    """
    manager = get_websocket_manager()

    await manager.broadcast(
        WebSocketMessage(
            type=MessageType.JOB_PROGRESS,  # Use generic type
            payload={"message": message, "type": msg_type},
        )
    )

    stats = manager.get_stats()
    return {"sent_to": stats["total_connections"], "message": message}


# =============================================================================
# Helper functions for notifying from Celery tasks
# =============================================================================


async def notify_job_progress(job_id: str, progress: int, stage: str, message: str | None = None):
    """
    Helper function to notify progress from anywhere in the codebase.

    Usage from a Celery task:
        import asyncio
        from api.routes.websocket_routes import notify_job_progress

        asyncio.run(notify_job_progress(job_id, 50, "analyzing", "Processing frames"))
    """
    manager = get_websocket_manager()
    await manager.send_job_progress(job_id, progress, stage, message)


async def notify_job_completed(job_id: str, result: dict | None = None):
    """Notifies that a job has completed"""
    manager = get_websocket_manager()
    await manager.send_job_completed(job_id, result)


async def notify_job_failed(job_id: str, error: str):
    """Notifies that a job has failed"""
    manager = get_websocket_manager()
    await manager.send_job_failed(job_id, error)
