"""
A2A Agent Executor
==================

Bridges QPrisma with the A2A (Agent-to-Agent) protocol via
Azure AI Foundry Hosted Agents.

All agent execution is routed through the Foundry hosted container,
which runs the LangGraph VideoAgentGraph inside a managed environment.
This module handles A2A task lifecycle and translates between the
A2A protocol wire format and the Foundry Responses/A2A APIs.

Reference: https://a2a-protocol.org/latest/specification/
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from time import perf_counter

from agent.a2a.task_store import _record_phase_latency, get_task_store
from agent.utils.observability import Metrics, get_logger
from models.a2a_models import (
    Artifact,
    Message,
    Part,
    Role,
    SendMessageRequest,
    StreamResponse,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)

logger = get_logger(__name__)


class A2AAgentExecutor:
    """
    A2A-compliant executor backed by Azure AI Foundry.

    Routes all agent execution through the Foundry hosted agent container.
    The hosted container runs the LangGraph VideoAgentGraph with native
    A2A protocol support, so this executor acts as a thin lifecycle adapter:

    - Creates and manages A2A Task objects locally
    - Delegates actual execution to ``FoundryAgentClient``
    - Translates Foundry streaming events to A2A SSE format
    """

    def __init__(self):
        self.agent_type = "video"
        self.task_store = get_task_store()

    @staticmethod
    def _extract_text(message: Message) -> str:
        """Extract plain text from A2A message parts."""
        parts = []
        for part in message.parts:
            if part.text:
                parts.append(part.text)
            elif part.data:
                import json
                parts.append(f"[Structured Data]: {json.dumps(part.data, indent=2)}")
        return "\n".join(parts).strip()

    def _get_foundry_client(self):
        """Get the Foundry agent client (lazy import)."""
        from services.foundry_agent_client import get_foundry_agent_client
        return get_foundry_agent_client()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def send_message(
        self,
        request: SendMessageRequest,
        blocking: bool = True,
    ) -> Task | Message:
        """
        Process an A2A message via the Foundry hosted agent.

        Creates an A2A task, sends the message to Foundry, and returns
        the completed task with the agent's response as an artifact.

        Args:
            request: The SendMessageRequest with message and configuration
            blocking: If True, wait for task completion before returning

        Returns:
            Task with COMPLETED/FAILED status and response artifacts
        """
        execution_start = perf_counter()
        message = request.message
        client = self._get_foundry_client()

        # Create and track the A2A task
        task = await self.task_store.create_task(
            context_id=message.contextId,
            metadata=request.metadata,
        )
        task.history = [message]
        task.status = TaskStatus(
            state=TaskState.WORKING,
            timestamp=datetime.now(UTC),
        )
        await self.task_store.update_task(task)

        # Extract QPrisma context from message metadata
        media_id = message.metadata.get("media_id") if message.metadata else None
        media_ids = message.metadata.get("media_ids") if message.metadata else None
        user_id = message.metadata.get("user_id") if message.metadata else None
        text_content = self._extract_text(message)

        try:
            logger.info(
                "A2A task routed to Foundry",
                task_id=task.id,
                context_id=task.contextId,
                agent_type=self.agent_type,
            )

            foundry_start = perf_counter()
            result = await client.send_message(
                message=text_content,
                media_id=media_id,
                media_ids=media_ids,
                user_id=user_id,
                session_id=task.contextId,
                thread_id=task.contextId,
            )
            _record_phase_latency(
                "foundry_execution", perf_counter() - foundry_start, self.agent_type
            )

            response_content = result.get("content", "")

            task.artifacts = [
                Artifact(
                    artifactId=str(uuid.uuid4()),
                    name="Agent Response",
                    description="The agent's response to the user's query",
                    parts=[Part(text=response_content)],
                )
            ]
            task.status = TaskStatus(
                state=TaskState.COMPLETED,
                timestamp=datetime.now(UTC),
            )

            # Add agent response to history
            task.history.append(
                Message(
                    messageId=str(uuid.uuid4()),
                    contextId=task.contextId,
                    taskId=task.id,
                    role=Role.AGENT,
                    parts=[Part(text=response_content)],
                )
            )

            persist_start = perf_counter()
            await self.task_store.update_task(task)
            _record_phase_latency(
                "task_persist", perf_counter() - persist_start, self.agent_type
            )

            total_duration = perf_counter() - execution_start
            Metrics.record_graph_execution(
                graph_name=f"a2a_{self.agent_type}",
                duration_seconds=total_duration,
                success=True,
                tool_calls=0,
            )
            logger.info(
                "A2A task completed",
                task_id=task.id,
                context_id=task.contextId,
                duration_ms=round(total_duration * 1000, 2),
            )
            return task

        except Exception as e:
            total_duration = perf_counter() - execution_start
            Metrics.record_graph_execution(
                graph_name=f"a2a_{self.agent_type}",
                duration_seconds=total_duration,
                success=False,
                tool_calls=0,
            )
            logger.error(
                f"A2A task {task.id} failed: {e}",
                task_id=task.id,
                context_id=task.contextId,
                duration_ms=round(total_duration * 1000, 2),
            )

            task.status = TaskStatus(
                state=TaskState.FAILED,
                message=Message(
                    role=Role.AGENT,
                    parts=[Part(text=f"Task failed: {e}")],
                ),
                timestamp=datetime.now(UTC),
            )
            persist_start = perf_counter()
            await self.task_store.update_task(task)
            _record_phase_latency(
                "task_persist", perf_counter() - persist_start, self.agent_type
            )
            return task

    async def send_streaming_message(
        self,
        request: SendMessageRequest,
    ) -> AsyncGenerator[StreamResponse, None]:
        """
        Process a message with streaming via the Foundry hosted agent.

        Yields StreamResponse objects as the task progresses:
        1. Initial Task object with SUBMITTED status
        2. TaskStatusUpdateEvent when status changes to WORKING
        3. TaskArtifactUpdateEvent for incremental response chunks
        4. Final TaskStatusUpdateEvent when COMPLETED or FAILED

        Args:
            request: The SendMessageRequest with message and configuration

        Yields:
            StreamResponse objects wrapping status/artifact updates
        """
        execution_start = perf_counter()
        message = request.message
        client = self._get_foundry_client()

        # Create and track the A2A task
        task = await self.task_store.create_task(
            context_id=message.contextId,
            metadata=request.metadata,
        )
        task.history = [message]
        await self.task_store.update_task(task)

        # Yield initial task
        yield StreamResponse(task=task)

        # Update to working
        task.status = TaskStatus(
            state=TaskState.WORKING,
            timestamp=datetime.now(UTC),
        )
        await self.task_store.update_task(task)

        yield StreamResponse(
            statusUpdate=TaskStatusUpdateEvent(
                taskId=task.id,
                contextId=task.contextId,
                status=task.status,
            )
        )

        # Extract QPrisma context from message metadata
        media_id = message.metadata.get("media_id") if message.metadata else None
        media_ids = message.metadata.get("media_ids") if message.metadata else None
        user_id = message.metadata.get("user_id") if message.metadata else None
        text_content = self._extract_text(message)

        if not media_id:
            logger.warning(
                "A2A streaming: no media_id in message metadata",
                metadata_keys=list(message.metadata.keys()) if message.metadata else [],
            )

        logger.info(
            "A2A streaming started",
            task_id=task.id,
            context_id=task.contextId,
            media_id=media_id,
        )

        artifact_id = str(uuid.uuid4())

        try:
            accumulated_content = ""
            foundry_start = perf_counter()

            async for event in client.send_streaming_message(
                message=text_content,
                media_id=media_id,
                media_ids=media_ids,
                user_id=user_id,
                session_id=task.contextId,
                thread_id=task.contextId,
            ):
                event_type = event.get("type")

                if event_type == "token":
                    chunk = event.get("content", "")
                    accumulated_content += chunk
                    yield StreamResponse(
                        artifactUpdate=TaskArtifactUpdateEvent(
                            taskId=task.id,
                            contextId=task.contextId,
                            artifact=Artifact(
                                artifactId=artifact_id,
                                name="Agent Response",
                                parts=[Part(text=chunk)],
                            ),
                            append=True,
                            lastChunk=False,
                        )
                    )

                elif event_type == "tool_start":
                    yield StreamResponse(
                        statusUpdate=TaskStatusUpdateEvent(
                            taskId=task.id,
                            contextId=task.contextId,
                            status=TaskStatus(
                                state=TaskState.WORKING,
                                message=Message(
                                    role=Role.AGENT,
                                    parts=[
                                        Part(text=f"Using tool: {event.get('name', 'unknown')}")
                                    ],
                                ),
                            ),
                        )
                    )

                elif event_type == "done":
                    accumulated_content = event.get("content", accumulated_content)

                elif event_type == "error":
                    raise RuntimeError(event.get("content", "Foundry streaming error"))

            _record_phase_latency(
                "foundry_execution", perf_counter() - foundry_start, self.agent_type
            )

            # Final artifact with complete content
            if accumulated_content:
                yield StreamResponse(
                    artifactUpdate=TaskArtifactUpdateEvent(
                        taskId=task.id,
                        contextId=task.contextId,
                        artifact=Artifact(
                            artifactId=artifact_id,
                            name="Agent Response",
                            parts=[Part(text=accumulated_content)],
                        ),
                        append=False,
                        lastChunk=True,
                    )
                )
                task.artifacts = [
                    Artifact(
                        artifactId=artifact_id,
                        name="Agent Response",
                        parts=[Part(text=accumulated_content)],
                    )
                ]

            task.status = TaskStatus(
                state=TaskState.COMPLETED,
                timestamp=datetime.now(UTC),
            )

            persist_start = perf_counter()
            await self.task_store.update_task(task)
            _record_phase_latency(
                "task_persist", perf_counter() - persist_start, self.agent_type
            )

            total_duration = perf_counter() - execution_start
            Metrics.record_graph_execution(
                graph_name=f"a2a_stream_{self.agent_type}",
                duration_seconds=total_duration,
                success=True,
                tool_calls=0,
            )
            logger.info(
                "A2A streaming completed",
                task_id=task.id,
                context_id=task.contextId,
                duration_ms=round(total_duration * 1000, 2),
            )

            yield StreamResponse(
                statusUpdate=TaskStatusUpdateEvent(
                    taskId=task.id,
                    contextId=task.contextId,
                    status=task.status,
                )
            )

        except Exception as e:
            total_duration = perf_counter() - execution_start
            Metrics.record_graph_execution(
                graph_name=f"a2a_stream_{self.agent_type}",
                duration_seconds=total_duration,
                success=False,
                tool_calls=0,
            )
            logger.error(
                f"A2A streaming task {task.id} failed: {e}",
                task_id=task.id,
                context_id=task.contextId,
                duration_ms=round(total_duration * 1000, 2),
            )

            task.status = TaskStatus(
                state=TaskState.FAILED,
                message=Message(
                    role=Role.AGENT,
                    parts=[Part(text=f"Task failed: {e}")],
                ),
                timestamp=datetime.now(UTC),
            )
            persist_start = perf_counter()
            await self.task_store.update_task(task)
            _record_phase_latency(
                "task_persist", perf_counter() - persist_start, self.agent_type
            )

            yield StreamResponse(
                statusUpdate=TaskStatusUpdateEvent(
                    taskId=task.id,
                    contextId=task.contextId,
                    status=task.status,
                )
            )

    # ------------------------------------------------------------------
    # Task management (read-only)
    # ------------------------------------------------------------------

    async def get_task(self, task_id: str, history_length: int | None = None) -> Task | None:
        """Get a task by ID."""
        task = await self.task_store.get_task(task_id)

        if task and history_length is not None:
            if history_length == 0:
                task = Task(
                    id=task.id,
                    contextId=task.contextId,
                    status=task.status,
                    artifacts=task.artifacts,
                    metadata=task.metadata,
                )
            elif task.history and len(task.history) > history_length:
                task.history = task.history[-history_length:]

        return task

    async def list_tasks(
        self,
        context_id: str | None = None,
        status: TaskState | None = None,
        page_size: int = 50,
        include_artifacts: bool = False,
    ) -> tuple[list[Task], int]:
        """List tasks with optional filtering."""
        return await self.task_store.list_tasks(
            context_id=context_id,
            status=status,
            page_size=page_size,
            include_artifacts=include_artifacts,
        )

    async def cancel_task(self, task_id: str) -> Task | None:
        """Cancel a task if it's in a cancellable state."""
        return await self.task_store.cancel_task(task_id)
