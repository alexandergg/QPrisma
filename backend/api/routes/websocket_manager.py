"""
WebSocket Manager para QPrisma
Gestiona conexiones WebSocket para actualizaciones en tiempo real.

Características:
- Conexiones por job_id (seguir un job específico)
- Conexiones por user_id (todos los jobs de un usuario)
- Broadcast a todos los clientes
- Heartbeat para mantener conexiones vivas
- Reconexión automática en cliente

Uso:
    # En el servidor
    manager = WebSocketManager()

    @app.websocket("/ws/jobs/{job_id}")
    async def websocket_endpoint(websocket: WebSocket, job_id: str):
        await manager.connect(websocket, job_id)
        try:
            while True:
                data = await websocket.receive_text()
                # Procesar mensajes del cliente si es necesario
        except WebSocketDisconnect:
            manager.disconnect(websocket, job_id)

    # Desde Celery task
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
    """Tipos de mensajes WebSocket"""

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
    """Estructura de mensaje WebSocket"""

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
    Gestor de conexiones WebSocket.

    Mantiene un registro de conexiones activas organizadas por:
    - job_id: Para seguir un job específico
    - user_id: Para recibir updates de todos los jobs del usuario
    - broadcast: Para mensajes globales
    """

    def __init__(self):
        # job_id -> set of websockets
        self._job_connections: dict[str, set[WebSocket]] = {}

        # user_id -> set of websockets
        self._user_connections: dict[str, set[WebSocket]] = {}

        # Todas las conexiones activas
        self._active_connections: set[WebSocket] = set()

        # WebSocket -> metadata
        self._connection_metadata: dict[WebSocket, dict[str, Any]] = {}

        # Lock para operaciones thread-safe
        self._lock = asyncio.Lock()

    async def connect(
        self, websocket: WebSocket, job_id: str | None = None, user_id: str | None = None
    ) -> bool:
        """
        Acepta una nueva conexión WebSocket.

        Args:
            websocket: La conexión WebSocket
            job_id: ID del job a seguir (opcional)
            user_id: ID del usuario (opcional)

        Returns:
            True si la conexión fue aceptada
        """
        try:
            await websocket.accept()

            async with self._lock:
                self._active_connections.add(websocket)

                # Guardar metadata
                self._connection_metadata[websocket] = {
                    "job_id": job_id,
                    "user_id": user_id,
                    "connected_at": datetime.now(UTC).isoformat(),
                }

                # Registrar en job_connections
                if job_id:
                    if job_id not in self._job_connections:
                        self._job_connections[job_id] = set()
                    self._job_connections[job_id].add(websocket)

                # Registrar en user_connections
                if user_id:
                    if user_id not in self._user_connections:
                        self._user_connections[user_id] = set()
                    self._user_connections[user_id].add(websocket)

            # Enviar confirmación
            await self._send_message(
                websocket,
                WebSocketMessage(
                    type=MessageType.CONNECTED,
                    payload={
                        "message": "Conectado correctamente",
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
        """Desconecta un WebSocket y limpia registros"""
        async with self._lock:
            # Obtener metadata
            metadata = self._connection_metadata.pop(websocket, {})
            job_id = metadata.get("job_id")
            user_id = metadata.get("user_id")

            # Remover de active_connections
            self._active_connections.discard(websocket)

            # Remover de job_connections
            if job_id and job_id in self._job_connections:
                self._job_connections[job_id].discard(websocket)
                if not self._job_connections[job_id]:
                    del self._job_connections[job_id]

            # Remover de user_connections
            if user_id and user_id in self._user_connections:
                self._user_connections[user_id].discard(websocket)
                if not self._user_connections[user_id]:
                    del self._user_connections[user_id]

        logger.info(f"WebSocket disconnected: job={job_id}, user={user_id}")

    async def subscribe_to_job(self, websocket: WebSocket, job_id: str):
        """Suscribe un WebSocket a un job específico"""
        async with self._lock:
            if job_id not in self._job_connections:
                self._job_connections[job_id] = set()
            self._job_connections[job_id].add(websocket)

            # Actualizar metadata
            if websocket in self._connection_metadata:
                self._connection_metadata[websocket]["job_id"] = job_id

        logger.debug(f"WebSocket subscribed to job {job_id}")

    async def unsubscribe_from_job(self, websocket: WebSocket, job_id: str):
        """Desuscribe un WebSocket de un job"""
        async with self._lock:
            if job_id in self._job_connections:
                self._job_connections[job_id].discard(websocket)

    async def _send_message(self, websocket: WebSocket, message: WebSocketMessage):
        """Envía un mensaje a un WebSocket específico"""
        try:
            await websocket.send_text(message.to_json())
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            await self.disconnect(websocket)

    async def send_to_job(self, job_id: str, message: WebSocketMessage):
        """
        Envía un mensaje a todos los clientes suscritos a un job.

        Args:
            job_id: ID del job
            message: Mensaje a enviar
        """
        message.job_id = job_id

        connections = self._job_connections.get(job_id, set()).copy()
        if not connections:
            logger.debug(f"No WebSocket connections for job {job_id}")
            return

        # Enviar a todas las conexiones
        disconnected = []
        for websocket in connections:
            try:
                await websocket.send_text(message.to_json())
            except Exception as e:
                logger.warning(f"Failed to send to websocket: {e}")
                disconnected.append(websocket)

        # Limpiar conexiones muertas
        for ws in disconnected:
            await self.disconnect(ws)

        logger.debug(
            f"Sent message to {len(connections) - len(disconnected)} clients for job {job_id}"
        )

    async def send_to_user(self, user_id: str, message: WebSocketMessage):
        """Envía un mensaje a todos los WebSockets de un usuario"""
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
        """Envía un mensaje a todas las conexiones activas"""
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
    # Métodos de conveniencia para eventos comunes
    # =========================================================================

    async def send_job_progress(
        self,
        job_id: str,
        progress: int,
        stage: str,
        message: str | None = None,
        data: dict | None = None,
    ):
        """Envía actualización de progreso de un job"""
        payload = {
            "progress": progress,
            "stage": stage,
            "message": message or f"Procesando: {stage}",
        }
        if data:
            payload["data"] = data

        await self.send_to_job(
            job_id, WebSocketMessage(type=MessageType.JOB_PROGRESS, payload=payload, job_id=job_id)
        )

    async def send_job_completed(self, job_id: str, result: dict | None = None):
        """Notifica que un job se completó"""
        await self.send_to_job(
            job_id,
            WebSocketMessage(
                type=MessageType.JOB_COMPLETED,
                payload={"message": "Procesamiento completado", "result": result},
                job_id=job_id,
            ),
        )

    async def send_job_failed(self, job_id: str, error: str):
        """Notifica que un job falló"""
        await self.send_to_job(
            job_id,
            WebSocketMessage(
                type=MessageType.JOB_FAILED,
                payload={"message": "Procesamiento fallido", "error": error},
                job_id=job_id,
            ),
        )

    async def send_heartbeat(self, websocket: WebSocket):
        """Envía heartbeat a un cliente"""
        await self._send_message(
            websocket,
            WebSocketMessage(
                type=MessageType.HEARTBEAT, payload={"timestamp": datetime.now(UTC).isoformat()}
            ),
        )

    # =========================================================================
    # Estadísticas
    # =========================================================================

    def get_stats(self) -> dict[str, Any]:
        """Retorna estadísticas de conexiones"""
        return {
            "total_connections": len(self._active_connections),
            "jobs_with_connections": len(self._job_connections),
            "users_with_connections": len(self._user_connections),
            "connections_by_job": {
                job_id: len(conns) for job_id, conns in self._job_connections.items()
            },
        }


# =============================================================================
# Singleton global
# =============================================================================

_manager: ConnectionManager | None = None


def get_websocket_manager() -> ConnectionManager:
    """Obtiene la instancia singleton del WebSocket manager"""
    global _manager
    if _manager is None:
        _manager = ConnectionManager()
    return _manager


# =============================================================================
# Integración con Redis Pub/Sub (para múltiples instancias de API)
# =============================================================================


class RedisPubSubManager:
    """
    Manager que usa Redis Pub/Sub para sincronizar WebSockets
    entre múltiples instancias del API.

    Útil cuando hay múltiples réplicas del backend y un cliente
    puede estar conectado a una instancia diferente de donde
    se ejecuta el Celery task.
    """

    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self._pubsub = None
        self._local_manager = get_websocket_manager()
        self._running = False

    async def connect(self):
        """Conecta al Redis Pub/Sub"""
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
        """Desconecta del Redis Pub/Sub"""
        self._running = False
        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.close()
        if hasattr(self, "_redis"):
            await self._redis.close()

    async def publish_event(self, event_type: str, job_id: str, data: dict):
        """Publica un evento a Redis para que otras instancias lo reciban"""
        if not hasattr(self, "_redis"):
            # Fallback a local manager
            await self._handle_event(event_type, job_id, data)
            return

        try:
            message = json.dumps({"type": event_type, "job_id": job_id, "data": data})
            await self._redis.publish("qprisma:websocket:events", message)
        except Exception as e:
            logger.error(f"Failed to publish event: {e}")
            # Fallback a local
            await self._handle_event(event_type, job_id, data)

    async def _handle_event(self, event_type: str, job_id: str, data: dict):
        """Maneja un evento (local o recibido de Redis)"""
        if event_type == "progress":
            await self._local_manager.send_job_progress(
                job_id, data.get("progress", 0), data.get("stage", "unknown"), data.get("message")
            )
        elif event_type == "completed":
            await self._local_manager.send_job_completed(job_id, data.get("result"))
        elif event_type == "failed":
            await self._local_manager.send_job_failed(job_id, data.get("error", "Unknown error"))

    async def listen(self):
        """Escucha eventos de Redis y los propaga a WebSockets locales"""
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


# Singleton para Redis Pub/Sub
_pubsub_manager: RedisPubSubManager | None = None


async def get_pubsub_manager() -> RedisPubSubManager:
    """Obtiene el manager de Redis Pub/Sub"""
    global _pubsub_manager
    if _pubsub_manager is None:
        import os

        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        _pubsub_manager = RedisPubSubManager(redis_url)
        await _pubsub_manager.connect()
    return _pubsub_manager
