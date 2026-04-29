"""
Foundry Agent Client
====================

Wraps the Azure AI Projects SDK to communicate with QPrisma's
hosted video agent via the dedicated Foundry agent endpoint.

Hosted agents are containerized agents deployed to Azure AI Foundry
Agent Service. They are invoked through the OpenAI Responses API
bound to the hosted agent's dedicated endpoint — **not** the standard
Threads/Messages/Runs (assistants) pattern.

Conversation continuity is achieved via the Foundry Conversations API:
- ``conversations.create()`` to start a new conversation
- ``conversation=conv.id`` on ``responses.create()`` to continue

Usage::

    from services.foundry_agent_client import get_foundry_agent_client

    client = get_foundry_agent_client()
    if client:
        conv_id = await client.create_conversation()
        result = await client.send_message(
            message="What happens in the first 5 minutes?",
            media_id="abc-123",
            user_id="user-456",
            conversation_id=conv_id,
        )
"""

import asyncio
import json
import logging
import re
from collections.abc import AsyncGenerator
from typing import Any

from core.config import settings

logger = logging.getLogger(__name__)


class FoundryAgentClient:
    """
    Client for communicating with QPrisma's Foundry Hosted Agent.

    Uses ``AIProjectClient.get_openai_client(agent_name=...)`` to obtain an
    OpenAI client bound to the hosted agent's dedicated endpoint, then calls
    ``openai.responses.create()`` with optional ``conversation`` continuity.
    """

    def __init__(
        self,
        project_endpoint: str,
        agent_name: str,
        request_timeout_seconds: float = 120.0,
    ):
        self._project_endpoint = project_endpoint
        self._agent_name = agent_name
        self._project_client = None
        self._openai_client = None
        self._request_timeout_seconds = request_timeout_seconds

    def _get_openai_client(self):
        """Lazy-initialize the OpenAI client bound to the hosted agent endpoint."""
        if self._openai_client is not None:
            return self._openai_client

        try:
            from azure.ai.projects import AIProjectClient
            from azure.identity import DefaultAzureCredential

            self._project_client = AIProjectClient(
                endpoint=self._project_endpoint,
                credential=DefaultAzureCredential(),
                allow_preview=True,
            )
            self._openai_client = self._project_client.get_openai_client(
                agent_name=self._agent_name
            )
            return self._openai_client
        except ImportError:
            logger.error(
                "azure-ai-projects SDK not installed. "
                "Install with: pip install 'azure-ai-projects>=2.1.0'"
            )
            raise
        except Exception as e:
            logger.error("Failed to create OpenAI client: %s", e)
            raise

    @staticmethod
    def _get_response_field(obj: Any, name: str, default: Any = None) -> Any:
        """Read an SDK response field from either dict-like or attribute objects."""
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    @classmethod
    def _extract_response_text(cls, response: Any) -> str:
        """Extract assistant text from Responses API payloads."""
        output_text = cls._get_response_field(response, "output_text", "")
        if isinstance(output_text, str) and output_text.strip():
            return output_text

        output = cls._get_response_field(response, "output", None) or []
        if isinstance(output, str):
            return output

        parts: list[str] = []
        if isinstance(output, list):
            for item in output:
                text = cls._extract_output_item_text(item)
                if text:
                    parts.append(text)
        return "".join(parts)

    @classmethod
    def _extract_output_item_text(cls, item: Any) -> str:
        """Extract text from a single structured Responses API output item."""
        if item is None:
            return ""
        if isinstance(item, str):
            return item

        delta = cls._get_response_field(item, "delta", None)
        if isinstance(delta, str):
            return delta
        if delta is not None:
            delta_text = cls._extract_output_item_text(delta)
            if delta_text:
                return delta_text

        item_text = cls._get_response_field(item, "text", None)
        if isinstance(item_text, str):
            return item_text

        value = cls._get_response_field(item, "value", None)
        if isinstance(value, str):
            return value

        content = cls._get_response_field(item, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts = [cls._extract_output_item_text(part) for part in content]
            return "".join(part for part in text_parts if part)

        return ""

    @classmethod
    def _extract_stream_text(cls, event: Any) -> str:
        """Extract incremental text from supported Responses stream event shapes."""
        delta_text = cls._extract_output_item_text(cls._get_response_field(event, "delta", None))
        if delta_text:
            return delta_text

        text = cls._extract_output_item_text(cls._get_response_field(event, "text", None))
        if text:
            return text

        part_text = cls._extract_output_item_text(
            cls._get_response_field(event, "content_part", None)
        )
        if part_text:
            return part_text

        return cls._extract_output_item_text(cls._get_response_field(event, "item", None))

    async def create_conversation(self) -> str:
        """
        Create a new Foundry conversation.

        Returns:
            The Foundry conversation ID to pass to send_message/send_streaming_message.
        """
        openai = self._get_openai_client()
        try:
            conversation = await asyncio.to_thread(openai.conversations.create)
            conv_id = conversation.id
            logger.info("Created Foundry conversation: %s", conv_id)
            return conv_id
        except Exception as e:
            logger.error("Failed to create Foundry conversation: %s", e)
            raise

    async def send_message(
        self,
        message: str,
        *,
        media_id: str | None = None,
        media_ids: list[str] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Send a message to the hosted agent via the OpenAI Responses API.

        Args:
            message: The user's query text
            media_id: Current video ID for context
            media_ids: Multiple video IDs for cross-video queries
            user_id: Authenticated user ID for multi-tenant isolation
            session_id: Conversation session ID
            conversation_id: Foundry conversation ID for conversation continuity

        Returns:
            Dictionary with 'content' (str), 'thread_id' (str),
            'conversation_id' (str), and 'metadata' (dict)
        """
        openai = self._get_openai_client()

        def _build_request(
            active_session_id: str | None,
            active_conversation_id: str | None,
        ) -> tuple[dict[str, Any], dict[str, Any]]:
            request_metadata = self._build_metadata(
                media_id=media_id,
                media_ids=media_ids,
                user_id=user_id,
                session_id=active_session_id,
            )
            request_kwargs: dict[str, Any] = {
                "input": [{"role": "user", "content": message}],
            }
            if request_metadata:
                request_kwargs["metadata"] = request_metadata
            if active_conversation_id:
                request_kwargs["conversation"] = active_conversation_id
            return request_kwargs, request_metadata

        kwargs, metadata = _build_request(session_id, conversation_id)

        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(openai.responses.create, **kwargs),
                timeout=self._request_timeout_seconds,
            )

            response_id = getattr(response, "id", "") or ""
            content = self._extract_response_text(response)

            return {
                "content": content,
                "thread_id": response_id,
                "conversation_id": self._extract_conversation_id(response) or conversation_id or "",
                "metadata": metadata,
            }

        except TimeoutError:
            logger.error(
                "Foundry agent call timed out after %.1fs",
                self._request_timeout_seconds,
                extra={"agent_name": self._agent_name},
            )
            raise
        except Exception as e:
            if conversation_id and self._is_retriable(e):
                new_conversation_id = await self.create_conversation()
                logger.warning(
                    "Retrying send_message with new conversation",
                    extra={"agent_name": self._agent_name},
                )
                kwargs, metadata = _build_request(new_conversation_id, new_conversation_id)
                response = await asyncio.wait_for(
                    asyncio.to_thread(openai.responses.create, **kwargs),
                    timeout=self._request_timeout_seconds,
                )
                return {
                    "content": self._extract_response_text(response),
                    "thread_id": getattr(response, "id", "") or "",
                    "conversation_id": (
                        self._extract_conversation_id(response) or new_conversation_id
                    ),
                    "metadata": metadata,
                }
            logger.exception(
                "Foundry agent call failed",
                extra={"agent_name": self._agent_name},
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
        conversation_id: str | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Send a message and stream the response from the hosted agent.

        Yields dictionaries with event type and data:
        - {"type": "token", "content": "..."}
        - {"type": "done", "content": "full response", "thread_id": "...",
           "conversation_id": "..."}

        Args:
            message: The user's query text
            media_id: Current video ID
            media_ids: Multiple video IDs
            user_id: Authenticated user ID
            session_id: Conversation session ID
            conversation_id: Foundry conversation ID for conversation continuity

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

        input_messages = [{"role": "user", "content": message}]
        kwargs: dict[str, Any] = {
            "input": input_messages,
            "stream": True,
        }
        if metadata:
            kwargs["metadata"] = metadata
        if conversation_id:
            kwargs["conversation"] = conversation_id

        try:
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue[dict | None] = asyncio.Queue()
            stop_event = asyncio.Event()

            def _stream_worker() -> None:
                """Run the streaming call in a worker thread."""
                stream = None
                try:
                    stream = openai.responses.create(**kwargs)
                    for event in stream:
                        if stop_event.is_set():
                            break
                        loop.call_soon_threadsafe(
                            queue.put_nowait,
                            {"type": event.type, "data": event},
                        )
                except Exception as exc:
                    loop.call_soon_threadsafe(
                        queue.put_nowait,
                        {"type": "_error", "error": exc},
                    )
                finally:
                    if stream is not None:
                        stream.close()
                    loop.call_soon_threadsafe(queue.put_nowait, None)

            accumulated_content = ""
            response_id = ""
            completed_conversation_id = conversation_id or ""
            # Track active function calls to pair start/end events
            active_tool_calls: dict[str, str] = {}  # item_id -> function name

            reader_task = asyncio.create_task(asyncio.to_thread(_stream_worker))
            try:
                while True:
                    try:
                        item = await asyncio.wait_for(
                            queue.get(),
                            timeout=self._request_timeout_seconds,
                        )
                    except TimeoutError:
                        logger.error(
                            "Foundry streaming idle timeout after %.1fs",
                            self._request_timeout_seconds,
                            extra={"agent_name": self._agent_name},
                        )
                        # Signal the reader and cancel its task so the generator
                        # returns promptly instead of blocking in the finally clause.
                        stop_event.set()
                        reader_task.cancel()
                        yield {
                            "type": "error",
                            "content": (
                                f"Foundry hosted agent did not produce output "
                                f"within {self._request_timeout_seconds:.0f}s"
                            ),
                        }
                        break
                    if item is None:
                        break

                    event_type = item["type"]
                    if event_type == "_error":
                        raise item["error"]

                    event = item["data"]

                    if event_type != "response.output_text.delta":
                        logger.debug(
                            "Foundry stream event: %s (item_type=%s)",
                            event_type,
                            getattr(getattr(event, "item", None), "type", "-"),
                        )

                    if event_type in {
                        "response.output_text.delta",
                        "response.content_part.delta",
                    }:
                        delta = self._extract_stream_text(event)
                        if delta:
                            accumulated_content += delta
                            yield {"type": "token", "content": delta}

                    elif event_type == "response.output_text.done":
                        if not accumulated_content:
                            text = self._extract_stream_text(event)
                            if text:
                                accumulated_content = text
                                yield {"type": "token", "content": text}

                    elif event_type == "response.output_item.added":
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
                        fn_name = getattr(event, "name", "") or "unknown"
                        raw_args = getattr(event, "arguments", "") or ""
                        parsed_args: dict[str, Any] = {}
                        try:
                            parsed_args = json.loads(raw_args) if raw_args else {}
                        except (json.JSONDecodeError, TypeError):
                            pass
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
                        elif output_item and not accumulated_content:
                            text = self._extract_output_item_text(output_item)
                            if text:
                                accumulated_content = text
                                yield {"type": "token", "content": text}

                    elif event_type == "response.completed":
                        resp = getattr(event, "response", None)
                        if resp:
                            response_id = getattr(resp, "id", "")
                            completed_conversation_id = (
                                self._extract_conversation_id(resp) or completed_conversation_id
                            )
                            if not accumulated_content:
                                accumulated_content = self._extract_response_text(resp)
            finally:
                if not reader_task.done():
                    stop_event.set()
                    reader_task.cancel()
                try:
                    await reader_task
                except asyncio.CancelledError:
                    pass  # expected after cancel(); suppressing intentionally

            yield {
                "type": "done",
                "content": accumulated_content,
                "thread_id": response_id,
                "conversation_id": completed_conversation_id,
            }

        except Exception as e:
            logger.exception(
                "Foundry streaming failed",
                extra={"agent_name": self._agent_name},
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
        """Return True if the exception indicates a bad conversation/response ID."""
        import openai as _openai

        return isinstance(exc, (_openai.BadRequestError, _openai.NotFoundError))  # noqa: UP038

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
    def _sanitize_log_value(value: object | None, max_len: int = 200) -> str | None:
        """Strip control characters and truncate request-derived log fields."""
        if value is None:
            return None
        return re.sub(r"[\x00-\x1f\x7f-\x9f]", "", str(value))[:max_len]

    @staticmethod
    def _extract_conversation_id(response: Any) -> str:
        """Extract the active conversation ID from a Foundry response if present."""
        conversation = getattr(response, "conversation", None)
        if isinstance(conversation, str):
            return conversation
        if conversation is not None:
            conversation_id = getattr(conversation, "id", None)
            if isinstance(conversation_id, str):
                return conversation_id

        conversation_id = getattr(response, "conversation_id", None)
        return conversation_id if isinstance(conversation_id, str) else ""


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
            request_timeout_seconds=settings.foundry.request_timeout_seconds,
        )
        logger.info("Foundry agent client initialized: %s @ %s", agent_name, endpoint)

    return _foundry_client
