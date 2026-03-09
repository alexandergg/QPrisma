"""
A2A Agent Executor
==================

Bridges LangGraph agents with the A2A (Agent-to-Agent) protocol.
Handles task lifecycle, streaming, and artifact generation.

This module wraps the existing VideoAgentGraph
to expose it as an A2A-compliant server.

Reference: https://a2a-protocol.org/latest/specification/
"""

import asyncio
import inspect
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from agent.graphs.video import create_production_checkpointer, create_video_agent_graph
from agent.state.agent_state import create_agent_state
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
from services.database_service import DatabaseService, get_database_service

logger = get_logger(__name__)


def _record_phase_latency(phase: str, duration_seconds: float, agent_type: str) -> None:
    """Record standardized A2A phase latency metric."""
    Metrics.observe_histogram(
        "a2a_phase_latency_seconds",
        duration_seconds,
        labels={"phase": phase, "agent": agent_type},
    )


_shared_checkpointer: Any | None = None
_shared_checkpointer_cm: Any | None = None
_checkpointer_lock = asyncio.Lock()


async def _maybe_call_setup(checkpointer: Any) -> None:
    """Call saver setup() if available (sync or async)."""
    setup_fn = getattr(checkpointer, "setup", None)
    if setup_fn is None:
        return

    try:
        result = setup_fn()
        if inspect.isawaitable(result):
            await result
    except Exception as exc:
        logger.warning(f"Checkpointer setup failed, continuing without setup: {exc}")


async def _materialize_checkpointer(candidate: Any) -> Any:
    """
    Materialize checkpointer instances that may be returned as context managers.

    Supports:
    - direct saver instances
    - sync context managers via __enter__
    - async context managers via __aenter__
    """
    global _shared_checkpointer_cm

    if candidate is None:
        return None

    if hasattr(candidate, "__aenter__") and hasattr(candidate, "__aexit__"):
        _shared_checkpointer_cm = candidate
        saver = await candidate.__aenter__()
        await _maybe_call_setup(saver)
        return saver

    if hasattr(candidate, "__enter__") and hasattr(candidate, "__exit__"):
        _shared_checkpointer_cm = candidate
        saver = candidate.__enter__()
        await _maybe_call_setup(saver)
        return saver

    await _maybe_call_setup(candidate)
    return candidate


async def get_shared_checkpointer() -> Any:
    """
    Get a singleton shared checkpointer for all A2A executors.

    Preference order follows production factory:
    PostgreSQL > Redis > MemorySaver fallback.
    """
    global _shared_checkpointer
    start = perf_counter()

    if _shared_checkpointer is not None:
        return _shared_checkpointer

    async with _checkpointer_lock:
        if _shared_checkpointer is not None:
            return _shared_checkpointer

        try:
            candidate = create_production_checkpointer()
            materialized = await _materialize_checkpointer(candidate)
            if materialized is None:
                raise RuntimeError("Production checkpointer factory returned None")

            _shared_checkpointer = materialized
            logger.info(
                "A2A shared checkpointer initialized",
                checkpointer_type=type(_shared_checkpointer).__name__,
            )
            _record_phase_latency(
                "checkpointer_init",
                perf_counter() - start,
                "shared",
            )
            return _shared_checkpointer
        except Exception as exc:
            logger.warning(f"Falling back to MemorySaver for A2A checkpointer: {exc}")
            _shared_checkpointer = MemorySaver()
            _record_phase_latency(
                "checkpointer_init",
                perf_counter() - start,
                "shared",
            )
            return _shared_checkpointer


class TaskStore:
    """
    In-memory task store for A2A task management.

    In production, this should be replaced with a persistent store
    (Redis, PostgreSQL, etc.) for durability and multi-instance support.
    """

    def __init__(self):
        self._tasks: dict[str, Task] = {}
        self._context_tasks: dict[str, list[str]] = {}  # contextId -> [taskIds]
        self._lock = asyncio.Lock()

    async def create_task(
        self,
        context_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Task:
        """Create a new task."""
        async with self._lock:
            task = Task(
                id=str(uuid.uuid4()),
                contextId=context_id or str(uuid.uuid4()),
                status=TaskStatus(state=TaskState.SUBMITTED),
                artifacts=[],
                history=[],
                metadata=metadata or {},
            )
            self._tasks[task.id] = task

            # Track by context
            if task.contextId not in self._context_tasks:
                self._context_tasks[task.contextId] = []
            self._context_tasks[task.contextId].append(task.id)

            return task

    async def get_task(self, task_id: str) -> Task | None:
        """Get a task by ID."""
        return self._tasks.get(task_id)

    async def update_task(self, task: Task) -> Task:
        """Update a task."""
        async with self._lock:
            self._tasks[task.id] = task
            return task

    async def list_tasks(
        self,
        context_id: str | None = None,
        status: TaskState | None = None,
        page_size: int = 50,
        include_artifacts: bool = False,
    ) -> tuple[list[Task], int]:
        """List tasks with optional filtering."""
        tasks = list(self._tasks.values())

        if context_id:
            task_ids = self._context_tasks.get(context_id, [])
            tasks = [t for t in tasks if t.id in task_ids]

        if status:
            tasks = [t for t in tasks if t.status.state == status]

        # Sort by timestamp descending
        tasks.sort(
            key=lambda t: t.status.timestamp or datetime.min,
            reverse=True,
        )

        total = len(tasks)
        tasks = tasks[:page_size]

        if not include_artifacts:
            # Strip artifacts for response size
            tasks = [
                Task(
                    id=t.id,
                    contextId=t.contextId,
                    status=t.status,
                    history=t.history,
                    metadata=t.metadata,
                )
                for t in tasks
            ]

        return tasks, total

    async def cancel_task(self, task_id: str) -> Task | None:
        """Cancel a task if possible."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None

            # Check if cancellable
            terminal_states = {
                TaskState.COMPLETED,
                TaskState.FAILED,
                TaskState.CANCELED,
                TaskState.REJECTED,
            }
            if task.status.state in terminal_states:
                return None  # Not cancellable

            task.status = TaskStatus(
                state=TaskState.CANCELED,
                timestamp=datetime.now(UTC),
            )
            self._tasks[task_id] = task
            return task


class PersistentTaskStore:
    """PostgreSQL-backed task store for durable A2A task lifecycle state."""

    def __init__(self, db: DatabaseService):
        self._db = db
        self._lock = asyncio.Lock()

    @staticmethod
    def _task_to_row(task: Task) -> dict[str, Any]:
        return {
            "id": task.id,
            "context_id": task.contextId,
            "status_state": str(task.status.state),
            "status_timestamp": task.status.timestamp,
            "status_payload": task.status.model_dump(mode="json"),
            "artifacts": [a.model_dump(mode="json") for a in (task.artifacts or [])],
            "history": [m.model_dump(mode="json") for m in (task.history or [])],
            "task_metadata": task.metadata or {},
        }

    @staticmethod
    def _row_to_task(row: Any, include_artifacts: bool = True) -> Task:
        status_payload = row.status_payload or {"state": TaskState.SUBMITTED}
        artifacts_payload = row.artifacts if include_artifacts else None

        return Task.model_validate(
            {
                "id": row.id,
                "contextId": row.context_id,
                "status": status_payload,
                "artifacts": artifacts_payload,
                "history": row.history,
                "metadata": row.task_metadata,
            }
        )

    async def create_task(
        self,
        context_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Task:
        start = perf_counter()
        task = Task(
            id=str(uuid.uuid4()),
            contextId=context_id or str(uuid.uuid4()),
            status=TaskStatus(state=TaskState.SUBMITTED),
            artifacts=[],
            history=[],
            metadata=metadata or {},
        )

        async with self._lock:
            await asyncio.to_thread(self._db.upsert_a2a_task, self._task_to_row(task))
            _record_phase_latency("task_persist", perf_counter() - start, "persistent_store")
            return task

    async def get_task(self, task_id: str) -> Task | None:
        row = await asyncio.to_thread(self._db.get_a2a_task, task_id)
        if not row:
            return None
        return self._row_to_task(row)

    async def update_task(self, task: Task) -> Task:
        start = perf_counter()
        async with self._lock:
            await asyncio.to_thread(self._db.upsert_a2a_task, self._task_to_row(task))
            _record_phase_latency("task_persist", perf_counter() - start, "persistent_store")
            return task

    async def list_tasks(
        self,
        context_id: str | None = None,
        status: TaskState | None = None,
        page_size: int = 50,
        include_artifacts: bool = False,
    ) -> tuple[list[Task], int]:
        rows, total = await asyncio.to_thread(
            self._db.list_a2a_tasks,
            context_id,
            str(status) if status is not None else None,
            page_size,
        )
        tasks = [self._row_to_task(row, include_artifacts=include_artifacts) for row in rows]
        return tasks, total

    async def cancel_task(self, task_id: str) -> Task | None:
        async with self._lock:
            task = await self.get_task(task_id)
            if not task:
                return None

            terminal_states = {
                TaskState.COMPLETED,
                TaskState.FAILED,
                TaskState.CANCELED,
                TaskState.REJECTED,
            }
            if task.status.state in terminal_states:
                return None

            task.status = TaskStatus(
                state=TaskState.CANCELED,
                timestamp=datetime.now(UTC),
            )
            persist_start = perf_counter()
            await asyncio.to_thread(self._db.upsert_a2a_task, self._task_to_row(task))
            _record_phase_latency(
                "task_persist", perf_counter() - persist_start, "persistent_store"
            )
            return task


# Global task store instance
_task_store: TaskStore | PersistentTaskStore | None = None


def get_task_store() -> TaskStore | PersistentTaskStore:
    """Get or create the global task store."""
    global _task_store
    if _task_store is None:
        try:
            db = get_database_service()
            health = db.health_check()
            if health.get("status") == "healthy":
                _task_store = PersistentTaskStore(db)
                logger.info("Using persistent PostgreSQL A2A TaskStore")
            else:
                logger.warning("Database not healthy, using in-memory A2A TaskStore fallback")
                _task_store = TaskStore()
        except Exception as exc:
            logger.warning(f"Failed to initialize persistent A2A TaskStore: {exc}")
            _task_store = TaskStore()
    return _task_store


class A2AAgentExecutor:
    """
    A2A-compliant executor for QPrisma agents.

    Wraps the LangGraph-based VideoAgentGraph to provide
    A2A protocol operations including:
    - SendMessage (sync and streaming)
    - GetTask / ListTasks
    - CancelTask
    - Task lifecycle management

    The executor translates between A2A Message/Task objects and the internal
    LangGraph agent state/messages.
    """

    def __init__(
        self,
        model_deployment: str | None = None,
        checkpointer=None,
    ):
        """
        Initialize the A2A executor.

        Args:
            model_deployment: Azure OpenAI deployment name
            checkpointer: LangGraph checkpointer for persistence
        """
        self.agent_type = "video"
        self.model_deployment = model_deployment
        self.checkpointer = checkpointer
        self.task_store = get_task_store()
        self._graph = None
        self._graph_lock = asyncio.Lock()

    async def _get_graph(self):
        """Get or create the appropriate LangGraph agent with persistent checkpointer."""
        if self._graph is not None:
            return self._graph

        async with self._graph_lock:
            if self._graph is not None:
                return self._graph

            resolved_checkpointer = self.checkpointer
            if resolved_checkpointer is None:
                resolved_checkpointer = await get_shared_checkpointer()

            self._graph = create_video_agent_graph(resolved_checkpointer)

            return self._graph

    def _a2a_message_to_langchain(self, message: Message) -> HumanMessage | AIMessage:
        """Convert A2A Message to LangChain message."""
        # Extract text content from parts
        text_content = ""
        for part in message.parts:
            if part.text:
                text_content += part.text + "\n"
            elif part.data:
                import json

                text_content += f"\n[Structured Data]: {json.dumps(part.data, indent=2)}\n"

        text_content = text_content.strip()

        if message.role == Role.USER:
            return HumanMessage(content=text_content)
        else:
            return AIMessage(content=text_content)

    def _langchain_message_to_a2a(
        self, message: AIMessage, task_id: str, context_id: str
    ) -> Message:
        """Convert LangChain AI message to A2A Message."""
        content = message.content if isinstance(message.content, str) else str(message.content)

        parts = [Part(text=content)]

        # Include tool call info in metadata if present
        metadata = {}
        if hasattr(message, "tool_calls") and message.tool_calls:
            metadata["tool_calls"] = [
                {"name": tc.get("name"), "id": tc.get("id")} for tc in message.tool_calls
            ]

        return Message(
            messageId=str(uuid.uuid4()),
            contextId=context_id,
            taskId=task_id,
            role=Role.AGENT,
            parts=parts,
            metadata=metadata if metadata else None,
        )

    def _extract_sources_artifact(
        self,
        result: dict[str, Any],
        task_id: str,
        context_id: str,
    ) -> Artifact | None:
        """Extract sources/references from agent result as an artifact."""
        from agent.utils.formatting import format_timestamp

        sources = []

        # Extract from messages looking for tool results
        for msg in result.get("messages", []):
            if hasattr(msg, "name") and hasattr(msg, "content"):
                try:
                    import json

                    tool_result = (
                        json.loads(msg.content) if isinstance(msg.content, str) else msg.content
                    )

                    if isinstance(tool_result, dict):
                        # Extract from search results
                        for r in tool_result.get("results", []):
                            if isinstance(r, dict) and "timestamp" in r:
                                sources.append(
                                    {
                                        "timestamp": r.get("timestamp", 0),
                                        "timestamp_formatted": r.get(
                                            "timestamp_formatted",
                                            format_timestamp(r.get("timestamp", 0)),
                                        ),
                                        "type": r.get("type", "unknown"),
                                        "description": r.get("content", r.get("description", ""))[
                                            :200
                                        ],
                                        "score": r.get("score", 0),
                                    }
                                )

                        # Extract from occurrences
                        for occ in tool_result.get("occurrences", []):
                            if isinstance(occ, dict) and "timestamp" in occ:
                                sources.append(
                                    {
                                        "timestamp": occ.get("timestamp", 0),
                                        "timestamp_formatted": occ.get("timestamp_formatted", ""),
                                        "type": occ.get("occurrence_type", "entity"),
                                        "description": occ.get("context", "")[:200],
                                    }
                                )
                except Exception:
                    pass

        if not sources:
            return None

        # Deduplicate and sort by timestamp
        seen = set()
        unique_sources = []
        for s in sources:
            key = (s.get("timestamp"), s.get("type"), s.get("description", "")[:50])
            if key not in seen:
                seen.add(key)
                unique_sources.append(s)

        unique_sources.sort(key=lambda x: x.get("timestamp", 0))

        return Artifact(
            artifactId=str(uuid.uuid4()),
            name="Video Sources",
            description="Timestamps and sources referenced in the response",
            parts=[Part(data={"sources": unique_sources[:20]})],  # Limit to 20
            metadata={"taskId": task_id, "contextId": context_id},
        )

    async def send_message(
        self,
        request: SendMessageRequest,
        blocking: bool = True,
    ) -> Task | Message:
        """
        Process a message and return a Task or direct Message response.

        For simple queries, may return a Message directly.
        For complex tasks, returns a Task object with status.

        Args:
            request: The SendMessageRequest with message and configuration
            blocking: If True, wait for task completion before returning

        Returns:
            Task or Message depending on the complexity of the request
        """
        execution_start = perf_counter()
        message = request.message

        # Create task
        task = await self.task_store.create_task(
            context_id=message.contextId,
            metadata=request.metadata,
        )

        # Add message to history
        task.history = [message]

        # Update status to working
        task.status = TaskStatus(
            state=TaskState.WORKING,
            timestamp=datetime.now(UTC),
        )
        await self.task_store.update_task(task)

        # Extract metadata from message
        media_id = None
        media_ids = None
        if message.metadata:
            media_id = message.metadata.get("media_id")
            media_ids = message.metadata.get("media_ids")

        # Convert message to LangChain format
        lc_message = self._a2a_message_to_langchain(message)

        # Build agent state
        state = create_agent_state(
            messages=[lc_message],
            media_id=media_id,
            media_ids=media_ids,
            session_id=task.contextId,
        )

        # Run the agent
        from langchain_core.runnables import RunnableConfig

        run_config = RunnableConfig(
            configurable={
                "thread_id": task.contextId,
                "media_id": media_id,
                "media_ids": media_ids,
                "model_deployment": self.model_deployment,
            }
        )

        try:
            logger.info(
                "A2A task execution started",
                task_id=task.id,
                context_id=task.contextId,
                agent_type=self.agent_type,
            )

            graph_ready_start = perf_counter()
            graph = await self._get_graph()
            _record_phase_latency(
                "graph_ready", perf_counter() - graph_ready_start, self.agent_type
            )

            model_start = perf_counter()
            result = await graph.ainvoke(state, run_config)
            _record_phase_latency("model_execution", perf_counter() - model_start, self.agent_type)

            # Extract final response
            final_message = result["messages"][-1]
            response_content = (
                final_message.content if hasattr(final_message, "content") else str(final_message)
            )

            # Create response artifact
            response_artifact = Artifact(
                artifactId=str(uuid.uuid4()),
                name="Agent Response",
                description="The agent's response to the user's query",
                parts=[Part(text=response_content)],
            )

            task.artifacts = [response_artifact]

            # Extract sources artifact if available
            sources_artifact = self._extract_sources_artifact(result, task.id, task.contextId)
            if sources_artifact:
                task.artifacts.append(sources_artifact)

            # Update task status to completed
            task.status = TaskStatus(
                state=TaskState.COMPLETED,
                timestamp=datetime.now(UTC),
            )

            # Add agent response to history
            agent_msg = self._langchain_message_to_a2a(final_message, task.id, task.contextId)
            task.history.append(agent_msg)

            persist_start = perf_counter()
            await self.task_store.update_task(task)
            _record_phase_latency("task_persist", perf_counter() - persist_start, self.agent_type)

            total_duration = perf_counter() - execution_start
            Metrics.record_graph_execution(
                graph_name=f"a2a_{self.agent_type}",
                duration_seconds=total_duration,
                success=True,
                tool_calls=0,
            )
            logger.info(
                "A2A task execution completed",
                task_id=task.id,
                context_id=task.contextId,
                agent_type=self.agent_type,
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
                agent_type=self.agent_type,
                duration_ms=round(total_duration * 1000, 2),
            )

            task.status = TaskStatus(
                state=TaskState.FAILED,
                message=Message(
                    role=Role.AGENT,
                    parts=[Part(text=f"Task failed: {str(e)}")],
                ),
                timestamp=datetime.now(UTC),
            )
            persist_start = perf_counter()
            await self.task_store.update_task(task)
            _record_phase_latency("task_persist", perf_counter() - persist_start, self.agent_type)
            return task

    async def send_streaming_message(
        self,
        request: SendMessageRequest,
    ) -> AsyncGenerator[StreamResponse, None]:
        """
        Process a message with streaming updates.

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

        # Create task
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

        # Extract metadata
        media_id = message.metadata.get("media_id") if message.metadata else None
        media_ids = message.metadata.get("media_ids") if message.metadata else None

        logger.info(
            "A2A streaming started",
            task_id=task.id,
            context_id=task.contextId,
            agent_type=self.agent_type,
            media_id=media_id,
        )

        # Convert message
        lc_message = self._a2a_message_to_langchain(message)

        # Build state
        state = create_agent_state(
            messages=[lc_message],
            media_id=media_id,
            media_ids=media_ids,
            session_id=task.contextId,
        )

        from langchain_core.runnables import RunnableConfig

        run_config = RunnableConfig(
            configurable={
                "thread_id": task.contextId,
                "media_id": media_id,
                "media_ids": media_ids,
                "model_deployment": self.model_deployment,
            }
        )

        try:
            # Stream events from the graph
            accumulated_content = ""
            artifact_id = str(uuid.uuid4())
            graph_ready_start = perf_counter()
            graph = await self._get_graph()
            _record_phase_latency(
                "graph_ready", perf_counter() - graph_ready_start, self.agent_type
            )

            model_start = perf_counter()

            async for event in graph.astream_events(state, run_config, version="v2"):
                kind = event.get("event")

                # Stream token-by-token from LLM
                if kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        accumulated_content += chunk.content

                        # Yield artifact update with streaming chunk
                        yield StreamResponse(
                            artifactUpdate=TaskArtifactUpdateEvent(
                                taskId=task.id,
                                contextId=task.contextId,
                                artifact=Artifact(
                                    artifactId=artifact_id,
                                    name="Agent Response",
                                    parts=[Part(text=chunk.content)],
                                ),
                                append=True,
                                lastChunk=False,
                            )
                        )

                # Tool execution events
                elif kind == "on_tool_start":
                    tool_name = event.get("name", "unknown")
                    yield StreamResponse(
                        statusUpdate=TaskStatusUpdateEvent(
                            taskId=task.id,
                            contextId=task.contextId,
                            status=TaskStatus(
                                state=TaskState.WORKING,
                                message=Message(
                                    role=Role.AGENT,
                                    parts=[Part(text=f"Using tool: {tool_name}")],
                                ),
                            ),
                        )
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

            # Complete
            task.status = TaskStatus(
                state=TaskState.COMPLETED,
                timestamp=datetime.now(UTC),
            )
            _record_phase_latency("model_execution", perf_counter() - model_start, self.agent_type)

            persist_start = perf_counter()
            await self.task_store.update_task(task)
            _record_phase_latency("task_persist", perf_counter() - persist_start, self.agent_type)

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
                agent_type=self.agent_type,
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
                agent_type=self.agent_type,
                duration_ms=round(total_duration * 1000, 2),
            )

            task.status = TaskStatus(
                state=TaskState.FAILED,
                message=Message(
                    role=Role.AGENT,
                    parts=[Part(text=f"Task failed: {str(e)}")],
                ),
                timestamp=datetime.now(UTC),
            )
            persist_start = perf_counter()
            await self.task_store.update_task(task)
            _record_phase_latency("task_persist", perf_counter() - persist_start, self.agent_type)

            yield StreamResponse(
                statusUpdate=TaskStatusUpdateEvent(
                    taskId=task.id,
                    contextId=task.contextId,
                    status=task.status,
                )
            )

    async def get_task(self, task_id: str, history_length: int | None = None) -> Task | None:
        """Get a task by ID."""
        task = await self.task_store.get_task(task_id)

        if task and history_length is not None:
            # Trim history if requested
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


# =============================================================================
# Factory Functions
# =============================================================================


_video_executor: A2AAgentExecutor | None = None


def get_video_a2a_executor() -> A2AAgentExecutor:
    """Get the singleton video agent A2A executor."""
    global _video_executor
    if _video_executor is None:
        _video_executor = A2AAgentExecutor()
    return _video_executor
