"""
Foundry Agent Client
====================

Wraps the Azure AI Foundry SDK to communicate with QPrisma's
hosted video agent. Supports both Responses API (for simple queries)
and A2A protocol (for task lifecycle management).

Usage::

    from services.foundry_agent_client import get_foundry_agent_client

    client = get_foundry_agent_client()
    if client:
        result = await client.send_message(
            message="What happens in the first 5 minutes?",
            media_id="abc-123",
            user_id="user-456",
        )
"""

import logging
from collections.abc import AsyncGenerator
from typing import Any

from core.config import settings

logger = logging.getLogger(__name__)


class FoundryAgentClient:
    """
    Client for communicating with QPrisma's Foundry Hosted Agent.

    Abstracts the Azure AI Projects SDK to provide a clean interface
    for sending messages and streaming responses from the hosted agent.
    """

    def __init__(
        self,
        project_endpoint: str,
        agent_name: str,
    ):
        self._project_endpoint = project_endpoint
        self._agent_name = agent_name
        self._client = None

    def _get_client(self):
        """Lazy-initialize the Azure AI Projects client."""
        if self._client is not None:
            return self._client

        try:
            from azure.ai.projects import AIProjectClient
            from azure.identity import DefaultAzureCredential

            self._client = AIProjectClient(
                endpoint=self._project_endpoint,
                credential=DefaultAzureCredential(),
                allow_preview=True,
            )
            return self._client
        except ImportError:
            logger.error(
                "azure-ai-projects SDK not installed. "
                "Install with: pip install 'azure-ai-projects>=1.0.0b7'"
            )
            raise
        except Exception as e:
            logger.error(f"Failed to create Foundry client: {e}")
            raise

    async def send_message(
        self,
        message: str,
        *,
        media_id: str | None = None,
        media_ids: list[str] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Send a message to the hosted agent via Foundry Responses API.

        QPrisma-specific context (media_id, user_id, etc.) is passed
        as metadata in the request, which the hosted agent extracts
        in its ``restore_media_context`` node.

        Args:
            message: The user's query text
            media_id: Current video ID for context
            media_ids: Multiple video IDs for cross-video queries
            user_id: Authenticated user ID for multi-tenant isolation
            session_id: Conversation session ID
            thread_id: Foundry thread ID for conversation continuity

        Returns:
            Dictionary with 'content' (str), 'thread_id' (str), and 'metadata' (dict)
        """
        import asyncio

        client = self._get_client()

        metadata = self._build_metadata(
            media_id=media_id,
            media_ids=media_ids,
            user_id=user_id,
            session_id=session_id,
        )
        full_message = self._prepend_context(message, metadata)

        try:
            response = await asyncio.to_thread(
                client.agents.create_response,
                agent_name=self._agent_name,
                input=full_message,
                thread_id=thread_id,
            )

            return {
                "content": (
                    response.output_text
                    if hasattr(response, "output_text")
                    else str(response)
                ),
                "thread_id": getattr(response, "thread_id", thread_id),
                "metadata": metadata,
            }

        except Exception as e:
            logger.error(
                f"Foundry agent call failed: {e}",
                extra={"agent_name": self._agent_name, "media_id": media_id},
            )
            raise

    async def send_streaming_message(
        self,
        message: str,
        *,
        media_id: str | None = None,
        media_ids: list[str] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        thread_id: str | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Send a message and stream the response from the hosted agent.

        Yields dictionaries with event type and data:
        - {"type": "token", "content": "..."}
        - {"type": "tool_start", "name": "search_video"}
        - {"type": "tool_end", "name": "search_video"}
        - {"type": "done", "content": "full response", "thread_id": "..."}

        Args:
            message: The user's query text
            media_id: Current video ID
            media_ids: Multiple video IDs
            user_id: Authenticated user ID
            session_id: Conversation session ID
            thread_id: Foundry thread ID

        Yields:
            Event dictionaries with type and content
        """
        import asyncio

        client = self._get_client()

        metadata = self._build_metadata(
            media_id=media_id,
            media_ids=media_ids,
            user_id=user_id,
            session_id=session_id,
        )
        full_message = self._prepend_context(message, metadata)

        try:
            response_stream = await asyncio.to_thread(
                client.agents.create_response,
                agent_name=self._agent_name,
                input=full_message,
                thread_id=thread_id,
                stream=True,
            )

            accumulated_content = ""
            for event in response_stream:
                event_type = getattr(event, "type", None)

                if event_type == "response.output_text.delta":
                    delta = getattr(event, "delta", "")
                    accumulated_content += delta
                    yield {"type": "token", "content": delta}

                elif event_type == "response.function_call_arguments.start":
                    yield {
                        "type": "tool_start",
                        "name": getattr(event, "name", "unknown"),
                    }

                elif event_type == "response.function_call_arguments.done":
                    yield {
                        "type": "tool_end",
                        "name": getattr(event, "name", "unknown"),
                    }

            yield {
                "type": "done",
                "content": accumulated_content,
                "thread_id": getattr(response_stream, "thread_id", thread_id),
            }

        except Exception as e:
            logger.error(
                f"Foundry streaming failed: {e}",
                extra={"agent_name": self._agent_name, "media_id": media_id},
            )
            yield {"type": "error", "content": str(e)}

    async def health_check(self) -> dict[str, Any]:
        """Check if the Foundry hosted agent is reachable."""
        try:
            import asyncio

            client = self._get_client()
            await asyncio.to_thread(client.agents.list)
            return {
                "status": "healthy",
                "agent_name": self._agent_name,
                "endpoint": self._project_endpoint,
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "agent_name": self._agent_name,
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_metadata(
        *,
        media_id: str | None,
        media_ids: list[str] | None,
        user_id: str | None,
        session_id: str | None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        if media_id:
            metadata["media_id"] = media_id
        if media_ids:
            metadata["media_ids"] = media_ids
        if user_id:
            metadata["user_id"] = user_id
        if session_id:
            metadata["session_id"] = session_id
        return metadata

    @staticmethod
    def _prepend_context(message: str, metadata: dict[str, Any]) -> str:
        """Prepend QPrisma context for the hosted agent to parse."""
        if not metadata:
            return message
        import json

        return f"[QPRISMA_CONTEXT:{json.dumps(metadata)}]\n{message}"


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_foundry_client: FoundryAgentClient | None = None


def get_foundry_agent_client() -> FoundryAgentClient:
    """
    Get or create the global Foundry agent client.

    Raises:
        RuntimeError: If FOUNDRY_PROJECT_ENDPOINT or FOUNDRY_AGENT_NAME
            are not configured.
    """
    global _foundry_client

    if _foundry_client is None:
        endpoint = settings.foundry.project_endpoint
        agent_name = settings.foundry.agent_name

        if not endpoint or not agent_name:
            raise RuntimeError(
                "Foundry agent not configured. Set FOUNDRY_PROJECT_ENDPOINT "
                "and FOUNDRY_AGENT_NAME environment variables."
            )

        _foundry_client = FoundryAgentClient(
            project_endpoint=endpoint,
            agent_name=agent_name,
        )
        logger.info(
            f"Foundry agent client initialized: {agent_name} @ {endpoint}"
        )

    return _foundry_client
