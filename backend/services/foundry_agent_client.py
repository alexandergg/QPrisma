"""
Foundry Agent Client
====================

Wraps the Azure AI Agents SDK to communicate with QPrisma's
hosted video agent via the standard Threads → Messages → Runs API.

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

    Uses the ``azure-ai-agents`` SDK with the Threads/Messages/Runs
    pattern for both synchronous and streaming interactions.
    """

    def __init__(
        self,
        project_endpoint: str,
        agent_name: str,
    ):
        self._project_endpoint = project_endpoint
        self._agent_name = agent_name
        self._client = None
        self._agent_id: str | None = None

    def _get_client(self):
        """Lazy-initialize the Azure AI Agents client."""
        if self._client is not None:
            return self._client

        try:
            from azure.ai.agents import AgentsClient
            from azure.identity import DefaultAzureCredential

            self._client = AgentsClient(
                endpoint=self._project_endpoint,
                credential=DefaultAzureCredential(),
            )
            return self._client
        except ImportError:
            logger.error(
                "azure-ai-agents SDK not installed. "
                "Install with: pip install 'azure-ai-agents>=1.0.0'"
            )
            raise
        except Exception as e:
            logger.error(f"Failed to create Agents client: {e}")
            raise

    def _resolve_agent_id(self, client) -> str:
        """Resolve agent name to agent ID (cached)."""
        if self._agent_id is not None:
            return self._agent_id

        for agent in client.list_agents():
            if agent.name == self._agent_name:
                self._agent_id = agent.id
                logger.info(f"Resolved agent '{self._agent_name}' → {agent.id}")
                return self._agent_id

        raise RuntimeError(
            f"Agent '{self._agent_name}' not found in project. Check FOUNDRY_AGENT_NAME is correct."
        )

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
        Send a message to the hosted agent via Threads/Messages/Runs API.

        QPrisma-specific context (media_id, user_id, etc.) is prepended
        to the message, which the hosted agent extracts in its
        ``restore_media_context`` node.

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

        from azure.ai.agents.models import MessageRole

        client = self._get_client()
        agent_id = await asyncio.to_thread(self._resolve_agent_id, client)

        metadata = self._build_metadata(
            media_id=media_id,
            media_ids=media_ids,
            user_id=user_id,
            session_id=session_id,
        )
        full_message = self._prepend_context(message, metadata)

        try:
            # Create or reuse thread
            if thread_id:
                await asyncio.to_thread(
                    client.messages.create,
                    thread_id=thread_id,
                    role=MessageRole.USER,
                    content=full_message,
                )
            else:
                from azure.ai.agents.models import ThreadMessageOptions

                thread = await asyncio.to_thread(
                    client.threads.create,
                    messages=[ThreadMessageOptions(role=MessageRole.USER, content=full_message)],
                )
                thread_id = thread.id

            # Run the agent and poll until completion
            await asyncio.to_thread(
                client.runs.create_and_process,
                thread_id=thread_id,
                agent_id=agent_id,
            )

            # Retrieve the assistant's response
            last_msg = await asyncio.to_thread(
                client.messages.get_last_message_text_by_role,
                thread_id=thread_id,
                role=MessageRole.AGENT,
            )

            content = last_msg.text if last_msg else ""

            return {
                "content": content,
                "thread_id": thread_id,
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
        - {"type": "tool_start", "name": "..."}
        - {"type": "tool_end", "name": "..."}
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

        from azure.ai.agents.models import AgentStreamEvent, MessageRole

        client = self._get_client()
        agent_id = await asyncio.to_thread(self._resolve_agent_id, client)

        metadata = self._build_metadata(
            media_id=media_id,
            media_ids=media_ids,
            user_id=user_id,
            session_id=session_id,
        )
        full_message = self._prepend_context(message, metadata)

        try:
            # Create or reuse thread
            if thread_id:
                await asyncio.to_thread(
                    client.messages.create,
                    thread_id=thread_id,
                    role=MessageRole.USER,
                    content=full_message,
                )
            else:
                from azure.ai.agents.models import ThreadMessageOptions

                thread = await asyncio.to_thread(
                    client.threads.create,
                    messages=[ThreadMessageOptions(role=MessageRole.USER, content=full_message)],
                )
                thread_id = thread.id

            # Stream the run
            event_stream = await asyncio.to_thread(
                client.runs.stream,
                thread_id=thread_id,
                agent_id=agent_id,
            )

            accumulated_content = ""

            def _iter_events():
                with event_stream:
                    for event_type, event_data, _ in event_stream:
                        yield event_type, event_data

            for event_type, event_data in await asyncio.to_thread(lambda: list(_iter_events())):
                if event_type == AgentStreamEvent.THREAD_MESSAGE_DELTA:
                    text = getattr(event_data, "text", "")
                    if text:
                        accumulated_content += text
                        yield {"type": "token", "content": text}

                elif event_type == AgentStreamEvent.THREAD_RUN_STEP_CREATED:
                    step_type = getattr(event_data, "type", "")
                    if step_type == "tool_calls":
                        yield {"type": "tool_start", "name": "agent_tool"}

                elif event_type == AgentStreamEvent.THREAD_RUN_STEP_COMPLETED:
                    step_type = getattr(event_data, "type", "")
                    if step_type == "tool_calls":
                        yield {"type": "tool_end", "name": "agent_tool"}

            yield {
                "type": "done",
                "content": accumulated_content,
                "thread_id": thread_id,
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
            agents = await asyncio.to_thread(lambda: list(client.list_agents(limit=1)))
            return {
                "status": "healthy",
                "agent_name": self._agent_name,
                "endpoint": self._project_endpoint,
                "agents_found": len(agents),
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
        logger.info(f"Foundry agent client initialized: {agent_name} @ {endpoint}")

    return _foundry_client
