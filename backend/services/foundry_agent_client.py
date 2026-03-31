"""
Foundry Agent Client
====================

Wraps the Azure AI Projects SDK to communicate with QPrisma's
hosted video agent via the Foundry Responses API.

Hosted agents are containerized agents deployed to Azure AI Foundry
Agent Service.  They expose a ``/responses`` endpoint and are invoked
through the project-level Responses API — **not** the standard
Threads/Messages/Runs (assistants) pattern.

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

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from core.config import settings

logger = logging.getLogger(__name__)

# Default API version for Foundry Agent Service
_API_VERSION = "2025-05-15-preview"


class FoundryAgentClient:
    """
    Client for communicating with QPrisma's Foundry Hosted Agent.

    Uses the ``AIProjectClient.send_request()`` low-level method to call the
    Foundry Responses API, which proxies to the hosted container's
    ``/responses`` endpoint.
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
        """Lazy-initialize the AIProjectClient."""
        if self._client is not None:
            return self._client

        try:
            from azure.ai.projects import AIProjectClient
            from azure.identity import DefaultAzureCredential

            self._client = AIProjectClient(
                endpoint=self._project_endpoint,
                credential=DefaultAzureCredential(),
            )
            return self._client
        except ImportError:
            logger.error(
                "azure-ai-projects SDK not installed. "
                "Install with: pip install 'azure-ai-projects>=1.0.0b7'"
            )
            raise
        except Exception as e:
            logger.error(f"Failed to create AIProjectClient: {e}")
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
        Send a message to the hosted agent via the Foundry Responses API.

        QPrisma-specific context (media_id, user_id, etc.) is prepended
        to the message, which the hosted agent extracts in its
        ``restore_media_context`` node.

        Args:
            message: The user's query text
            media_id: Current video ID for context
            media_ids: Multiple video IDs for cross-video queries
            user_id: Authenticated user ID for multi-tenant isolation
            session_id: Conversation session ID
            thread_id: Previous response ID for conversation continuity

        Returns:
            Dictionary with 'content' (str), 'thread_id' (str), and 'metadata' (dict)
        """
        from azure.core.rest import HttpRequest

        client = self._get_client()

        metadata = self._build_metadata(
            media_id=media_id,
            media_ids=media_ids,
            user_id=user_id,
            session_id=session_id,
        )
        full_message = self._prepend_context(message, metadata)

        body: dict[str, Any] = {
            "input": full_message,
            "stream": False,
        }
        if thread_id:
            body["previous_response_id"] = thread_id

        try:
            request = HttpRequest(
                method="POST",
                url=f"agents/{self._agent_name}/responses?api-version={_API_VERSION}",
                json=body,
                headers={"Content-Type": "application/json"},
            )

            response = await asyncio.to_thread(client.send_request, request)
            response.raise_for_status()
            result = response.json()

            response_id = result.get("id", "")
            content = self._extract_text(result)

            return {
                "content": content,
                "thread_id": response_id,
                "metadata": metadata,
            }

        except Exception as e:
            # If a stale previous_response_id caused the failure, retry without it
            if thread_id and self._is_retriable_status(e):
                logger.warning(f"Retrying without previous_response_id (was '{thread_id}')")
                body.pop("previous_response_id", None)
                request = HttpRequest(
                    method="POST",
                    url=f"agents/{self._agent_name}/responses?api-version={_API_VERSION}",
                    json=body,
                    headers={"Content-Type": "application/json"},
                )
                response = await asyncio.to_thread(client.send_request, request)
                response.raise_for_status()
                result = response.json()
                return {
                    "content": self._extract_text(result),
                    "thread_id": result.get("id", ""),
                    "metadata": metadata,
                }
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
        - {"type": "done", "content": "full response", "thread_id": "..."}

        Args:
            message: The user's query text
            media_id: Current video ID
            media_ids: Multiple video IDs
            user_id: Authenticated user ID
            session_id: Conversation session ID
            thread_id: Previous response ID for conversation continuity

        Yields:
            Event dictionaries with type and content
        """
        from azure.core.rest import HttpRequest

        client = self._get_client()

        metadata = self._build_metadata(
            media_id=media_id,
            media_ids=media_ids,
            user_id=user_id,
            session_id=session_id,
        )
        full_message = self._prepend_context(message, metadata)

        body: dict[str, Any] = {
            "input": full_message,
            "stream": True,
        }
        if thread_id:
            body["previous_response_id"] = thread_id

        try:
            request = HttpRequest(
                method="POST",
                url=f"agents/{self._agent_name}/responses?api-version={_API_VERSION}",
                json=body,
                headers={"Content-Type": "application/json"},
            )

            response = await asyncio.to_thread(client.send_request, request, stream=True)
            response.raise_for_status()

            accumulated_content = ""
            response_id = ""

            loop = asyncio.get_running_loop()
            queue: asyncio.Queue[dict | None] = asyncio.Queue()

            def _read_stream() -> None:
                """Read SSE stream from the response in a worker thread."""
                try:
                    for line in response.iter_lines():
                        if not line:
                            continue
                        text = line.decode("utf-8") if isinstance(line, bytes) else line
                        if text.startswith("data: "):
                            data_str = text[6:]
                            if data_str.strip() == "[DONE]":
                                break
                            try:
                                event = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue
                            loop.call_soon_threadsafe(queue.put_nowait, event)
                finally:
                    loop.call_soon_threadsafe(queue.put_nowait, None)
                    response.close()

            reader_task = asyncio.create_task(asyncio.to_thread(_read_stream))
            try:
                while True:
                    event_data = await queue.get()
                    if event_data is None:
                        break

                    event_type = event_data.get("type", "")
                    if event_type == "response.output_text.delta":
                        delta = event_data.get("delta", "")
                        if delta:
                            accumulated_content += delta
                            yield {"type": "token", "content": delta}
                    elif event_type == "response.completed":
                        resp = event_data.get("response", {})
                        response_id = resp.get("id", "")
                        if not accumulated_content:
                            accumulated_content = self._extract_text(resp)
            finally:
                await reader_task

            yield {
                "type": "done",
                "content": accumulated_content,
                "thread_id": response_id,
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
            client = self._get_client()
            agent = await asyncio.to_thread(client.agents.get, agent_name=self._agent_name)
            return {
                "status": "healthy",
                "agent_name": self._agent_name,
                "endpoint": self._project_endpoint,
                "agent_id": getattr(agent, "id", "unknown"),
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
    def _is_retriable_status(exc: Exception) -> bool:
        """Return True if the exception indicates a bad previous_response_id."""
        from azure.core.exceptions import HttpResponseError

        if isinstance(exc, HttpResponseError):
            return exc.status_code in (400, 404)
        return False

    @staticmethod
    def _extract_text(response_data: dict[str, Any]) -> str:
        """Extract text content from a Responses API result."""
        output = response_data.get("output", [])
        parts: list[str] = []
        # Normalize: if output is a string, wrap it so we don't iterate chars
        output_items = output if isinstance(output, list) else [output]
        for item in output_items:
            if isinstance(item, dict):
                if item.get("type") == "message":
                    for content in item.get("content", []):
                        if isinstance(content, dict) and content.get("type") == "output_text":
                            text = content.get("text", "")
                            if isinstance(text, str):
                                parts.append(text)
            elif isinstance(item, str):
                parts.append(item)
        if parts:
            return "\n".join(parts)
        # Fallback: try top-level 'output' as string
        raw = response_data.get("output", "")
        return raw if isinstance(raw, str) else str(raw)

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
        logger.info(f"Foundry agent client initialized: {agent_name} @ {endpoint}")

    return _foundry_client
