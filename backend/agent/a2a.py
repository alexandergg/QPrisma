"""
A2A Agent Executor
==================

Bridges LangGraph agents with the A2A (Agent-to-Agent) protocol.
Handles task lifecycle, streaming, and artifact generation.

This module wraps the existing VideoAgentGraph and EditorAgentGraph
to expose them as A2A-compliant servers.

Reference: https://a2a-protocol.org/latest/specification/
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from agent.graphs.editor import create_editor_agent_graph
from agent.state.agent_state import create_agent_state
from agent.graphs.video import create_video_agent_graph
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

logger = logging.getLogger(__name__)


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
                timestamp=datetime.utcnow(),
            )
            self._tasks[task_id] = task
            return task


# Global task store instance
_task_store: TaskStore | None = None


def get_task_store() -> TaskStore:
    """Get or create the global task store."""
    global _task_store
    if _task_store is None:
        _task_store = TaskStore()
    return _task_store


class A2AAgentExecutor:
    """
    A2A-compliant executor for QPrisma agents.
    
    Wraps LangGraph-based agents (VideoAgentGraph, EditorAgentGraph) to provide
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
        agent_type: str = "video",  # "video" or "editor"
        model_deployment: str | None = None,
        checkpointer=None,
    ):
        """
        Initialize the A2A executor.
        
        Args:
            agent_type: Type of agent ("video" for VideoAgentGraph, "editor" for EditorAgentGraph)
            model_deployment: Azure OpenAI deployment name
            checkpointer: LangGraph checkpointer for persistence
        """
        self.agent_type = agent_type
        self.model_deployment = model_deployment
        self.checkpointer = checkpointer
        self.task_store = get_task_store()
        self._graph = None

    @property
    def graph(self):
        """Get or create the appropriate LangGraph agent."""
        if self._graph is None:
            if self.agent_type == "editor":
                self._graph = create_editor_agent_graph(self.checkpointer)
            else:
                self._graph = create_video_agent_graph(self.checkpointer)
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

    def _langchain_message_to_a2a(self, message: AIMessage, task_id: str, context_id: str) -> Message:
        """Convert LangChain AI message to A2A Message."""
        content = message.content if isinstance(message.content, str) else str(message.content)
        
        parts = [Part(text=content)]
        
        # Include tool call info in metadata if present
        metadata = {}
        if hasattr(message, "tool_calls") and message.tool_calls:
            metadata["tool_calls"] = [
                {"name": tc.get("name"), "id": tc.get("id")}
                for tc in message.tool_calls
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
                    tool_result = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
                    
                    if isinstance(tool_result, dict):
                        # Extract from search results
                        for r in tool_result.get("results", []):
                            if isinstance(r, dict) and "timestamp" in r:
                                sources.append({
                                    "timestamp": r.get("timestamp", 0),
                                    "timestamp_formatted": r.get("timestamp_formatted", format_timestamp(r.get("timestamp", 0))),
                                    "type": r.get("type", "unknown"),
                                    "description": r.get("content", r.get("description", ""))[:200],
                                    "score": r.get("score", 0),
                                })
                        
                        # Extract from occurrences
                        for occ in tool_result.get("occurrences", []):
                            if isinstance(occ, dict) and "timestamp" in occ:
                                sources.append({
                                    "timestamp": occ.get("timestamp", 0),
                                    "timestamp_formatted": occ.get("timestamp_formatted", ""),
                                    "type": occ.get("occurrence_type", "entity"),
                                    "description": occ.get("context", "")[:200],
                                })
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
        message = request.message
        config = request.configuration or {}
        
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
            timestamp=datetime.utcnow(),
        )
        await self.task_store.update_task(task)
        
        # Extract metadata from message
        media_id = None
        project_id = None
        if message.metadata:
            media_id = message.metadata.get("media_id")
            project_id = message.metadata.get("project_id")
        
        # Convert message to LangChain format
        lc_message = self._a2a_message_to_langchain(message)
        
        # Build agent state
        state = create_agent_state(
            messages=[lc_message],
            media_id=media_id,
            session_id=task.contextId,
        )
        
        # Run the agent
        from langchain_core.runnables import RunnableConfig
        
        run_config = RunnableConfig(
            configurable={
                "thread_id": task.contextId,
                "media_id": media_id,
                "project_id": project_id,
                "model_deployment": self.model_deployment,
            }
        )
        
        try:
            logger.info(f"A2A executing task {task.id} with message: {message.parts[0].text[:50] if message.parts else ''}...")
            
            result = await self.graph.ainvoke(state, run_config)
            
            # Extract final response
            final_message = result["messages"][-1]
            response_content = final_message.content if hasattr(final_message, "content") else str(final_message)
            
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
                timestamp=datetime.utcnow(),
            )
            
            # Add agent response to history
            agent_msg = self._langchain_message_to_a2a(final_message, task.id, task.contextId)
            task.history.append(agent_msg)
            
            await self.task_store.update_task(task)
            
            logger.info(f"A2A task {task.id} completed successfully")
            return task
            
        except Exception as e:
            logger.error(f"A2A task {task.id} failed: {e}")
            
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message=Message(
                    role=Role.AGENT,
                    parts=[Part(text=f"Task failed: {str(e)}")],
                ),
                timestamp=datetime.utcnow(),
            )
            await self.task_store.update_task(task)
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
            timestamp=datetime.utcnow(),
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
        project_id = message.metadata.get("project_id") if message.metadata else None
        
        # Convert message
        lc_message = self._a2a_message_to_langchain(message)
        
        # Build state
        state = create_agent_state(
            messages=[lc_message],
            media_id=media_id,
            session_id=task.contextId,
        )
        
        from langchain_core.runnables import RunnableConfig
        
        run_config = RunnableConfig(
            configurable={
                "thread_id": task.contextId,
                "media_id": media_id,
                "project_id": project_id,
                "model_deployment": self.model_deployment,
            }
        )
        
        try:
            # Stream events from the graph
            accumulated_content = ""
            artifact_id = str(uuid.uuid4())
            
            async for event in self.graph.astream_events(state, run_config, version="v2"):
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
                timestamp=datetime.utcnow(),
            )
            await self.task_store.update_task(task)
            
            yield StreamResponse(
                statusUpdate=TaskStatusUpdateEvent(
                    taskId=task.id,
                    contextId=task.contextId,
                    status=task.status,
                )
            )
            
        except Exception as e:
            logger.error(f"A2A streaming task {task.id} failed: {e}")
            
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message=Message(
                    role=Role.AGENT,
                    parts=[Part(text=f"Task failed: {str(e)}")],
                ),
                timestamp=datetime.utcnow(),
            )
            await self.task_store.update_task(task)
            
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
_editor_executor: A2AAgentExecutor | None = None


def get_video_a2a_executor() -> A2AAgentExecutor:
    """Get the singleton video agent A2A executor."""
    global _video_executor
    if _video_executor is None:
        _video_executor = A2AAgentExecutor(agent_type="video")
    return _video_executor


def get_editor_a2a_executor() -> A2AAgentExecutor:
    """Get the singleton editor agent A2A executor."""
    global _editor_executor
    if _editor_executor is None:
        _editor_executor = A2AAgentExecutor(agent_type="editor")
    return _editor_executor
