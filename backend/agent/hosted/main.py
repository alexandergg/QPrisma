"""
QPrisma Video Agent — hosted runtime entrypoint.

Targets the Azure AI Foundry **refreshed public preview** for hosted agents:

* Runtime SDK: ``azure-ai-agentserver-responses==1.0.0b5`` (+ ``core>=2.0.0b3``).
* Protocol: OpenAI Responses (``protocol.version: "1.0.0"`` in ``agent.yaml``).
* Persistence: **Foundry Conversations** (Sessions / Conversations / Responses).
  In-process LangGraph state uses ``MemorySaver`` only for the duration of a
  single turn; cross-turn history is recovered via ``context.get_history()``.
* Per-request inputs (media_id, media_ids, user_id, …) arrive via
  ``request.metadata``. The legacy ``[QPRISMA_CONTEXT:…]`` message envelope
  has been removed.

Local development falls back to ``InMemoryResponseProvider`` automatically when
``FOUNDRY_HOSTING_ENVIRONMENT`` is unset (handled by ``ResponsesAgentServerHost``).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import AsyncIterable
from typing import Any
from urllib.parse import urlparse

from azure.ai.agentserver.responses import (
    CreateResponse,
    ResponseContext,
    ResponsesAgentServerHost,
    TextResponse,
)
from azure.identity import DefaultAzureCredential
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.checkpoint.memory import MemorySaver

from agent.graphs.video import create_video_agent_graph
from agent.hosted.telemetry import SafeAzureAIOpenTelemetryTracer
from agent.state.agent_state import AgentInputState

logger = logging.getLogger("qprisma.hosted")

# ---------------------------------------------------------------------------
# Foundry env-var bridge
# ---------------------------------------------------------------------------
# Foundry reserves the ``FOUNDRY_*`` namespace for the runtime contract.
# Existing QPrisma code reads ``AZURE_AI_PROJECT_*``; mirror them so the
# hosted environment can populate either side.

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
    """Initialise Azure AI OpenTelemetry tracer (best-effort).

    Returns the LangChain callback or ``None`` if telemetry is unavailable.
    Failures are logged but never block startup — the agent must remain
    serviceable even if telemetry export is degraded.
    """

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
            trace_all_langgraph_nodes=True,
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


async def _get_graph() -> Any:
    global _graph
    if _graph is not None:
        return _graph
    async with _graph_lock:
        if _graph is not None:
            return _graph
        checkpointer = MemorySaver()
        graph = await create_video_agent_graph(checkpointer=checkpointer)
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
    """Best-effort coercion of an SDK history/input item into a LangChain message.

    The refreshed Responses preview returns provider-shaped dicts. We accept
    the common variants and fall back to ``HumanMessage`` for unknown roles.
    """

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
            (item.get("tool_call_id") if isinstance(item, dict) else getattr(item, "tool_call_id", None))
            or "unknown"
        )
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


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


async def _stream_tokens(
    graph: Any,
    state: AgentInputState,
    config: dict[str, Any],
    cancellation_signal: asyncio.Event,
) -> AsyncIterable[str]:
    """Stream LangGraph LLM token deltas as plain text chunks.

    ``TextResponse`` consumes an ``AsyncIterable[str]``; the SDK wraps each
    yielded chunk in the appropriate Responses streaming event.
    """

    try:
        async for event in graph.astream_events(state, config=config, version="v2"):
            if cancellation_signal.is_set():
                logger.info("Cancellation requested mid-stream; aborting graph events.")
                break

            event_type = event.get("event")
            if event_type != "on_chat_model_stream":
                continue

            chunk = event.get("data", {}).get("chunk")
            if chunk is None:
                continue

            content = getattr(chunk, "content", None)
            if isinstance(content, str) and content:
                yield content
            elif isinstance(content, list):
                for piece in content:
                    if isinstance(piece, str) and piece:
                        yield piece
                    elif isinstance(piece, dict):
                        text = piece.get("text")
                        if isinstance(text, str) and text:
                            yield text
    except asyncio.CancelledError:
        logger.info("Token stream cancelled.")
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Graph streaming failed: %s", exc)
        yield f"\n\n[error] Agent execution failed: {exc}"


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)

_tracer = _setup_telemetry()
app = ResponsesAgentServerHost()


@app.response_handler
async def handle_response(
    request: CreateResponse,
    context: ResponseContext,
    cancellation_signal: asyncio.Event,
) -> TextResponse:
    """Refreshed-preview entrypoint: ingest a Responses request, stream tokens."""

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

    response_id = getattr(context, "response_id", None) or "unknown"
    config: dict[str, Any] = {
        "configurable": {
            "thread_id": response_id,
            "media_id": state.get("media_id"),
            "media_ids": state.get("media_ids"),
            "user_id": state.get("user_id"),
        },
        "metadata": metadata,
    }

    return TextResponse(
        context,
        request,
        text=_stream_tokens(graph, state, config, cancellation_signal),
    )


def main() -> None:
    """CLI entrypoint for the hosted runtime."""
    port_env = os.environ.get("PORT")
    port = int(port_env) if port_env else None
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
