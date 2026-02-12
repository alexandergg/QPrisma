"""
Agent Observability Utilities
=============================

Structured logging, metrics, and tracing for LangGraph agents.

Features:
- Correlation ID propagation through graph execution
- Structured JSON logging with context
- Prometheus metrics for monitoring
- Request context management
"""

import logging
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from typing import Any

# =============================================================================
# Context Variables for Request Tracking
# =============================================================================

# Context variable for request-scoped data
_request_context: ContextVar[dict[str, Any] | None] = ContextVar("request_context", default=None)


@dataclass
class RequestContext:
    """
    Request context that flows through the entire graph execution.

    Provides correlation IDs and metadata for structured logging and tracing.
    """

    request_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    user_id: str | None = None
    session_id: str | None = None
    media_id: str | None = None
    project_id: str | None = None
    start_time: float = field(default_factory=time.time)

    # Execution tracking
    node_path: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for logging."""
        return {
            "request_id": self.request_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "media_id": self.media_id,
            "project_id": self.project_id,
            "elapsed_ms": int((time.time() - self.start_time) * 1000),
            "node_count": len(self.node_path),
            "tool_call_count": len(self.tool_calls),
            "error_count": len(self.errors),
        }

    def add_node(self, node_name: str) -> None:
        """Track node execution."""
        self.node_path.append(node_name)

    def add_tool_call(self, tool_name: str, duration_ms: float, success: bool) -> None:
        """Track tool call."""
        self.tool_calls.append(
            {
                "tool": tool_name,
                "duration_ms": duration_ms,
                "success": success,
                "timestamp": time.time(),
            }
        )

    def add_error(self, error: str, node: str | None = None) -> None:
        """Track error."""
        self.errors.append(
            {
                "error": error,
                "node": node,
                "timestamp": time.time(),
            }
        )


def get_request_context() -> RequestContext:
    """Get current request context or create a new one."""
    ctx = _request_context.get() or {}
    if not ctx or "context" not in ctx:
        return RequestContext()
    return ctx["context"]


def set_request_context(context: RequestContext) -> None:
    """Set request context for current execution."""
    _request_context.set({"context": context})


@contextmanager
def request_context(
    user_id: str | None = None,
    session_id: str | None = None,
    media_id: str | None = None,
    project_id: str | None = None,
    request_id: str | None = None,
):
    """
    Context manager for request-scoped logging and tracking.

    Usage:
        with request_context(user_id="user-123", media_id="vid-456") as ctx:
            result = await agent.run(message)
            # All logs within this block will include request_id, user_id, etc.
    """
    ctx = RequestContext(
        request_id=request_id or str(uuid.uuid4())[:8],
        user_id=user_id,
        session_id=session_id,
        media_id=media_id,
        project_id=project_id,
    )
    token = _request_context.set({"context": ctx})
    try:
        yield ctx
    finally:
        _request_context.reset(token)


# =============================================================================
# Structured Logger
# =============================================================================


class StructuredLogger:
    """
    Structured logger that automatically includes request context.

    All log messages include:
    - request_id: Correlation ID for tracing
    - user_id, session_id: User context
    - node: Current graph node (if applicable)
    - Additional structured fields
    """

    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.name = name

    def _log(self, level: int, message: str, **kwargs) -> None:
        """Internal log method with context injection."""
        ctx = get_request_context()

        # Build structured log data
        log_data = {
            "request_id": ctx.request_id,
            "user_id": ctx.user_id,
            "session_id": ctx.session_id,
            "elapsed_ms": int((time.time() - ctx.start_time) * 1000),
            **kwargs,
        }

        # Format as structured log
        extra_str = " ".join(f"{k}={v}" for k, v in log_data.items() if v is not None)
        self.logger.log(level, f"{message} | {extra_str}")

    def debug(self, message: str, **kwargs) -> None:
        self._log(logging.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs) -> None:
        self._log(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs) -> None:
        self._log(logging.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs) -> None:
        ctx = get_request_context()
        ctx.add_error(message, kwargs.get("node"))
        self._log(logging.ERROR, message, **kwargs)

    def tool_start(self, tool_name: str, **kwargs) -> None:
        """Log tool execution start."""
        self.info(f"Tool starting: {tool_name}", tool=tool_name, event="tool_start", **kwargs)

    def tool_end(self, tool_name: str, duration_ms: float, success: bool, **kwargs) -> None:
        """Log tool execution end."""
        ctx = get_request_context()
        ctx.add_tool_call(tool_name, duration_ms, success)

        level = logging.INFO if success else logging.WARNING
        self._log(
            level,
            f"Tool completed: {tool_name}",
            tool=tool_name,
            event="tool_end",
            duration_ms=round(duration_ms, 2),
            success=success,
            **kwargs,
        )

    def node_start(self, node_name: str, **kwargs) -> None:
        """Log node execution start."""
        ctx = get_request_context()
        ctx.add_node(node_name)
        self.debug(f"Node starting: {node_name}", node=node_name, event="node_start", **kwargs)

    def node_end(self, node_name: str, duration_ms: float, **kwargs) -> None:
        """Log node execution end."""
        self.debug(
            f"Node completed: {node_name}",
            node=node_name,
            event="node_end",
            duration_ms=round(duration_ms, 2),
            **kwargs,
        )

    def graph_start(self, graph_name: str, **kwargs) -> None:
        """Log graph execution start."""
        self.info(f"Graph starting: {graph_name}", graph=graph_name, event="graph_start", **kwargs)

    def graph_end(self, graph_name: str, duration_ms: float, success: bool, **kwargs) -> None:
        """Log graph execution end."""
        ctx = get_request_context()
        self.info(
            f"Graph completed: {graph_name}",
            graph=graph_name,
            event="graph_end",
            duration_ms=round(duration_ms, 2),
            success=success,
            tool_calls=len(ctx.tool_calls),
            nodes_visited=len(ctx.node_path),
            **kwargs,
        )


def get_logger(name: str) -> StructuredLogger:
    """Get a structured logger for the given module."""
    return StructuredLogger(name)


# =============================================================================
# Prometheus Metrics
# =============================================================================

# Metrics storage (in production, use prometheus_client)
_metrics: dict[str, Any] = {
    "counters": {},
    "histograms": {},
    "gauges": {},
}


class Metrics:
    """
    Prometheus-style metrics for agent observability.

    In production, replace with prometheus_client library.
    This implementation provides the interface for easy migration.
    """

    # Tool metrics
    TOOL_CALLS_TOTAL = "agent_tool_calls_total"
    TOOL_CALL_DURATION = "agent_tool_call_duration_seconds"
    TOOL_CALL_ERRORS = "agent_tool_call_errors_total"

    # Graph metrics
    GRAPH_EXECUTIONS_TOTAL = "agent_graph_executions_total"
    GRAPH_EXECUTION_DURATION = "agent_graph_execution_duration_seconds"
    GRAPH_ERRORS_TOTAL = "agent_graph_errors_total"

    # Node metrics
    NODE_EXECUTIONS_TOTAL = "agent_node_executions_total"
    NODE_EXECUTION_DURATION = "agent_node_execution_duration_seconds"

    # Iteration metrics
    TOOL_ITERATIONS = "agent_tool_iterations"
    ERROR_RECOVERIES = "agent_error_recoveries_total"

    # Memory metrics
    MEMORY_RETRIEVAL_DURATION = "agent_memory_retrieval_duration_seconds"
    MEMORY_RETRIEVAL_ERRORS = "agent_memory_retrieval_errors_total"
    MEMORY_CANDIDATES = "agent_memory_candidates"
    MEMORY_SNIPPETS_INJECTED = "agent_memory_snippets_injected"
    MEMORY_BUDGET_CHARS = "agent_memory_budget_chars"

    # Artifact rehydration metrics
    ARTIFACT_REHYDRATION_DURATION = "agent_artifact_rehydration_duration_seconds"
    ARTIFACT_REHYDRATION_ATTEMPTS = "agent_artifact_rehydration_attempts_total"
    ARTIFACT_REHYDRATION_SUCCESSES = "agent_artifact_rehydration_successes_total"
    ARTIFACT_REHYDRATION_ERRORS = "agent_artifact_rehydration_errors_total"

    @classmethod
    def inc_counter(cls, name: str, labels: dict[str, str] | None = None, value: float = 1) -> None:
        """Increment a counter metric."""
        key = cls._make_key(name, labels)
        if key not in _metrics["counters"]:
            _metrics["counters"][key] = 0
        _metrics["counters"][key] += value

    @classmethod
    def observe_histogram(
        cls, name: str, value: float, labels: dict[str, str] | None = None
    ) -> None:
        """Record a histogram observation."""
        key = cls._make_key(name, labels)
        if key not in _metrics["histograms"]:
            _metrics["histograms"][key] = []
        _metrics["histograms"][key].append(value)

    @classmethod
    def set_gauge(cls, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """Set a gauge metric."""
        key = cls._make_key(name, labels)
        _metrics["gauges"][key] = value

    @classmethod
    def _make_key(cls, name: str, labels: dict[str, str] | None) -> str:
        """Create a unique key for a metric with labels."""
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    @classmethod
    def get_all(cls) -> dict[str, Any]:
        """Get all metrics (for testing/debugging)."""
        return _metrics.copy()

    @classmethod
    def reset(cls) -> None:
        """Reset all metrics (for testing)."""
        _metrics["counters"] = {}
        _metrics["histograms"] = {}
        _metrics["gauges"] = {}

    # Convenience methods

    @classmethod
    def record_tool_call(
        cls,
        tool_name: str,
        duration_seconds: float,
        success: bool,
        agent_type: str = "video",
    ) -> None:
        """Record a tool call with all relevant metrics."""
        labels = {"tool": tool_name, "agent": agent_type}

        cls.inc_counter(cls.TOOL_CALLS_TOTAL, labels)
        cls.observe_histogram(cls.TOOL_CALL_DURATION, duration_seconds, labels)

        if not success:
            cls.inc_counter(cls.TOOL_CALL_ERRORS, labels)

    @classmethod
    def record_graph_execution(
        cls,
        graph_name: str,
        duration_seconds: float,
        success: bool,
        tool_calls: int,
    ) -> None:
        """Record a graph execution with all relevant metrics."""
        labels = {"graph": graph_name}

        cls.inc_counter(cls.GRAPH_EXECUTIONS_TOTAL, labels)
        cls.observe_histogram(cls.GRAPH_EXECUTION_DURATION, duration_seconds, labels)
        cls.observe_histogram(cls.TOOL_ITERATIONS, tool_calls, labels)

        if not success:
            cls.inc_counter(cls.GRAPH_ERRORS_TOTAL, labels)

    @classmethod
    def record_node_execution(
        cls,
        node_name: str,
        duration_seconds: float,
        graph_name: str = "video",
    ) -> None:
        """Record a node execution."""
        labels = {"node": node_name, "graph": graph_name}

        cls.inc_counter(cls.NODE_EXECUTIONS_TOTAL, labels)
        cls.observe_histogram(cls.NODE_EXECUTION_DURATION, duration_seconds, labels)


# =============================================================================
# Decorators for Instrumentation
# =============================================================================


def instrument_node(node_name: str, graph_name: str = "video"):
    """
    Decorator to instrument a LangGraph node with logging and metrics.

    Usage:
        @instrument_node("call_model", "video")
        async def call_model(state, config):
            ...
    """

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            logger = get_logger(f"agent.nodes.{node_name}")
            start_time = time.time()

            logger.node_start(node_name)

            try:
                result = await func(*args, **kwargs)
                duration_ms = (time.time() - start_time) * 1000

                logger.node_end(node_name, duration_ms)
                Metrics.record_node_execution(node_name, duration_ms / 1000, graph_name)

                return result

            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                logger.error(f"Node failed: {e}", node=node_name, duration_ms=duration_ms)
                raise

        return wrapper

    return decorator


def instrument_tool(tool_name: str, agent_type: str = "video"):
    """
    Decorator to instrument a tool with logging and metrics.

    Usage:
        @instrument_tool("search_video")
        @tool
        async def search_video(...):
            ...
    """

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            logger = get_logger(f"agent.tools.{tool_name}")
            start_time = time.time()

            logger.tool_start(tool_name)

            try:
                result = await func(*args, **kwargs)
                duration_ms = (time.time() - start_time) * 1000

                # Check if result indicates error
                success = True
                if isinstance(result, dict) and result.get("error"):
                    success = False

                logger.tool_end(tool_name, duration_ms, success)
                Metrics.record_tool_call(tool_name, duration_ms / 1000, success, agent_type)

                return result

            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                logger.tool_end(tool_name, duration_ms, success=False, error=str(e))
                Metrics.record_tool_call(tool_name, duration_ms / 1000, False, agent_type)
                raise

        return wrapper

    return decorator


@contextmanager
def instrument_graph(graph_name: str):
    """
    Context manager to instrument graph execution.

    Usage:
        with instrument_graph("video") as ctx:
            result = await graph.ainvoke(state, config)
    """
    logger = get_logger(f"agent.graphs.{graph_name}")
    start_time = time.time()
    ctx = get_request_context()

    logger.graph_start(graph_name)

    success = True
    try:
        yield ctx
    except Exception:
        success = False
        raise
    finally:
        duration_ms = (time.time() - start_time) * 1000
        logger.graph_end(graph_name, duration_ms, success, tool_calls=len(ctx.tool_calls))
        Metrics.record_graph_execution(
            graph_name,
            duration_ms / 1000,
            success,
            len(ctx.tool_calls),
        )


# =============================================================================
# Config Helpers
# =============================================================================


def inject_request_context_to_config(config: dict, context: RequestContext | None = None) -> dict:
    """
    Inject request context into RunnableConfig for propagation through graph.

    Usage:
        config = inject_request_context_to_config(config, ctx)
        result = await graph.ainvoke(state, config)
    """
    ctx = context or get_request_context()

    if "configurable" not in config:
        config["configurable"] = {}

    config["configurable"]["request_id"] = ctx.request_id
    config["configurable"]["user_id"] = ctx.user_id
    config["configurable"]["session_id"] = ctx.session_id

    # Also set metadata for LangSmith tracing
    if "metadata" not in config:
        config["metadata"] = {}

    config["metadata"]["request_id"] = ctx.request_id
    config["metadata"]["user_id"] = ctx.user_id

    return config


def extract_request_id_from_config(config: dict) -> str | None:
    """Extract request ID from RunnableConfig."""
    return config.get("configurable", {}).get("request_id")
