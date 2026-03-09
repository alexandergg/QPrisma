"""
WebSocket Routes for QPrisma
WebSocket endpoints for real-time updates.

Endpoints:
    /ws/jobs/{job_id}  - Follow a specific job (requires JWT token query param)
    /ws/user/{user_id} - Receive updates for all jobs of a user (requires JWT; user must match)
    /ws/all            - Receive all updates (admin/debug; first-message auth)

Message protocol:
    Client -> Server:
        {"type": "auth", "token": "jwt-token"}   (only for /ws/all, must be first message)
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
    // Job endpoint (token in query param)
    const ws = new WebSocket('ws://localhost:8000/ws/jobs/my-job-id?token=eyJ...');

    // All-updates endpoint (first-message auth)
    const ws = new WebSocket('ws://localhost:8000/ws/all');
    ws.onopen = () => ws.send(JSON.stringify({type: "auth", token: "eyJ..."}));

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
from datetime import UTC, datetime

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from api.dependencies import get_auth_service
from api.routes.websocket_manager import (
    ConnectionManager,
    MessageType,
    WebSocketMessage,
    get_websocket_manager,
)
from models.user import TokenData

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# WebSocket Authentication Helper
# =============================================================================


async def authenticate_websocket(websocket: WebSocket, token: str | None) -> dict | None:
    """
    Verify a JWT token for WebSocket authentication.

    Args:
        websocket: The WebSocket connection (used for logging context).
        token: JWT access token string, or None.

    Returns:
        A dict with ``user_id`` and ``email`` on success, or ``None`` on
        failure.  Callers are responsible for closing the socket on ``None``.
    """
    if not token:
        logger.warning(
            "WebSocket auth failed: no token provided (client=%s)",
            websocket.client,
        )
        return None

    try:
        auth_service = get_auth_service()
        token_data: TokenData = await auth_service.verify_token(token)
        return {"user_id": token_data.user_id, "email": token_data.email}
    except Exception:
        logger.warning(
            "WebSocket auth failed: invalid or expired token (client=%s)",
            websocket.client,
        )
        return None


# =============================================================================
# WebSocket Endpoints
# =============================================================================


@router.websocket("/jobs/{job_id}")
async def websocket_job_endpoint(
    websocket: WebSocket, job_id: str, token: str | None = Query(None)
):
    """
    WebSocket for following a specific job.

    Receives real-time progress updates for the specified job.
    Requires a valid JWT token as a query parameter.

    Connection example:
        ws://localhost:8000/ws/jobs/abc123?token=eyJ...
    """
    # --- Authentication ---
    user = await authenticate_websocket(websocket, token)
    if user is None:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    manager = get_websocket_manager()

    # Connect
    connected = await manager.connect(websocket, job_id=job_id)
    if not connected:
        return

    logger.info("Authenticated WebSocket for job %s (user=%s)", job_id, user["user_id"])

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
async def websocket_user_endpoint(
    websocket: WebSocket, user_id: str, token: str | None = Query(None)
):
    """
    WebSocket for receiving updates for all jobs of a user.
    Requires a valid JWT token whose subject matches user_id.

    Example:
        ws://localhost:8000/ws/user/user123?token=eyJ...
    """
    # --- Authentication ---
    user = await authenticate_websocket(websocket, token)
    if user is None:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    # --- Authorization: token user must match requested user_id ---
    if user["user_id"] != user_id:
        logger.warning(
            "WebSocket forbidden: token user %s tried to subscribe to user %s (client=%s)",
            user["user_id"],
            user_id,
            websocket.client,
        )
        await websocket.close(code=4003, reason="Forbidden")
        return

    manager = get_websocket_manager()

    connected = await manager.connect(websocket, user_id=user_id)
    if not connected:
        return

    logger.info("Authenticated WebSocket for user %s", user_id)

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
async def websocket_all_endpoint(websocket: WebSocket):
    """
    WebSocket for receiving all updates (admin/debug).

    Uses first-message authentication: after connecting, the client must
    immediately send ``{"type": "auth", "token": "eyJ..."}``.  The server
    validates the JWT and either keeps the connection alive or closes it
    with code 4001.

    Example:
        const ws = new WebSocket('ws://localhost:8000/ws/all');
        ws.onopen = () => ws.send(JSON.stringify({type: "auth", token: "eyJ..."}));
    """
    # Accept the raw connection first (first-message auth pattern)
    await websocket.accept()

    # --- First-message authentication ---
    try:
        # Give the client a reasonable window to send the auth message
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
        auth_msg = json.loads(raw)

        if auth_msg.get("type") != "auth" or not auth_msg.get("token"):
            logger.warning(
                "WebSocket /ws/all auth failed: invalid auth message format (client=%s)",
                websocket.client,
            )
            await websocket.close(code=4001, reason="Unauthorized")
            return

        user = await authenticate_websocket(websocket, auth_msg["token"])
        if user is None:
            await websocket.close(code=4001, reason="Unauthorized")
            return

    except TimeoutError:
        logger.warning(
            "WebSocket /ws/all auth failed: auth timeout (client=%s)",
            websocket.client,
        )
        await websocket.close(code=4001, reason="Unauthorized")
        return
    except (json.JSONDecodeError, Exception) as exc:
        logger.warning(
            "WebSocket /ws/all auth failed: %s (client=%s)",
            exc,
            websocket.client,
        )
        await websocket.close(code=4001, reason="Unauthorized")
        return

    # Auth succeeded — register with the manager (connection already accepted)
    manager = get_websocket_manager()

    # Manually register since we already accepted the connection above
    async with manager._lock:
        manager._active_connections.add(websocket)
        manager._connection_metadata[websocket] = {
            "job_id": None,
            "user_id": user["user_id"],
            "connected_at": datetime.now(UTC).isoformat(),
        }

    # Send connected confirmation
    await websocket.send_text(
        json.dumps(
            {
                "type": "connected",
                "payload": {
                    "message": "Authenticated successfully",
                    "user_id": user["user_id"],
                },
            }
        )
    )

    logger.info("Authenticated WebSocket for /ws/all (user=%s)", user["user_id"])

    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                await _handle_client_message(websocket, data, manager)

            except TimeoutError:
                await manager.send_heartbeat(websocket)

    except WebSocketDisconnect:
        logger.info("Admin WebSocket disconnected (user=%s)", user["user_id"])
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
        import redis.asyncio as aioredis

        from core.config import settings

        redis_url = settings.redis.url
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
