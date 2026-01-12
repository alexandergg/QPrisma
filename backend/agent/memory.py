"""
Agent Memory
=============

Redis-backed conversation memory for the video agent.
Supports session persistence and conversation history.
"""

import json
import logging
import os
from datetime import timedelta
from typing import Any

import redis

logger = logging.getLogger(__name__)


class AgentMemory:
    """
    Redis-backed memory for agent conversations.

    Features:
    - Session persistence across requests
    - Conversation history with TTL
    - Video context caching
    - Thread-safe operations
    """

    def __init__(
        self,
        redis_url: str | None = None,
        session_ttl: int = 3600,  # 1 hour default
        max_messages: int = 50,
    ):
        """
        Initialize agent memory.

        Args:
            redis_url: Redis connection URL
            session_ttl: Session time-to-live in seconds
            max_messages: Maximum messages to keep per session
        """
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.session_ttl = session_ttl
        self.max_messages = max_messages
        self._client: redis.Redis | None = None

    @property
    def client(self) -> redis.Redis:
        """Get or create Redis client."""
        if self._client is None:
            self._client = redis.from_url(self.redis_url, decode_responses=True)
        return self._client

    def _session_key(self, session_id: str) -> str:
        """Generate Redis key for a session."""
        return f"qprisma:agent:session:{session_id}"

    def _messages_key(self, session_id: str) -> str:
        """Generate Redis key for session messages."""
        return f"qprisma:agent:messages:{session_id}"

    # =========================================================================
    # Session Management
    # =========================================================================

    def create_session(
        self,
        session_id: str,
        user_id: str | None = None,
        media_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a new conversation session.

        Args:
            session_id: Unique session identifier
            user_id: Optional user identifier
            media_id: Optional video context

        Returns:
            Session data
        """
        session_data = {
            "session_id": session_id,
            "user_id": user_id,
            "media_id": media_id,
            "created_at": self._timestamp(),
            "last_activity": self._timestamp(),
            "message_count": 0,
        }

        key = self._session_key(session_id)
        self.client.hset(key, mapping={k: json.dumps(v) for k, v in session_data.items()})
        self.client.expire(key, self.session_ttl)

        logger.info(f"Created session {session_id}")
        return session_data

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """
        Get session data.

        Args:
            session_id: Session identifier

        Returns:
            Session data or None if not found
        """
        key = self._session_key(session_id)
        data = self.client.hgetall(key)

        if not data:
            return None

        # Parse JSON values
        return {k: json.loads(v) for k, v in data.items()}

    def update_session(
        self,
        session_id: str,
        media_id: str | None = None,
        **kwargs,
    ) -> None:
        """
        Update session data.

        Args:
            session_id: Session identifier
            media_id: New video context
            **kwargs: Additional fields to update
        """
        key = self._session_key(session_id)

        updates = {"last_activity": self._timestamp()}
        if media_id is not None:
            updates["media_id"] = media_id
        updates.update(kwargs)

        self.client.hset(key, mapping={k: json.dumps(v) for k, v in updates.items()})
        self.client.expire(key, self.session_ttl)  # Refresh TTL

    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session and its messages.

        Args:
            session_id: Session identifier

        Returns:
            True if deleted, False if not found
        """
        session_key = self._session_key(session_id)
        messages_key = self._messages_key(session_id)

        deleted = self.client.delete(session_key, messages_key)
        logger.info(f"Deleted session {session_id}")
        return deleted > 0

    # =========================================================================
    # Message History
    # =========================================================================

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: list[dict] | None = None,
        tool_call_id: str | None = None,
        name: str | None = None,
    ) -> None:
        """
        Add a message to conversation history.

        Args:
            session_id: Session identifier
            role: Message role (user, assistant, tool)
            content: Message content
            tool_calls: Tool calls for assistant messages
            tool_call_id: Tool call ID for tool messages
            name: Tool name for tool messages
        """
        key = self._messages_key(session_id)

        message = {
            "role": role,
            "content": content,
            "timestamp": self._timestamp(),
        }

        if tool_calls:
            message["tool_calls"] = tool_calls
        if tool_call_id:
            message["tool_call_id"] = tool_call_id
        if name:
            message["name"] = name

        # Add to list
        self.client.rpush(key, json.dumps(message))

        # Trim to max messages
        self.client.ltrim(key, -self.max_messages, -1)

        # Set TTL
        self.client.expire(key, self.session_ttl)

        # Update session message count
        session_key = self._session_key(session_id)
        self.client.hincrby(session_key, "message_count", 1)

    def get_messages(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get conversation history.

        Args:
            session_id: Session identifier
            limit: Maximum messages to return (newest first if limited)

        Returns:
            List of messages
        """
        key = self._messages_key(session_id)

        if limit:
            # Get last N messages
            raw_messages = self.client.lrange(key, -limit, -1)
        else:
            raw_messages = self.client.lrange(key, 0, -1)

        return [json.loads(msg) for msg in raw_messages]

    def clear_messages(self, session_id: str) -> None:
        """
        Clear conversation history for a session.

        Args:
            session_id: Session identifier
        """
        key = self._messages_key(session_id)
        self.client.delete(key)

        # Reset message count
        session_key = self._session_key(session_id)
        self.client.hset(session_key, "message_count", json.dumps(0))

    # =========================================================================
    # Helpers
    # =========================================================================

    def _timestamp(self) -> str:
        """Get current timestamp as ISO string."""
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()

    def close(self) -> None:
        """Close Redis connection."""
        if self._client:
            self._client.close()
            self._client = None


# Singleton instance
_memory_instance: AgentMemory | None = None


def get_agent_memory() -> AgentMemory:
    """Get or create agent memory singleton."""
    global _memory_instance
    if _memory_instance is None:
        _memory_instance = AgentMemory()
    return _memory_instance
