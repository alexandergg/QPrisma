"""
QPrisma Video Agent - Foundry hosted runtime entrypoint.

Targets the Azure AI Foundry refreshed public preview for hosted agents:

* Runtime SDK: ``azure-ai-agentserver-responses==1.0.0b5``.
* Protocol: OpenAI Responses (``protocol.version: "1.0.0"`` in ``agent.yaml``).
* Persistence: Foundry Conversations / Responses own cross-turn history.
  LangGraph uses ``MemorySaver`` only for in-run state inside the hosted
  container.
* Per-request QPrisma inputs (media_id, media_ids, user_id, session_id) arrive
  via ``request.metadata``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from collections.abc import AsyncIterable, AsyncIterator
from typing import Any
from urllib.parse import urlparse

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("qprisma.hosted")


def _bootstrap_environment() -> None:
    """Configure hosted runtime logging before importing settings-backed modules."""
    try:
        from core.logging_config import setup_logging

        setup_logging()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Structured logging setup failed; continuing with basic logging: %s", exc)


_bootstrap_environment()

from azure.ai.agentserver.responses import (  # noqa: E402
    CreateResponse,
    ResponseContext,
    ResponseEventStream,
    ResponsesAgentServerHost,
    TextResponse,
)
from azure.identity import DefaultAzureCredential  # noqa: E402
from langchain_core.messages import (  # noqa: E402
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.checkpoint.memory import MemorySaver  # noqa: E402

from agent.graphs.video import create_video_agent_graph  # noqa: E402
from agent.hosted.telemetry import SafeAzureAIOpenTelemetryTracer  # noqa: E402
from agent.state.agent_state import AgentInputState  # noqa: E402
from agent.utils.observability import (  # noqa: E402
    set_conversation_id,
    set_otel_media_context,
    set_otel_user_id,
    stamp_current_span,
)

# ---------------------------------------------------------------------------
# Foundry env-var bridge
# ---------------------------------------------------------------------------
# Foundry reserves the ``FOUNDRY_*`` namespace for the runtime contract.
# Existing QPrisma code reads ``AZURE_AI_PROJECT_*``; mirror them so the hosted
# environment can populate either side without redeclaring platform variables.

_FOUNDRY_ENV_BRIDGE: dict[str, str] = {
    "FOUNDRY_PROJECT_ENDPOINT": "AZURE_AI_PROJECT_ENDPOINT",
    "FOUNDRY_PROJECT_ARM_ID": "AZURE_AI_PROJECT_ARM_ID",
    "FOUNDRY_AGENT_NAME": "AZURE_AI_AGENT_NAME",
    "FOUNDRY_AGENT_VERSION": "AZURE_AI_AGENT_VERSION",
    "FOUNDRY_AGENT_SESSION_ID": "AZURE_AI_AGENT_SESSION_ID",
}
for foundry_key, qprisma_key in _FOUNDRY_ENV_BRIDGE.items():
    value = os.environ.get(foundry_key)
    if value and not os.environ.get(qprisma_key):
        os.environ[qprisma_key] = value


def _mask_uri(uri: str | None) -> str:
    if not uri:
        return "<unset>"
    try:
        parsed = urlparse(uri)
        host = parsed.hostname or "<unknown>"
        return f"{parsed.scheme or 'https'}://{host}"
    except Exception:
        return "<malformed>"


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------

_tracer: SafeAzureAIOpenTelemetryTracer | None = None


def _setup_telemetry() -> SafeAzureAIOpenTelemetryTracer | None:
    """Initialise Azure AI OpenTelemetry tracer (best-effort)."""
    project_endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT") or os.environ.get(
        "AZURE_AI_PROJECT_ENDPOINT"
    )
    if not project_endpoint:
        logger.warning(
            "FOUNDRY_PROJECT_ENDPOINT/AZURE_AI_PROJECT_ENDPOINT not set; "
            "skipping AzureAIOpenTelemetryTracer.",
        )
        return None

    agent_id = os.environ.get("FOUNDRY_AGENT_NAME") or os.environ.get(
        "AZURE_AI_AGENT_NAME", "qprisma-video-agent"
    )

    try:
        from langchain_azure_ai.callbacks.tracers import AzureAIOpenTelemetryTracer

        inner = AzureAIOpenTelemetryTracer(
            project_endpoint=project_endpoint,
            credential=DefaultAzureCredential(),
            agent_id=agent_id,
        )
        wrapped = SafeAzureAIOpenTelemetryTracer(inner)
        logger.info(
            "AzureAIOpenTelemetryTracer initialised (endpoint=%s agent_id=%s)",
            _mask_uri(project_endpoint),
            agent_id,
        )
        return wrapped
    except ImportError as exc:
        logger.warning("langchain-azure-ai tracer unavailable: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to initialise AzureAIOpenTelemetryTracer: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Graph factory (compiled once per process)
# ---------------------------------------------------------------------------

_graph_lock = asyncio.Lock()
_graph: Any | None = None


def create_hosted_checkpointer() -> MemorySaver:
    """Create the Foundry-native Hosted Agent checkpointer.

    Hosted mode intentionally keeps LangGraph checkpointing process-local:
    Foundry Responses/Conversations own cross-turn conversation history, while
    LangGraph only needs in-run graph state for a single hosted execution.
    """
    return MemorySaver()


async def _get_graph() -> Any:
    global _graph
    if _graph is not None:
        return _graph
    async with _graph_lock:
        if _graph is not None:
            return _graph
        checkpointer = create_hosted_checkpointer()
        graph = create_video_agent_graph(checkpointer=checkpointer)
        callbacks = [_tracer] if _tracer is not None else []
        config: dict[str, Any] = {"tags": ["qprisma", "video-agent", "hosted"]}
        if callbacks:
            config["callbacks"] = callbacks
        _graph = graph.with_config(config)
        logger.info(
            "Video agent graph compiled (tracer=%s).",
            "enabled" if callbacks else "disabled",
        )
        return _graph


# ---------------------------------------------------------------------------
# History helpers
# ---------------------------------------------------------------------------


def _coerce_message(item: Any) -> BaseMessage | None:
    """Best-effort coercion of an SDK history/input item into a LangChain message."""
    if isinstance(item, BaseMessage):
        return item

    role: str | None = None
    content: Any = None

    if isinstance(item, dict):
        role = (item.get("role") or item.get("type") or "").lower() or None
        content = item.get("content") or item.get("text") or item.get("message")
    else:
        role = (getattr(item, "role", None) or getattr(item, "type", None) or "").lower() or None
        content = (
            getattr(item, "content", None)
            or getattr(item, "text", None)
            or getattr(item, "message", None)
        )

    if content is None:
        return None

    text: str
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                value = part.get("text") or part.get("content") or part.get("value")
                if isinstance(value, str):
                    parts.append(value)
        text = "\n".join(p for p in parts if p)
    else:
        text = str(content)

    text = text.strip()
    if not text:
        return None

    if role in {"assistant", "ai"}:
        return AIMessage(content=text)
    if role in {"system", "developer"}:
        return SystemMessage(content=text)
    if role == "tool":
        tool_call_id = (
            item.get("tool_call_id")
            if isinstance(item, dict)
            else getattr(item, "tool_call_id", None)
        ) or "unknown"
        return ToolMessage(content=text, tool_call_id=tool_call_id)
    return HumanMessage(content=text)


async def _collect_history(context: ResponseContext) -> list[BaseMessage]:
    raw: list[Any] = []
    try:
        history = await context.get_history()
        if history:
            raw.extend(history)
    except Exception as exc:  # noqa: BLE001
        logger.warning("context.get_history() failed: %s", exc)

    try:
        inputs = await context.get_input_items()
        if inputs:
            raw.extend(inputs)
    except Exception as exc:  # noqa: BLE001
        logger.warning("context.get_input_items() failed: %s", exc)

    messages: list[BaseMessage] = []
    for item in raw:
        coerced = _coerce_message(item)
        if coerced is not None:
            messages.append(coerced)

    if not messages:
        try:
            text = await context.get_input_text()
        except Exception:  # noqa: BLE001
            text = None
        if text:
            messages.append(HumanMessage(content=text))

    return messages


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------


def _normalise_media_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v is not None and str(v).strip()]
    if isinstance(value, str):
        return [piece.strip() for piece in value.split(",") if piece.strip()]
    return [str(value)]


def _build_initial_state(
    metadata: dict[str, Any],
    messages: list[BaseMessage],
) -> AgentInputState:
    media_id_raw = metadata.get("media_id")
    media_ids_raw = metadata.get("media_ids")

    media_ids = _normalise_media_ids(media_ids_raw)
    media_id = (
        str(media_id_raw).strip()
        if media_id_raw is not None and str(media_id_raw).strip()
        else (media_ids[0] if media_ids else None)
    )
    if media_id and media_id not in media_ids:
        media_ids.insert(0, media_id)

    state: dict[str, Any] = {
        "messages": messages,
        "media_id": media_id,
        "media_ids": media_ids or None,
        "user_id": metadata.get("user_id") or metadata.get("userId"),
    }

    session_id = metadata.get("session_id") or metadata.get("sessionId")
    if session_id:
        state["session_id"] = str(session_id)

    benchmark_context = metadata.get("benchmark_context")
    if isinstance(benchmark_context, dict) and benchmark_context:
        state["benchmark_context"] = benchmark_context

    video_titles = metadata.get("video_titles")
    if isinstance(video_titles, dict) and video_titles:
        state["video_titles"] = {str(k): str(v) for k, v in video_titles.items()}

    return state  # type: ignore[return-value]


def _context_conversation_id(context: ResponseContext) -> str:
    for attr in ("conversation_id", "session_id", "thread_id", "response_id"):
        value = getattr(context, attr, None)
        if value:
            return str(value)
    return "unknown"


def _stamp_request_context(context: ResponseContext, state: AgentInputState) -> None:
    conversation_id = _context_conversation_id(context)
    media_id = state.get("media_id")
    media_ids = state.get("media_ids")
    user_id = state.get("user_id")
    session_id = state.get("session_id")

    set_conversation_id(conversation_id)
    if user_id:
        set_otel_user_id(str(user_id))
    set_otel_media_context(
        media_id=str(media_id) if media_id else None,
        media_ids=[str(value) for value in media_ids] if media_ids else None,
        session_id=str(session_id) if session_id else None,
    )
    stamp_current_span(
        conversation_id=conversation_id,
        user_id=str(user_id) if user_id else None,
        media_id=str(media_id) if media_id else None,
        media_ids=[str(value) for value in media_ids] if media_ids else None,
        session_id=str(session_id) if session_id else None,
    )


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


def _response_id_from_context(context: ResponseContext) -> str:
    response_id = getattr(context, "response_id", None)
    if isinstance(response_id, str) and response_id:
        return response_id
    return f"caresp_{uuid.uuid4().hex}"


def _call_id_from_run_id(run_id: str) -> str:
    if not run_id:
        return f"call_{uuid.uuid4().hex}"
    return f"call_{''.join(char if char.isalnum() else '_' for char in run_id)}"


def _json_dumps_safe(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return json.dumps(str(value), ensure_ascii=False)


def _extract_text_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
                continue
            if isinstance(part, dict):
                value = part.get("text") or part.get("content") or part.get("value")
            else:
                value = (
                    getattr(part, "text", None)
                    or getattr(part, "content", None)
                    or getattr(part, "value", None)
                )
            if isinstance(value, str):
                parts.append(value)
        return "".join(parts)
    return str(content)


def _message_has_tool_calls(message: Any) -> bool:
    if isinstance(message, dict):
        return bool(message.get("tool_calls") or message.get("tool_call_chunks"))
    return bool(
        getattr(message, "tool_calls", None)
        or getattr(message, "tool_call_chunks", None)
        or getattr(message, "additional_kwargs", {}).get("tool_calls")
    )


def _extract_final_text_from_model_output(output: Any) -> str:
    message = output
    if hasattr(output, "message"):
        message = output.message
    elif isinstance(output, dict) and "message" in output:
        message = output["message"]

    if _message_has_tool_calls(message):
        return ""

    content = (
        message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
    )
    return _extract_text_content(content).strip()


async def _stream_response_events(
    *,
    context: ResponseContext,
    request: CreateResponse,
    graph: Any,
    state: AgentInputState,
    config: dict[str, Any],
    cancellation_signal: asyncio.Event,
) -> AsyncIterator[Any]:
    """Translate LangGraph stream events into Foundry Responses stream events."""
    stream = ResponseEventStream(
        response_id=_response_id_from_context(context),
        request=request,
    )
    message_builder: Any | None = None
    text_builder: Any | None = None
    accumulated_text: list[str] = []
    tool_builders: dict[str, Any] = {}
    tool_start_times: dict[str, float] = {}
    model_tokens_emitted: dict[str, bool] = {}

    def ensure_text_stream() -> list[Any]:
        nonlocal message_builder, text_builder
        events: list[Any] = []
        if message_builder is None:
            message_builder = stream.add_output_item_message()
            events.append(message_builder.emit_added())
        if text_builder is None:
            text_builder = message_builder.add_text_content()
            events.append(text_builder.emit_added())
        return events

    def emit_text_delta(text: str) -> list[Any]:
        if not text:
            return []
        events = ensure_text_stream()
        accumulated_text.append(text)
        events.append(text_builder.emit_delta(text))
        return events

    yield stream.emit_created(status="in_progress")
    yield stream.emit_in_progress()

    try:
        async for event in graph.astream_events(state, config=config, version="v2"):
            if cancellation_signal.is_set():
                logger.info("Cancellation requested mid-stream; aborting graph events.")
                break

            event_type = event.get("event")
            data = event.get("data", {})
            run_id = str(event.get("run_id") or "")

            if event_type == "on_chat_model_start":
                if run_id:
                    model_tokens_emitted[run_id] = False
                continue

            if event_type == "on_tool_start":
                tool_name = str(event.get("name", "unknown"))
                builder = stream.add_output_item_function_call(
                    name=tool_name,
                    call_id=_call_id_from_run_id(run_id),
                )
                tool_builders[run_id] = builder
                tool_start_times[run_id] = time.perf_counter()
                logger.info("Hosted graph tool started: tool=%s run_id=%s", tool_name, run_id)
                yield builder.emit_added()
                arguments = _json_dumps_safe(data.get("input") or {})
                yield builder.emit_arguments_delta(arguments)
                yield builder.emit_arguments_done(arguments)
                continue

            if event_type == "on_tool_end":
                tool_name = str(event.get("name", "unknown"))
                started_at = tool_start_times.pop(run_id, None)
                elapsed_seconds = time.perf_counter() - started_at if started_at else None
                output = data.get("output")
                success = not (isinstance(output, dict) and output.get("error"))
                logger.info(
                    "Hosted graph tool finished: tool=%s run_id=%s success=%s elapsed_seconds=%s",
                    tool_name,
                    run_id,
                    success,
                    f"{elapsed_seconds:.3f}" if elapsed_seconds is not None else "unknown",
                )
                builder = tool_builders.pop(run_id, None)
                if builder is not None:
                    yield builder.emit_done()
                continue

            if event_type == "on_chat_model_stream":
                chunk = data.get("chunk")
                if chunk is None:
                    continue
                text = _extract_text_content(getattr(chunk, "content", None))
                if text:
                    if run_id:
                        model_tokens_emitted[run_id] = True
                    for response_event in emit_text_delta(text):
                        yield response_event
                continue

            if event_type == "on_chat_model_end":
                if run_id and model_tokens_emitted.get(run_id):
                    continue
                text = _extract_final_text_from_model_output(data.get("output"))
                if text:
                    for response_event in emit_text_delta(text):
                        yield response_event

    except asyncio.CancelledError:
        logger.info("Response event stream cancelled.")
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Graph streaming failed: %s", exc)
        for response_event in emit_text_delta(f"\n\n[error] Agent execution failed: {exc}"):
            yield response_event

    for builder in list(tool_builders.values()):
        yield builder.emit_done()
    if text_builder is not None:
        final_text = "".join(accumulated_text)
        yield text_builder.emit_text_done(final_text)
        yield text_builder.emit_done()
    if message_builder is not None:
        yield message_builder.emit_done()
    yield stream.emit_completed()


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

_tracer = _setup_telemetry()
app = ResponsesAgentServerHost()


@app.response_handler
async def handle_response(
    request: CreateResponse,
    context: ResponseContext,
    cancellation_signal: asyncio.Event,
) -> TextResponse | AsyncIterable[Any]:
    """Refreshed-preview entrypoint: ingest a Responses request, stream graph events."""
    metadata: dict[str, Any] = dict(request.metadata) if request.metadata else {}

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "Incoming response request response_id=%s metadata_keys=%s",
            getattr(context, "response_id", None),
            sorted(metadata.keys()),
        )

    history = await _collect_history(context)
    if not history:
        logger.warning(
            "No input messages resolved (response_id=%s); replying with stub.",
            getattr(context, "response_id", None),
        )
        return TextResponse(
            context,
            request,
            text="I didn't receive any user input. Please send a message and try again.",
        )

    graph = await _get_graph()
    state = _build_initial_state(metadata, history)
    _stamp_request_context(context, state)

    conversation_id = _context_conversation_id(context)
    config: dict[str, Any] = {
        "configurable": {
            "thread_id": conversation_id,
            "media_id": state.get("media_id"),
            "media_ids": state.get("media_ids"),
            "user_id": state.get("user_id"),
            "session_id": state.get("session_id"),
        },
        "metadata": metadata,
    }

    return _stream_response_events(
        context=context,
        request=request,
        graph=graph,
        state=state,
        config=config,
        cancellation_signal=cancellation_signal,
    )


def main() -> None:
    """CLI entrypoint for the hosted runtime."""
    port_env = os.environ.get("PORT")
    port = int(port_env) if port_env else None
    app.run(host="0.0.0.0", port=port)  # noqa: S104


if __name__ == "__main__":
    main()
