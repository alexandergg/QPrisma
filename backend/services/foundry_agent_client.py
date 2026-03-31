"""
Foundry Agent Client
====================

Wraps the Azure AI Projects SDK to communicate with QPrisma's
hosted video agent via the Foundry Responses API.

Hosted agents are containerized agents deployed to Azure AI Foundry
Agent Service.  They are invoked through the OpenAI Responses API
using an ``agent_reference`` — **not** the standard
Threads/Messages/Runs (assistants) pattern.

Official pattern (from Microsoft docs)::

    project = AIProjectClient(endpoint=..., credential=...)
    openai = project.get_openai_client()
    response = openai.responses.create(
        input=[{"role": "user", "content": "Hello!"}],
        extra_body={"agent_reference": {"name": agent_name, "type": "agent_reference"}},
    )

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


class FoundryAgentClient:
    """
    Client for communicating with QPrisma's Foundry Hosted Agent.

    Uses ``AIProjectClient.get_openai_client()`` to obtain an OpenAI client
    configured for the Foundry project, then calls ``openai.responses.create()``
    with an ``agent_reference`` to route to the hosted agent.
    """

    def __init__(
        self,
        project_endpoint: str,
        agent_name: str,
    ):
        self._project_endpoint = project_endpoint
        self._agent_name = agent_name
        self._project_client = None
        self._openai_client = None

    def _get_openai_client(self):
        """Lazy-initialize the OpenAI client via AIProjectClient."""
        if self._openai_client is not None:
            return self._openai_client

        try:
            from azure.ai.projects import AIProjectClient
            from azure.identity import DefaultAzureCredential

            self._project_client = AIProjectClient(
                endpoint=self._project_endpoint,
                credential=DefaultAzureCredential(),
            )
            self._openai_client = self._project_client.get_openai_client()
            return self._openai_client
        except ImportError:
            logger.error(
                "azure-ai-projects SDK not installed. "
                "Install with: pip install 'azure-ai-projects>=1.0.0b7'"
            )
            raise
        except Exception as e:
            logger.error(f"Failed to create OpenAI client: {e}")
            raise

    def _agent_ref(self) -> dict[str, str]:
        """Return the agent_reference body for Responses API calls."""
        return {"name": self._agent_name, "type": "agent_reference"}

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
        Send a message to the hosted agent via the OpenAI Responses API.

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
        openai = self._get_openai_client()

        metadata = self._build_metadata(
            media_id=media_id,
            media_ids=media_ids,
            user_id=user_id,
            session_id=session_id,
        )
        full_message = self._prepend_context(message, metadata)

        input_messages = [{"role": "user", "content": full_message}]
        extra: dict[str, Any] = {"agent_reference": self._agent_ref()}
        if thread_id:
            extra["previous_response_id"] = thread_id

        try:
            response = await asyncio.to_thread(
                openai.responses.create,
                input=input_messages,
                extra_body=extra,
            )

            response_id = response.id or ""
            content = response.output_text or ""

            return {
                "content": content,
                "thread_id": response_id,
                "metadata": metadata,
            }

        except Exception as e:
            # If a stale previous_response_id caused the failure, retry without it
            if thread_id and self._is_retriable(e):
                logger.warning(f"Retrying without previous_response_id (was '{thread_id}')")
                extra.pop("previous_response_id", None)
                response = await asyncio.to_thread(
                    openai.responses.create,
                    input=input_messages,
                    extra_body=extra,
                )
                return {
                    "content": response.output_text or "",
                    "thread_id": response.id or "",
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
        openai = self._get_openai_client()

        metadata = self._build_metadata(
            media_id=media_id,
            media_ids=media_ids,
            user_id=user_id,
            session_id=session_id,
        )
        full_message = self._prepend_context(message, metadata)

        input_messages = [{"role": "user", "content": full_message}]
        extra: dict[str, Any] = {"agent_reference": self._agent_ref()}
        if thread_id:
            extra["previous_response_id"] = thread_id

        try:
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue[dict | None] = asyncio.Queue()

            def _stream_worker() -> None:
                """Run the streaming call in a worker thread."""
                stream = None
                try:
                    stream = openai.responses.create(
                        input=input_messages,
                        stream=True,
                        extra_body=extra,
                    )
                    for event in stream:
                        loop.call_soon_threadsafe(
                            queue.put_nowait,
                            {"type": event.type, "data": event},
                        )
                finally:
                    if stream is not None:
                        stream.close()
                    loop.call_soon_threadsafe(queue.put_nowait, None)

            accumulated_content = ""
            response_id = ""
            # Track active function calls to pair start/end events
            active_tool_calls: dict[str, str] = {}  # item_id -> function name

            reader_task = asyncio.create_task(asyncio.to_thread(_stream_worker))
            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        break

                    event_type = item["type"]
                    event = item["data"]

                    # Log every event for diagnostics (helps validate hosted agent behavior)
                    if event_type != "response.output_text.delta":
                        logger.debug(
                            "Foundry stream event: %s (item_type=%s)",
                            event_type,
                            getattr(getattr(event, "item", None), "type", "-"),
                        )

                    if event_type == "response.output_text.delta":
                        delta = getattr(event, "delta", "")
                        if delta:
                            accumulated_content += delta
                            yield {"type": "token", "content": delta}

                    elif event_type == "response.output_item.added":
                        # A new output item appeared — check if it's a function call
                        output_item = getattr(event, "item", None)
                        if output_item and getattr(output_item, "type", "") == "function_call":
                            fn_name = getattr(output_item, "name", "") or "unknown"
                            item_id = getattr(output_item, "id", "")
                            if item_id:
                                active_tool_calls[item_id] = fn_name
                            yield {
                                "type": "tool_start",
                                "name": fn_name,
                                "call_id": getattr(output_item, "call_id", item_id),
                            }

                    elif event_type == "response.function_call_arguments.done":
                        # Function call arguments are fully assembled
                        fn_name = getattr(event, "name", "") or "unknown"
                        raw_args = getattr(event, "arguments", "") or ""
                        parsed_args: dict[str, Any] = {}
                        try:
                            parsed_args = json.loads(raw_args) if raw_args else {}
                        except (json.JSONDecodeError, TypeError):
                            pass
                        # Extract a human-readable description from args
                        description = (
                            parsed_args.get("query")
                            or parsed_args.get("entity_name")
                            or parsed_args.get("topic")
                            or ""
                        )
                        yield {
                            "type": "tool_args",
                            "name": fn_name,
                            "arguments": parsed_args,
                            "description": str(description)[:100],
                        }

                    elif event_type == "response.output_item.done":
                        # An output item finished — emit tool_end for function calls
                        output_item = getattr(event, "item", None)
                        if output_item and getattr(output_item, "type", "") == "function_call":
                            fn_name = getattr(output_item, "name", "") or "unknown"
                            item_id = getattr(output_item, "id", "")
                            active_tool_calls.pop(item_id, None)
                            yield {
                                "type": "tool_end",
                                "name": fn_name,
                                "call_id": getattr(output_item, "call_id", item_id),
                                "success": True,
                            }

                    elif event_type == "response.completed":
                        resp = getattr(event, "response", None)
                        if resp:
                            response_id = getattr(resp, "id", "")
                            if not accumulated_content:
                                accumulated_content = getattr(resp, "output_text", "") or ""
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
            if self._project_client is None:
                self._get_openai_client()
            client = self._project_client
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
    def _is_retriable(exc: Exception) -> bool:
        """Return True if the exception indicates a bad previous_response_id."""
        import openai as _openai

        return isinstance(exc, _openai.BadRequestError | _openai.NotFoundError)

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
