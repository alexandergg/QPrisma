"""
WebSocket Manager for QPrisma
Manages WebSocket connections for real-time updates.

Features:
- Connections by job_id (follow a specific job)
- Connections by user_id (all jobs for a user)
- Broadcast to all clients
- Heartbeat to keep connections alive
- Automatic reconnection on the client side

Usage:
    # On the server
    manager = WebSocketManager()

    @app.websocket("/ws/jobs/{job_id}")
    async def websocket_endpoint(websocket: WebSocket, job_id: str):
        await manager.connect(websocket, job_id)
        try:
            while True:
                data = await websocket.receive_text()
                # Process client messages if necessary
        except WebSocketDisconnect:
            manager.disconnect(websocket, job_id)

    # From a background processor or status bridge
    await manager.send_job_update(job_id, {
        "progress": 50,
        "stage": "analyzing"
    })
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class MessageType(str, Enum):
    """WebSocket message types"""

    # Server -> Client
    JOB_PROGRESS = "job_progress"
    JOB_COMPLETED = "job_completed"
    JOB_FAILED = "job_failed"
    JOB_CANCELLED = "job_cancelled"
    HEARTBEAT = "heartbeat"
    ERROR = "error"
    CONNECTED = "connected"

    # Client -> Server
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    PING = "ping"


@dataclass
class WebSocketMessage:
    """WebSocket message structure"""

    type: MessageType
    payload: dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    job_id: str | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "type": self.type.value,
                "payload": self.payload,
                "timestamp": self.timestamp,
                "job_id": self.job_id,
            }
        )

    @classmethod
    def from_json(cls, data: str) -> "WebSocketMessage":
        parsed = json.loads(data)
        return cls(
            type=MessageType(parsed.get("type", "error")),
            payload=parsed.get("payload", {}),
            timestamp=parsed.get("timestamp", datetime.now(UTC).isoformat()),
            job_id=parsed.get("job_id"),
        )


class ConnectionManager:
    """
    WebSocket connection manager.

    Maintains a registry of active connections organized by:
    - job_id: To follow a specific job
    - user_id: To receive updates for all jobs of a user
    - broadcast: For global messages
    """

    def __init__(self):
        # job_id -> set of websockets
        self._job_connections: dict[str, set[WebSocket]] = {}

        # user_id -> set of websockets
        self._user_connections: dict[str, set[WebSocket]] = {}

        # All active connections
        self._active_connections: set[WebSocket] = set()

        # WebSocket -> metadata
        self._connection_metadata: dict[WebSocket, dict[str, Any]] = {}

        # Lock for thread-safe operations
        self._lock = asyncio.Lock()

    async def connect(
        self, websocket: WebSocket, job_id: str | None = None, user_id: str | None = None
    ) -> bool:
        """
        Accepts a new WebSocket connection.

        Args:
            websocket: The WebSocket connection
            job_id: ID of the job to follow (optional)
            user_id: ID of the user (optional)

        Returns:
            True if the connection was accepted
        """
        try:
            await websocket.accept()

            async with self._lock:
                self._active_connections.add(websocket)

                # Store metadata
                self._connection_metadata[websocket] = {
                    "job_id": job_id,
                    "user_id": user_id,
                    "connected_at": datetime.now(UTC).isoformat(),
                }

                # Register in job_connections
                if job_id:
                    if job_id not in self._job_connections:
                        self._job_connections[job_id] = set()
                    self._job_connections[job_id].add(websocket)

                # Register in user_connections
                if user_id:
                    if user_id not in self._user_connections:
                        self._user_connections[user_id] = set()
                    self._user_connections[user_id].add(websocket)

            # Send confirmation
            await self._send_message(
                websocket,
                WebSocketMessage(
                    type=MessageType.CONNECTED,
                    payload={
                        "message": "Connected successfully",
                        "job_id": job_id,
                        "user_id": user_id,
                    },
                    job_id=job_id,
                ),
            )

            logger.info(f"WebSocket connected: job={job_id}, user={user_id}")
            return True

        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            return False

    async def disconnect(self, websocket: WebSocket):
        """Disconnects a WebSocket and cleans up its registry entries"""
        async with self._lock:
            # Get metadata
            metadata = self._connection_metadata.pop(websocket, {})
            job_id = metadata.get("job_id")
            user_id = metadata.get("user_id")

            # Remove from active_connections
            self._active_connections.discard(websocket)

            # Remove from job_connections
            if job_id and job_id in self._job_connections:
                self._job_connections[job_id].discard(websocket)
                if not self._job_connections[job_id]:
                    del self._job_connections[job_id]

            # Remove from user_connections
            if user_id and user_id in self._user_connections:
                self._user_connections[user_id].discard(websocket)
                if not self._user_connections[user_id]:
                    del self._user_connections[user_id]

        logger.info(f"WebSocket disconnected: job={job_id}, user={user_id}")

    async def subscribe_to_job(self, websocket: WebSocket, job_id: str):
        """Subscribes a WebSocket to a specific job"""
        async with self._lock:
            if job_id not in self._job_connections:
                self._job_connections[job_id] = set()
            self._job_connections[job_id].add(websocket)

            # Update metadata
            if websocket in self._connection_metadata:
                self._connection_metadata[websocket]["job_id"] = job_id

        logger.debug(f"WebSocket subscribed to job {job_id}")

    async def unsubscribe_from_job(self, websocket: WebSocket, job_id: str):
        """Unsubscribes a WebSocket from a job"""
        async with self._lock:
            if job_id in self._job_connections:
                self._job_connections[job_id].discard(websocket)

    async def _send_message(self, websocket: WebSocket, message: WebSocketMessage):
        """Sends a message to a specific WebSocket"""
        try:
            await websocket.send_text(message.to_json())
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            await self.disconnect(websocket)

    async def send_to_job(self, job_id: str, message: WebSocketMessage):
        """
        Sends a message to all clients subscribed to a job.

        Args:
            job_id: ID of the job
            message: Message to send
        """
        message.job_id = job_id

        connections = self._job_connections.get(job_id, set()).copy()
        if not connections:
            logger.debug(f"No WebSocket connections for job {job_id}")
            return

        # Send to all connections
        disconnected = []
        for websocket in connections:
            try:
                await websocket.send_text(message.to_json())
            except Exception as e:
                logger.warning(f"Failed to send to websocket: {e}")
                disconnected.append(websocket)

        # Clean up dead connections
        for ws in disconnected:
            await self.disconnect(ws)

        logger.debug(
            f"Sent message to {len(connections) - len(disconnected)} clients for job {job_id}"
        )

    async def send_to_user(self, user_id: str, message: WebSocketMessage):
        """Sends a message to all WebSockets for a user"""
        connections = self._user_connections.get(user_id, set()).copy()

        disconnected = []
        for websocket in connections:
            try:
                await websocket.send_text(message.to_json())
            except Exception:
                disconnected.append(websocket)

        for ws in disconnected:
            await self.disconnect(ws)

    async def broadcast(self, message: WebSocketMessage):
        """Sends a message to all active connections"""
        connections = self._active_connections.copy()

        disconnected = []
        for websocket in connections:
            try:
                await websocket.send_text(message.to_json())
            except Exception:
                disconnected.append(websocket)

        for ws in disconnected:
            await self.disconnect(ws)

        logger.debug(f"Broadcast sent to {len(connections) - len(disconnected)} clients")

    # =========================================================================
    # Convenience methods for common events
    # =========================================================================

    async def send_job_progress(
        self,
        job_id: str,
        progress: int,
        stage: str,
        message: str | None = None,
        data: dict | None = None,
    ):
        """Sends a progress update for a job"""
        payload = {
            "progress": progress,
            "stage": stage,
            "message": message or f"Processing: {stage}",
        }
        if data:
            payload["data"] = data

        await self.send_to_job(
            job_id, WebSocketMessage(type=MessageType.JOB_PROGRESS, payload=payload, job_id=job_id)
        )

    async def send_job_completed(self, job_id: str, result: dict | None = None):
        """Notifies that a job has completed"""
        await self.send_to_job(
            job_id,
            WebSocketMessage(
                type=MessageType.JOB_COMPLETED,
                payload={"message": "Processing completed", "result": result},
                job_id=job_id,
            ),
        )

    async def send_job_failed(self, job_id: str, error: str):
        """Notifies that a job has failed"""
        await self.send_to_job(
            job_id,
            WebSocketMessage(
                type=MessageType.JOB_FAILED,
                payload={"message": "Processing failed", "error": error},
                job_id=job_id,
            ),
        )

    async def send_heartbeat(self, websocket: WebSocket):
        """Sends a heartbeat to a client"""
        await self._send_message(
            websocket,
            WebSocketMessage(
                type=MessageType.HEARTBEAT, payload={"timestamp": datetime.now(UTC).isoformat()}
            ),
        )

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> dict[str, Any]:
        """Returns connection statistics"""
        return {
            "total_connections": len(self._active_connections),
            "jobs_with_connections": len(self._job_connections),
            "users_with_connections": len(self._user_connections),
            "connections_by_job": {
                job_id: len(conns) for job_id, conns in self._job_connections.items()
            },
        }


# =============================================================================
# Global singleton
# =============================================================================

_manager: ConnectionManager | None = None


def get_websocket_manager() -> ConnectionManager:
    """Gets the singleton instance of the WebSocket manager"""
    global _manager
    if _manager is None:
        _manager = ConnectionManager()
    return _manager


# =============================================================================
# Redis Pub/Sub integration (for multiple API instances)
# =============================================================================


class RedisPubSubManager:
    """
    Manager that uses Redis Pub/Sub to synchronize WebSockets
    across multiple API instances.

    Useful when there are multiple backend replicas and a client
    may be connected to a different instance than the one publishing
    processing status updates.
    """

    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self._pubsub = None
        self._local_manager = get_websocket_manager()
        self._running = False

    async def connect(self):
        """Connects to Redis Pub/Sub"""
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(self.redis_url)
            self._pubsub = self._redis.pubsub()
            await self._pubsub.subscribe("qprisma:websocket:events")
            self._running = True
            logger.info("Redis Pub/Sub connected for WebSocket sync")
        except Exception as e:
            logger.warning(f"Redis Pub/Sub not available: {e}")

    async def disconnect(self):
        """Disconnects from Redis Pub/Sub"""
        self._running = False
        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.close()
        if hasattr(self, "_redis"):
            await self._redis.close()

    async def publish_event(self, event_type: str, job_id: str, data: dict):
        """Publishes an event to Redis for other instances to receive"""
        if not hasattr(self, "_redis"):
            # Fallback to local manager
            await self._handle_event(event_type, job_id, data)
            return

        try:
            message = json.dumps({"type": event_type, "job_id": job_id, "data": data})
            await self._redis.publish("qprisma:websocket:events", message)
        except Exception as e:
            logger.error(f"Failed to publish event: {e}")
            # Fallback to local
            await self._handle_event(event_type, job_id, data)

    async def _handle_event(self, event_type: str, job_id: str, data: dict):
        """Handles an event (local or received from Redis)"""
        if event_type == "progress":
            await self._local_manager.send_job_progress(
                job_id, data.get("progress", 0), data.get("stage", "unknown"), data.get("message")
            )
        elif event_type == "completed":
            await self._local_manager.send_job_completed(job_id, data.get("result"))
        elif event_type == "failed":
            await self._local_manager.send_job_failed(job_id, data.get("error", "Unknown error"))

    async def listen(self):
        """Listens for Redis events and propagates them to local WebSockets"""
        if not self._pubsub:
            return

        while self._running:
            try:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message and message["type"] == "message":
                    data = json.loads(message["data"])
                    await self._handle_event(data["type"], data["job_id"], data["data"])
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in Redis listener: {e}")
                await asyncio.sleep(1)


# Singleton for Redis Pub/Sub
_pubsub_manager: RedisPubSubManager | None = None


async def get_pubsub_manager() -> RedisPubSubManager:
    """Gets the Redis Pub/Sub manager"""
    global _pubsub_manager
    if _pubsub_manager is None:
        from core.config import settings

        redis_url = settings.redis.url
        _pubsub_manager = RedisPubSubManager(redis_url)
        await _pubsub_manager.connect()
    return _pubsub_manager
