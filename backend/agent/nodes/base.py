"""
Base Agent Nodes
================

Shared node implementations for LangGraph agents.

Features:
- Configurable model creation with caching
- Shared message trimming and context management
- Error handling with graceful degradation
- Tool iteration management
- Structured logging with correlation IDs
- Prometheus-style metrics
"""

import json
import re
import time
from functools import lru_cache
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import AzureChatOpenAI
from langgraph.graph import END

from agent.state.agent_state import (
    AgentState,
    get_message_trimmer,
    should_retry_exception,
    truncate_tool_message_content,
)
from agent.utils.observability import (
    Metrics,
    get_logger,
)
from core.azure_credentials import build_openai_client_kwargs
from core.config import settings

logger = get_logger(__name__)


def _sanitize_log(value: object, max_len: int = 200) -> str:
    """Strip control characters and truncate for safe logging."""
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", "", str(value))[:max_len]


# Shared message trimmer instance
_message_trimmer = get_message_trimmer(max_tokens=80000)

# Iteration limits
DEFAULT_MAX_TOOL_ITERATIONS = 10
DEFAULT_WARN_TOOL_ITERATIONS = 7

# Error thresholds for graceful degradation
MAX_CONSECUTIVE_ERRORS = 3

# Artifact rehydration budget (keeps prompt compact while restoring key details)
ARTIFACT_REHYDRATION_MAX_ITEMS = 2
ARTIFACT_REHYDRATION_MAX_TOTAL_CHARS = 3500
ARTIFACT_REHYDRATION_ITEM_CHARS = 1400

# Hybrid memory retrieval and reranking limits
HYBRID_MEMORY_MAX_CANDIDATES = 24
HYBRID_MEMORY_MAX_SNIPPETS = 6
HYBRID_MEMORY_BASE_BUDGET_CHARS = 1200
HYBRID_MEMORY_DETAIL_BUDGET_CHARS = 2200


# =============================================================================
# Model Creation (Cached)
# =============================================================================


@lru_cache(maxsize=8)
def create_model(
    model_deployment: str | None = None,
    temperature: float = 1,
    streaming: bool = True,
) -> AzureChatOpenAI:
    """
    Create Azure OpenAI chat model (cached by deployment + params).

    Uses API key when available, falls back to managed identity (AAD)
    for hosted agent containers.

    Args:
        model_deployment: Azure deployment name
        temperature: Model temperature
        streaming: Enable streaming responses

    Returns:
        Configured AzureChatOpenAI instance
    """
    deployment = model_deployment or settings.azure.openai_deployment_gpt

    kwargs = {
        "azure_deployment": deployment,
        "model": deployment,  # Needed for OpenTelemetry gen_ai instrumentation
        "temperature": temperature,
        "streaming": streaming,
    }
    client_kwargs = build_openai_client_kwargs(
        endpoint=settings.azure.openai_endpoint,
        api_key=settings.azure.openai_api_key,
        api_version=settings.azure.openai_api_version,
        use_managed_identity=settings.azure.use_managed_identity,
    )
    if client_kwargs is None:
        raise ValueError("Azure OpenAI chat model is not configured")
    kwargs.update(client_kwargs)

    return AzureChatOpenAI(**kwargs)


# =============================================================================
# Context Extraction
# =============================================================================


def extract_topics_from_messages(messages: list) -> list[str]:
    """
    Extract key topics/entities from conversation for context memory.

    Used to maintain awareness of what has been discussed.
    """
    topics = set()

    for msg in messages:
        if isinstance(msg, HumanMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            # Extract quoted phrases
            quotes = re.findall(r'"([^"]+)"', content)
            topics.update(quotes)
            # Extract capitalized words (potential entities)
            caps = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", content)
            topics.update(caps)
        elif isinstance(msg, ToolMessage):
            # Extract from tool results
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            # Look for entity names in results
            entity_matches = re.findall(r'"name":\s*"([^"]+)"', content)
            topics.update(entity_matches)

    return list(topics)[:10]  # Keep last 10 topics


def _get_latest_human_query(messages: list) -> str:
    """Extract the most recent human query text."""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return msg.content if isinstance(msg.content, str) else str(msg.content)
    return ""


def _extract_artifact_id(text: str) -> str | None:
    """Extract artifact id marker from memory text."""
    match = re.search(r"\[artifact:([^\]]+)\]", text)
    if match:
        return match.group(1)
    return None


def _score_text_overlap(text: str, query_terms: set[str]) -> int:
    """Score lexical overlap between a text snippet and query terms."""
    if not query_terms:
        return 0
    lowered = text.lower()
    return sum(1 for term in query_terms if term in lowered)


def _memory_budget_chars(query: str) -> int:
    """Compute dynamic memory injection budget based on query needs."""
    if _is_detail_query(query):
        return HYBRID_MEMORY_DETAIL_BUDGET_CHARS

    query_term_count = len(_extract_query_terms(query))
    if query_term_count >= 8:
        return HYBRID_MEMORY_BASE_BUDGET_CHARS + 400

    return HYBRID_MEMORY_BASE_BUDGET_CHARS


def _agent_type_from_state(state: AgentState) -> str:
    """Infer agent type label from state for observability metrics."""
    return "video"


def _extract_query_terms(query: str) -> set[str]:
    """Extract lightweight keywords from query for artifact ranking."""
    stop_words = {
        "the",
        "and",
        "for",
        "with",
        "this",
        "that",
        "what",
        "when",
        "where",
        "which",
        "who",
        "how",
        "about",
        "video",
        "scene",
        "please",
    }
    return {
        term for term in re.findall(r"\b[a-z0-9]{3,}\b", query.lower()) if term not in stop_words
    }


def _is_detail_query(query: str) -> bool:
    """Detect if user asks for precision where full artifact detail helps."""
    detail_hints = (
        "exact",
        "specific",
        "detail",
        "timestamp",
        "timecode",
        "quote",
        "verbatim",
        "full",
        "complete",
        "all results",
        "evidence",
    )
    lowered = query.lower()
    return any(hint in lowered for hint in detail_hints)


def _score_artifact_ref(ref: dict, query_terms: set[str]) -> int:
    """Score artifact reference relevance against current query terms."""
    if not query_terms:
        return 0
    haystack = f"{ref.get('tool_name', '')} {ref.get('summary', '')}".lower()
    return sum(1 for term in query_terms if term in haystack)


def _select_artifact_refs_for_query(query: str, artifact_refs: list[dict]) -> list[dict]:
    """Choose a small set of most relevant artifact refs for rehydration."""
    recent_refs = list(reversed(artifact_refs[-20:]))
    if not recent_refs:
        return []

    query_terms = _extract_query_terms(query)
    detail_query = _is_detail_query(query)
    scored = [
        (_score_artifact_ref(ref, query_terms), index, ref) for index, ref in enumerate(recent_refs)
    ]

    if not detail_query and (not scored or max(score for score, _, _ in scored) <= 0):
        return []

    ranked = sorted(scored, key=lambda item: (item[0], -item[1]), reverse=True)
    selected: list[dict] = []
    seen_ids: set[str] = set()
    for _, _, ref in ranked:
        artifact_id = ref.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id or artifact_id in seen_ids:
            continue
        selected.append(ref)
        seen_ids.add(artifact_id)
        if len(selected) >= ARTIFACT_REHYDRATION_MAX_ITEMS:
            break

    return selected


def _format_artifact_payload_preview(payload: dict | list | str | None) -> str:
    """Format artifact payload into compact text snippet for prompt hydration."""
    if isinstance(payload, dict):
        for key in (
            "results",
            "occurrences",
            "highlights",
            "timeline",
            "moments",
            "comparison",
            "message",
        ):
            if key in payload:
                return f"{key}: {json.dumps(payload[key], ensure_ascii=False)[:ARTIFACT_REHYDRATION_ITEM_CHARS]}"
        return json.dumps(payload, ensure_ascii=False)[:ARTIFACT_REHYDRATION_ITEM_CHARS]

    if isinstance(payload, list):
        return json.dumps(payload, ensure_ascii=False)[:ARTIFACT_REHYDRATION_ITEM_CHARS]

    if isinstance(payload, str):
        return payload[:ARTIFACT_REHYDRATION_ITEM_CHARS]

    if payload is None:
        return ""

    return str(payload)[:ARTIFACT_REHYDRATION_ITEM_CHARS]


async def _retrieve_hybrid_memory_context(
    state: AgentState,
    config: RunnableConfig,
) -> tuple[list[str], list[str]]:
    """Hybrid retrieval + reranking for memory candidates with dynamic context budget."""
    retrieval_started = time.time()
    metric_labels = {"source": "hybrid", "agent": _agent_type_from_state(state)}
    query = _get_latest_human_query(state.get("messages", []))
    if not query:
        return [], []

    query_terms = _extract_query_terms(query)
    detail_query = _is_detail_query(query)
    budget_chars = _memory_budget_chars(query)

    candidates: list[dict] = []

    local_memory = state.get("memory_context", [])
    if isinstance(local_memory, list):
        for index, entry in enumerate(reversed(local_memory[-20:])):
            if not isinstance(entry, str) or not entry:
                continue

            lexical_score = _score_text_overlap(entry, query_terms)
            recency_score = max(0.0, 1.0 - (index / 20))
            artifact_id = _extract_artifact_id(entry)
            rank_score = (lexical_score * 2.0) + recency_score
            if detail_query and artifact_id:
                rank_score += 0.5

            candidates.append(
                {
                    "text": entry[:260],
                    "artifact_id": artifact_id,
                    "source": "local",
                    "lexical_score": lexical_score,
                    "rank_score": rank_score,
                    "recency_score": recency_score,
                }
            )

    artifact_refs = state.get("artifact_refs", [])
    if isinstance(artifact_refs, list):
        for index, ref in enumerate(reversed(artifact_refs[-20:])):
            if not isinstance(ref, dict):
                continue
            summary = ref.get("summary")
            if not isinstance(summary, str) or not summary:
                continue

            tool_name = ref.get("tool_name") if isinstance(ref.get("tool_name"), str) else "tool"
            artifact_id = (
                ref.get("artifact_id") if isinstance(ref.get("artifact_id"), str) else None
            )
            ref_text = (
                summary
                if summary.lower().startswith(tool_name.lower())
                else f"{tool_name}: {summary}"
            )
            lexical_score = _score_text_overlap(ref_text, query_terms)
            recency_score = max(0.0, 1.0 - (index / 20))
            rank_score = (lexical_score * 2.2) + (recency_score * 0.8)
            if detail_query and artifact_id:
                rank_score += 0.8

            candidates.append(
                {
                    "text": ref_text[:260],
                    "artifact_id": artifact_id,
                    "source": "artifact_ref",
                    "lexical_score": lexical_score,
                    "rank_score": rank_score,
                    "recency_score": recency_score,
                }
            )

    if not candidates:
        duration_seconds = time.time() - retrieval_started
        Metrics.observe_histogram(
            Metrics.MEMORY_RETRIEVAL_DURATION, duration_seconds, metric_labels
        )
        Metrics.observe_histogram(Metrics.MEMORY_CANDIDATES, 0, metric_labels)
        Metrics.observe_histogram(Metrics.MEMORY_SNIPPETS_INJECTED, 0, metric_labels)
        Metrics.observe_histogram(
            Metrics.MEMORY_BUDGET_CHARS,
            budget_chars,
            {**metric_labels, "kind": "budget"},
        )
        Metrics.observe_histogram(
            Metrics.MEMORY_BUDGET_CHARS,
            0,
            {**metric_labels, "kind": "used"},
        )
        logger.info(
            "Hybrid memory retrieval completed",
            candidate_count=0,
            ranked_count=0,
            snippet_count=0,
            budget_chars=budget_chars,
            used_chars=0,
            prioritized_artifacts=0,
            detail_query=detail_query,
            query_terms=len(query_terms),
            duration_ms=round(duration_seconds * 1000, 2),
        )
        return [], []

    ranked = sorted(
        candidates,
        key=lambda item: (item["rank_score"], item["recency_score"]),
        reverse=True,
    )[:HYBRID_MEMORY_MAX_CANDIDATES]

    snippets: list[str] = []
    prioritized_artifact_ids: list[str] = []
    seen_text: set[str] = set()
    total_chars = 0

    for candidate in ranked:
        text = candidate.get("text")
        if not isinstance(text, str) or not text:
            continue

        source = candidate.get("source")
        source_label = source if isinstance(source, str) else "memory"
        snippet = f"[{source_label}] {text}"
        dedupe_key = snippet.lower()
        if dedupe_key in seen_text:
            continue

        projected_chars = total_chars + len(snippet)
        if snippets and projected_chars > budget_chars:
            continue
        if not snippets and len(snippet) > budget_chars:
            snippet = snippet[:budget_chars]
            projected_chars = len(snippet)

        snippets.append(snippet)
        seen_text.add(dedupe_key)
        total_chars = projected_chars

        artifact_id = candidate.get("artifact_id")
        lexical_score = candidate.get("lexical_score")
        if (
            isinstance(artifact_id, str)
            and artifact_id
            and artifact_id not in prioritized_artifact_ids
            and (detail_query or (isinstance(lexical_score, int | float) and lexical_score > 0))
        ):
            prioritized_artifact_ids.append(artifact_id)

        if len(snippets) >= HYBRID_MEMORY_MAX_SNIPPETS or total_chars >= budget_chars:
            break

    prioritized = prioritized_artifact_ids[:ARTIFACT_REHYDRATION_MAX_ITEMS]
    duration_seconds = time.time() - retrieval_started
    Metrics.observe_histogram(Metrics.MEMORY_RETRIEVAL_DURATION, duration_seconds, metric_labels)
    Metrics.observe_histogram(Metrics.MEMORY_CANDIDATES, len(candidates), metric_labels)
    Metrics.observe_histogram(Metrics.MEMORY_SNIPPETS_INJECTED, len(snippets), metric_labels)
    Metrics.observe_histogram(
        Metrics.MEMORY_BUDGET_CHARS,
        budget_chars,
        {**metric_labels, "kind": "budget"},
    )
    Metrics.observe_histogram(
        Metrics.MEMORY_BUDGET_CHARS,
        total_chars,
        {**metric_labels, "kind": "used"},
    )
    logger.info(
        "Hybrid memory retrieval completed",
        candidate_count=len(candidates),
        ranked_count=len(ranked),
        snippet_count=len(snippets),
        budget_chars=budget_chars,
        used_chars=total_chars,
        prioritized_artifacts=len(prioritized),
        detail_query=detail_query,
        query_terms=len(query_terms),
        duration_ms=round(duration_seconds * 1000, 2),
    )

    return snippets, prioritized


async def _rehydrate_artifact_context(
    state: AgentState,
    config: RunnableConfig,
    *,
    prioritized_artifact_ids: list[str] | None = None,
) -> list[str]:
    """Recover selective detail from persisted tool artifacts for precision turns."""
    rehydration_started = time.time()
    metric_labels = {"source": "artifact", "agent": _agent_type_from_state(state)}
    artifact_refs = state.get("artifact_refs", [])
    if not artifact_refs:
        return []

    query = _get_latest_human_query(state.get("messages", []))
    if not query:
        return []

    selected_refs: list[dict]
    if prioritized_artifact_ids:
        refs_by_id: dict[str, dict] = {}
        for ref in reversed(artifact_refs[-50:]):
            if not isinstance(ref, dict):
                continue
            artifact_id = ref.get("artifact_id")
            if isinstance(artifact_id, str) and artifact_id and artifact_id not in refs_by_id:
                refs_by_id[artifact_id] = ref

        selected_refs = []
        for artifact_id in prioritized_artifact_ids:
            ref = refs_by_id.get(artifact_id)
            if ref is not None:
                selected_refs.append(ref)
        selected_refs = selected_refs[:ARTIFACT_REHYDRATION_MAX_ITEMS]
    else:
        selected_refs = _select_artifact_refs_for_query(query, artifact_refs)

    if not selected_refs:
        duration_seconds = time.time() - rehydration_started
        Metrics.observe_histogram(
            Metrics.ARTIFACT_REHYDRATION_DURATION, duration_seconds, metric_labels
        )
        Metrics.inc_counter(Metrics.ARTIFACT_REHYDRATION_ATTEMPTS, metric_labels, 0)
        Metrics.inc_counter(Metrics.ARTIFACT_REHYDRATION_SUCCESSES, metric_labels, 0)
        return []

    try:
        from services.tool_artifact_service import get_tool_artifact_service

        artifact_service = await get_tool_artifact_service()
    except (TypeError, ValueError, RuntimeError, ImportError) as exc:
        Metrics.inc_counter(Metrics.ARTIFACT_REHYDRATION_ERRORS, metric_labels)
        logger.warning("Failed to initialize artifact service for rehydration: %s", exc)
        return []

    snippets: list[str] = []
    total_chars = 0
    attempts = 0
    successes = 0
    for ref in selected_refs:
        artifact_id = ref.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id:
            continue

        attempts += 1
        try:
            artifact = await artifact_service.get_artifact(artifact_id)
        except (TypeError, ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
            Metrics.inc_counter(Metrics.ARTIFACT_REHYDRATION_ERRORS, metric_labels)
            logger.warning("Failed to fetch tool artifact %s: %s", artifact_id, exc)
            continue

        if not isinstance(artifact, dict):
            continue

        tool_name = ref.get("tool_name") or artifact.get("tool_name") or "tool"
        summary = ref.get("summary") if isinstance(ref.get("summary"), str) else ""
        payload_preview = _format_artifact_payload_preview(artifact.get("payload"))
        if not payload_preview:
            continue

        snippet = (
            f"[artifact:{artifact_id}] {tool_name}\n"
            f"summary: {summary[:180]}\n"
            f"payload: {payload_preview}"
        )
        if total_chars + len(snippet) > ARTIFACT_REHYDRATION_MAX_TOTAL_CHARS:
            break

        snippets.append(snippet)
        total_chars += len(snippet)
        successes += 1

    duration_seconds = time.time() - rehydration_started
    Metrics.observe_histogram(
        Metrics.ARTIFACT_REHYDRATION_DURATION, duration_seconds, metric_labels
    )
    Metrics.inc_counter(Metrics.ARTIFACT_REHYDRATION_ATTEMPTS, metric_labels, attempts)
    Metrics.inc_counter(Metrics.ARTIFACT_REHYDRATION_SUCCESSES, metric_labels, successes)
    logger.info(
        "Artifact rehydration completed",
        selected_refs=len(selected_refs),
        attempts=attempts,
        successes=successes,
        snippet_chars=total_chars,
        duration_ms=round(duration_seconds * 1000, 2),
    )

    return snippets


# =============================================================================
# Shared Node Logic
# =============================================================================


async def base_call_model(
    state: AgentState,
    config: RunnableConfig,
    tools: list,
    system_message: SystemMessage,
    max_iterations: int = DEFAULT_MAX_TOOL_ITERATIONS,
    warn_iterations: int = DEFAULT_WARN_TOOL_ITERATIONS,
    temperature: float = 1,
) -> dict:
    """
    Base implementation for calling the LLM.

    Shared logic for calling the LLM:
    - Message trimming to prevent context overflow
    - Tool binding with iteration management
    - Error tracking for graceful degradation
    - Structured logging with correlation IDs
    - Prometheus metrics collection

    Args:
        state: Current agent state
        config: Runnable configuration
        tools: List of tools to bind
        system_message: System prompt message
        max_iterations: Maximum tool calls before stopping
        warn_iterations: Tool calls at which to warn about limit
        temperature: Model temperature

    Returns:
        State update dict with messages and tracking info
    """
    start_time = time.time()

    # Get model from config or create default
    model_deployment = config.get("configurable", {}).get("model_deployment")
    model = create_model(model_deployment, temperature=temperature)

    # Check tool call count for iteration management
    tool_calls_count = state.get("tool_calls_count", 0)
    approaching_limit = tool_calls_count >= warn_iterations
    consecutive_errors = state.get("consecutive_errors", 0)

    logger.info(
        "base_call_model: checking tools",
        tools_provided=len(tools) if tools else 0,
        tool_names=[t.name for t in tools] if tools else [],
        tool_calls_count=tool_calls_count,
        approaching_limit=approaching_limit,
        consecutive_errors=consecutive_errors,
    )

    # If approaching limit or too many errors, don't bind tools
    should_bind_tools = (
        tools and not approaching_limit and consecutive_errors < MAX_CONSECUTIVE_ERRORS
    )

    if should_bind_tools:
        model = model.bind_tools(tools)
        logger.debug(
            "Tools bound to model",
            tool_count=len(tools),
            iteration=tool_calls_count,
        )
    elif approaching_limit:
        logger.info(
            "Not binding tools - approaching iteration limit",
            tool_calls_count=tool_calls_count,
            max_iterations=max_iterations,
        )
    elif consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
        logger.warning(
            "Not binding tools - error threshold reached",
            consecutive_errors=consecutive_errors,
        )

    # Truncate tool messages to prevent large results from overflowing context
    truncated_messages = [truncate_tool_message_content(msg) for msg in state["messages"]]

    # Apply message trimming to prevent context overflow
    trimmed_messages = _message_trimmer.invoke(truncated_messages)
    messages = [system_message] + trimmed_messages

    hybrid_memory_context, prioritized_artifact_ids = await _retrieve_hybrid_memory_context(
        state, config
    )
    if hybrid_memory_context:
        memory_hint = SystemMessage(
            content=(
                "Ranked memory context for this query:\n"
                + "\n".join(f"- {entry}" for entry in hybrid_memory_context)
                + "\nUse higher-ranked items first, then request extra detail only when required."
            )
        )
        messages.append(memory_hint)
        logger.info(
            "Added hybrid memory context",
            memory_snippets=len(hybrid_memory_context),
            memory_chars=sum(len(entry) for entry in hybrid_memory_context),
            prioritized_artifacts=len(prioritized_artifact_ids),
        )

    rehydrated_artifacts = await _rehydrate_artifact_context(
        state,
        config,
        prioritized_artifact_ids=prioritized_artifact_ids,
    )
    if rehydrated_artifacts:
        artifact_hint = SystemMessage(
            content=(
                "Detailed excerpts rehydrated from full tool artifacts:\n"
                + "\n\n".join(rehydrated_artifacts)
                + "\nUse this evidence for precise answers."
            )
        )
        messages.append(artifact_hint)
        logger.info(
            "Added rehydrated artifact context",
            artifact_snippets=len(rehydrated_artifacts),
            artifact_chars=sum(len(entry) for entry in rehydrated_artifacts),
        )

    # If approaching limit or had errors, add a hint to summarize
    if approaching_limit or consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
        partial_results = state.get("partial_results", [])

        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS and partial_results:
            hint_content = (
                "IMPORTANT: Some tools encountered errors, but you have partial results. "
                f"Provide your best response based on the {len(partial_results)} results gathered. "
                "Be transparent about any limitations due to errors."
            )
        else:
            hint_content = (
                "IMPORTANT: You have gathered enough information. "
                "Do NOT make any more tool calls. "
                "Provide your final comprehensive response NOW based on the information you've collected."
            )

        hint = SystemMessage(content=hint_content)
        messages.append(hint)

    # Log context size for debugging
    total_chars = sum(len(str(m.content)) for m in messages if m.content)
    estimated_tokens = total_chars // 4
    logger.info(
        "Calling LLM",
        message_count=len(messages),
        estimated_tokens=estimated_tokens,
        tool_calls_count=tool_calls_count,
        model=model_deployment or "default",
    )

    try:
        # Invoke model
        response = await model.ainvoke(messages, config)

        duration_ms = (time.time() - start_time) * 1000

        # Update tool call count if this is a tool call
        new_tool_calls = 0
        if hasattr(response, "tool_calls") and response.tool_calls:
            new_tool_calls = len(response.tool_calls)
            tool_calls_count += new_tool_calls

        # Record metrics
        Metrics.record_node_execution("call_model", duration_ms / 1000)

        logger.info(
            "LLM call completed",
            duration_ms=round(duration_ms, 2),
            new_tool_calls=new_tool_calls,
            total_tool_calls=tool_calls_count,
            has_content=bool(response.content),
        )

        return {
            "messages": [response],
            "tool_calls_count": tool_calls_count,
            "consecutive_errors": 0,  # Reset on success
        }

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        logger.error(
            "LLM call failed",
            error=str(e),
            duration_ms=round(duration_ms, 2),
            tool_calls_count=tool_calls_count,
        )

        # Record error metrics
        Metrics.inc_counter(Metrics.GRAPH_ERRORS_TOTAL, {"node": "call_model"})

        # Check if we should retry
        if should_retry_exception(e):
            raise  # Let retry policy handle it

        # Non-retryable error - create error response
        error_msg = AIMessage(
            content=(
                f"I encountered an issue while processing your request: {str(e)}. "
                "Let me try to help with what I know."
            )
        )

        return {
            "messages": [error_msg],
            "tool_calls_count": tool_calls_count,
            "consecutive_errors": consecutive_errors + 1,
            "last_error": str(e),
        }


def base_should_continue(
    state: AgentState,
    max_iterations: int = DEFAULT_MAX_TOOL_ITERATIONS,
) -> Literal["tools", "error_handler", "__end__"]:
    """
    Base implementation for routing decision.

    Returns:
        "tools": If there are tool calls to execute
        "error_handler": If we've hit error threshold but have partial results
        "__end__": If no tool calls or max iterations exceeded
    """
    messages = state.get("messages", [])
    tool_calls_count = state.get("tool_calls_count", 0)
    consecutive_errors = state.get("consecutive_errors", 0)

    if not messages:
        return END

    last_message = messages[-1]

    # Check for tool calls
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        # Check iteration limit
        if tool_calls_count >= max_iterations:
            logger.warning(f"Reached max tool iterations ({max_iterations})," " forcing end")
            return END

        # Check error threshold - route to error handler if we have partial results
        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            partial_results = state.get("partial_results", [])
            if partial_results:
                logger.info(
                    "Error threshold reached with partial results, routing to error handler"
                )
                return "error_handler"
            return END

        return "tools"

    return END


def _parse_tool_payload(content: str) -> dict | list | str:
    """Parse tool message content preserving non-JSON payloads."""
    stripped = content.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return json.loads(stripped)
    return content


def _build_tool_memory_summary(tool_name: str, payload: dict | list | str) -> str:
    """Build a compact memory summary from tool payload."""
    if isinstance(payload, dict):
        if payload.get("error"):
            return f"{tool_name}: error - {str(payload.get('error'))[:140]}"

        count = payload.get("count")
        if isinstance(count, int):
            return f"{tool_name}: retrieved {count} result(s)"

        for key in ("results", "occurrences", "highlights", "timeline", "moments", "comparison"):
            value = payload.get(key)
            if isinstance(value, list):
                return f"{tool_name}: returned {len(value)} {key}"

        message = payload.get("message")
        if isinstance(message, str) and message:
            return f"{tool_name}: {message[:160]}"

        return f"{tool_name}: returned keys {', '.join(list(payload.keys())[:4])}"

    if isinstance(payload, list):
        return f"{tool_name}: returned list with {len(payload)} item(s)"

    text = payload if isinstance(payload, str) else str(payload)
    return f"{tool_name}: {text[:160]}"


async def _persist_tool_artifact(
    state: AgentState,
    config: RunnableConfig,
    *,
    tool_call_id: str | None,
    tool_name: str,
    payload: dict | list | str,
    summary: str,
) -> str | None:
    """Persist full tool payload as artifact and return artifact id."""
    session_id = state.get("session_id") or config.get("configurable", {}).get("thread_id")
    if not session_id:
        return None

    from core.config import settings

    if not settings.azure.is_storage_configured:
        return None

    from services.tool_artifact_service import get_tool_artifact_service

    media_id = state.get("media_id")

    artifact_service = await get_tool_artifact_service()
    artifact = await artifact_service.save_artifact(
        tool_call_id=tool_call_id or f"{tool_name}_{session_id}",
        tool_name=tool_name,
        session_id=session_id,
        thread_id=config.get("configurable", {}).get("thread_id"),
        user_id=state.get("user_id"),
        media_id=media_id,
        payload=payload,
        metadata={"summary": summary, "source": "langgraph_tool"},
    )
    return artifact.get("id")


async def update_context_node(state: AgentState, config: RunnableConfig) -> dict:
    """
    Update conversation context after tool execution.

    Extracts key topics and entities from the conversation
    to maintain context awareness across turns.
    Also tracks partial results for error recovery.
    """
    messages = state.get("messages", [])

    if not messages:
        return {}

    # Extract topics from recent messages
    current_context = state.get("conversation_context", [])
    new_topics = extract_topics_from_messages(messages[-2:])
    updated_context = list(set(current_context + new_topics))[-10:]

    # Track successful tool results for error recovery + compact memory
    partial_results = state.get("partial_results", [])
    memory_context = state.get("memory_context", [])
    artifact_refs = state.get("artifact_refs", [])

    # Check last message for tool results
    if messages:
        last_msg = messages[-1]
        if isinstance(last_msg, ToolMessage):
            try:
                content = (
                    last_msg.content if isinstance(last_msg.content, str) else str(last_msg.content)
                )
                result = _parse_tool_payload(content)
                result_dict = result if isinstance(result, dict) else {"raw": result}
                tool_name = getattr(last_msg, "name", "unknown") or "unknown"
                summary = _build_tool_memory_summary(tool_name, result)
                artifact_id = await _persist_tool_artifact(
                    state,
                    config,
                    tool_call_id=getattr(last_msg, "tool_call_id", None),
                    tool_name=tool_name,
                    payload=result,
                    summary=summary,
                )

                # Only track successful results
                if not result_dict.get("error"):
                    memory_entry = summary
                    if artifact_id:
                        memory_entry = f"{summary} [artifact:{artifact_id}]"
                        artifact_refs.append(
                            {
                                "artifact_id": artifact_id,
                                "tool_call_id": getattr(last_msg, "tool_call_id", None),
                                "tool_name": tool_name,
                                "summary": summary,
                            }
                        )

                    memory_context.append(memory_entry)
                    partial_results.append(
                        {
                            "tool": tool_name,
                            "summary": summary[:200],
                            "artifact_id": artifact_id,
                        }
                    )
                    # Keep last 10 partial results
                    partial_results = partial_results[-10:]
                    memory_context = memory_context[-20:]
                    artifact_refs = artifact_refs[-50:]
            except (json.JSONDecodeError, TypeError, ValueError, OSError) as exc:
                logger.warning(f"Failed to update tool memory context:" f" {_sanitize_log(exc)}")

    return {
        "conversation_context": updated_context,
        "partial_results": partial_results,
        "memory_context": memory_context,
        "artifact_refs": artifact_refs,
    }


# =============================================================================
# Error Handler Node (Graceful Degradation)
# =============================================================================


async def error_handler_node(state: AgentState, config: RunnableConfig) -> dict:
    """
    Handle errors gracefully by providing a partial response.

    This node is triggered when:
    - Multiple consecutive tool errors occur
    - We have partial results that can still be useful

    Instead of crashing, it generates a helpful response
    acknowledging the limitations.
    """
    partial_results = state.get("partial_results", [])
    last_error = state.get("last_error", "unknown error")
    consecutive_errors = state.get("consecutive_errors", 0)

    # Log error recovery
    logger.warning(
        "Error handler triggered - recovering gracefully",
        consecutive_errors=consecutive_errors,
        partial_results_count=len(partial_results),
        last_error=last_error,
    )

    # Record recovery metric
    Metrics.inc_counter(
        Metrics.ERROR_RECOVERIES,
        {
            "has_partial_results": str(bool(partial_results)).lower(),
        },
    )

    # Build a graceful response
    if partial_results:
        result_summary = "\n".join(
            [
                f"- {r.get('tool', 'unknown')}: {r.get('summary', '')[:100]}..."
                for r in partial_results[:5]
            ]
        )

        content = (
            f"I encountered some issues while searching ({last_error}), "
            f"but here's what I found so far:\n\n{result_summary}\n\n"
            "Would you like me to try a different approach?"
        )
    else:
        content = (
            f"I encountered an issue while processing your request: {last_error}. "
            "Could you please try rephrasing your question, or let me know if there's "
            "a specific aspect of the video you'd like me to focus on?"
        )

    response = AIMessage(content=content)

    logger.info(
        "Error handler completed - generated recovery response",
        response_length=len(content),
    )

    return {
        "messages": [response],
        "consecutive_errors": 0,  # Reset after handling
        "last_error": None,
    }


# =============================================================================
# Dynamic Tool Binding (P1 Improvement)
# =============================================================================


def select_tools_for_query(
    query: str,
    all_tools: list,
    max_tools: int = 8,
    is_multi_video: bool = False,
) -> list:
    """
    Dynamically select a focused subset of tools based on the query.

    Research shows binding 5-8 focused tools per turn improves
    LLM tool selection accuracy significantly.

    Args:
        query: User's query
        all_tools: All available tools
        max_tools: Maximum tools to bind
        is_multi_video: Whether the session has 2+ videos selected
            (library mode).  When True, multi-video / library tools
            are prioritised and at least one is always included.

    Returns:
        Focused subset of tools
    """
    query_lower = query.lower()

    tool_categories_by_name = {
        "search_video": ("search",),
        "describe_scene": ("search",),
        "find_entity": ("entity",),
        "get_transcript": ("subtitle",),
        "get_scene_context": ("context", "search"),
        "get_community_overview": ("structure", "analysis"),
        "list_chapters": ("structure",),
        "get_video_info": ("structure",),
        "get_summary": ("structure",),
        "get_related_content": ("analysis",),
        "get_entity_timeline": ("entity", "analysis"),
        "compare_moments": ("compare",),
        "find_highlights": ("highlight", "search"),
        "search_across_videos": ("library", "search"),
        "compare_videos": ("library", "compare"),
        "find_common_entities": ("library", "entity"),
        "get_library_overview": ("library", "structure"),
    }

    # Tool categories with keywords
    search_keywords = [
        "find",
        "search",
        "where",
        "when",
        "what",
        "show",
        "locate",
        "best",
        "highlight",
        "important",
        "interesting",
        "key",
        "moment",
    ]
    entity_keywords = [
        "who",
        "person",
        "people",
        "name",
        "character",
        "actor",
        "guest",
        "host",
        "interviewer",
        "presenter",
        "speaker",
    ]
    shared_entity_keywords = [
        "appear in both",
        "appears in both",
        "appear across",
        "appears across",
        "appear in multiple",
        "appears in multiple",
        "common",
        "in common",
        "same person",
        "same people",
        "same object",
        "same objects",
        "shared",
        "who appears",
    ]
    structure_keywords = [
        "chapter",
        "section",
        "part",
        "outline",
        "summary",
        "summarize",
        "summarise",
        "overview",
        "about",
        "theme",
        "topic",
        "info",
        "begin",
        "breakdown",
        "conclusion",
        "end",
        "finish",
        "introduction",
        "recap",
        "segment",
        "start",
        "structure",
    ]
    compare_keywords = ["compare", "difference", "similar", "versus", "vs"]
    edit_keywords = ["clip", "cut", "trim", "create", "add", "remove", "delete", "export"]
    subtitle_keywords = [
        "subtitle",
        "caption",
        "text",
        "transcri",
        "transcript",
        "quote",
        "narration",
        "exact",
        "verbatim",
        "dialogue",
        "said",
        "audio",
        "conversation",
        "hear",
        "listen",
        "say",
        "speech",
        "spoken",
        "talking",
        "tell",
        "told",
        "voice",
        "words",
    ]
    analysis_keywords = [
        "change",
        "connection",
        "develop",
        "evolution",
        "pattern",
        "progress",
        "related",
        "timeline",
        "track",
        "trend",
    ]
    library_keywords = [
        "across",
        "all videos",
        "compare",
        "both",
        "between",
        "every video",
        "each video",
        "all of them",
        "library",
        "multiple",
        "videos",
    ]

    # Keywords to identify library / multi-video tools by name or description
    library_tool_keywords = [
        "across",
        "compare_videos",
        "multi",
        "cross-video",
        "multiple videos",
        "library",
    ]

    # Categorize tools
    search_tools = []
    entity_tools = []
    structure_tools = []
    compare_tools = []
    edit_tools = []
    subtitle_tools = []
    analysis_tools = []
    context_tools = []
    highlight_tools = []
    library_tools = []
    other_tools = []

    for tool in all_tools:
        tool_name = tool.name.lower()
        tool_desc = (tool.description or "").lower()
        explicit_categories = tool_categories_by_name.get(tool_name, ())

        if "library" in explicit_categories or any(kw in tool_desc for kw in library_tool_keywords):
            library_tools.append(tool)

        if "subtitle" in explicit_categories:
            subtitle_tools.append(tool)
        if "context" in explicit_categories:
            context_tools.append(tool)
        if "highlight" in explicit_categories:
            highlight_tools.append(tool)

        if "compare" in explicit_categories:
            compare_tools.append(tool)
        elif "entity" in explicit_categories:
            entity_tools.append(tool)
        elif "structure" in explicit_categories:
            structure_tools.append(tool)
        elif "analysis" in explicit_categories:
            analysis_tools.append(tool)
        elif "search" in explicit_categories:
            search_tools.append(tool)
        elif any(kw in tool_desc for kw in edit_keywords):
            edit_tools.append(tool)
        elif any(kw in tool_desc for kw in subtitle_keywords):
            subtitle_tools.append(tool)
        elif any(kw in tool_desc for kw in compare_keywords):
            compare_tools.append(tool)
        elif any(kw in tool_desc for kw in entity_keywords):
            entity_tools.append(tool)
        elif any(kw in tool_desc for kw in structure_keywords):
            structure_tools.append(tool)
        elif any(kw in tool_desc for kw in analysis_keywords):
            analysis_tools.append(tool)
        elif any(kw in tool_desc for kw in search_keywords):
            search_tools.append(tool)
        else:
            other_tools.append(tool)

    # Check for multi-video / library intent in the query
    has_library_intent = is_multi_video and any(kw in query_lower for kw in library_keywords)
    has_shared_entity_intent = is_multi_video and (
        any(kw in query_lower for kw in shared_entity_keywords)
        or (
            any(kw in query_lower for kw in entity_keywords)
            and any(kw in query_lower for kw in ("both", "all videos", "multiple", "across"))
        )
    )
    has_subtitle_intent = any(kw in query_lower for kw in subtitle_keywords)

    # Select based on query intent
    selected = []

    def append_tool(tool) -> None:
        if tool and tool not in selected:
            selected.append(tool)

    def append_tool_by_name(tool_name: str) -> None:
        append_tool(next((candidate for candidate in all_tools if candidate.name == tool_name), None))

    def extend_unique(tools: list) -> None:
        for tool in tools:
            append_tool(tool)

    is_generic_timeline_query = "timeline" in query_lower and not any(
        kw in query_lower for kw in entity_keywords
    )

    if has_shared_entity_intent:
        append_tool_by_name("find_common_entities")
        append_tool_by_name("search_across_videos")
        append_tool_by_name("get_library_overview")
        for tool in entity_tools + structure_tools:
            if tool not in selected:
                selected.append(tool)
                if len(selected) >= max_tools:
                    break
    elif has_library_intent:
        # Multi-video mode with cross-video query: prioritise library tools
        selected.extend(library_tools[:3])
        for tool in search_tools + structure_tools:
            if tool not in selected:
                selected.append(tool)
                if len(selected) >= max_tools:
                    break
    elif has_subtitle_intent:
        append_tool_by_name("get_transcript")
        if any(kw in query_lower for kw in ("around", "before", "after", "context")):
            append_tool_by_name("get_scene_context")
        extend_unique(subtitle_tools[:3])
        if any(kw in query_lower for kw in ("around", "before", "after", "context")):
            extend_unique(context_tools[:1])
        extend_unique(search_tools[:2])
    elif any(kw in query_lower for kw in edit_keywords):
        selected.extend(edit_tools[:4])
        selected.extend(search_tools[:2])  # Often need to search first
    elif any(kw in query_lower for kw in compare_keywords):
        selected.extend(compare_tools[:2])
        selected.extend(search_tools[:3])
    elif any(kw in query_lower for kw in entity_keywords):
        selected.extend(entity_tools[:3])
        selected.extend(search_tools[:2])
    elif is_generic_timeline_query:
        preferred_timeline_tools = [
            "list_chapters",
            "get_video_info",
            "get_summary",
            "get_scene_context",
        ]
        for preferred_name in preferred_timeline_tools:
            if len(selected) >= max_tools:
                break
            tool = next(
                (candidate for candidate in structure_tools if candidate.name == preferred_name),
                None,
            )
            if tool and tool not in selected:
                selected.append(tool)
        for tool in analysis_tools + search_tools:
            if tool not in selected:
                selected.append(tool)
                if len(selected) >= max_tools:
                    break
    elif any(kw in query_lower for kw in structure_keywords):
        selected.extend(structure_tools[:3])
        selected.extend(search_tools[:2])
    elif any(kw in query_lower for kw in analysis_keywords):
        selected.extend(analysis_tools[:3])
        selected.extend(search_tools[:2])
    else:
        # Default: prioritize search
        selected.extend(search_tools[:4])
        selected.extend(entity_tools[:2])

    # In multi-video mode, guarantee at least 1 library tool is present
    if is_multi_video and library_tools and not any(t in library_tools for t in selected):
        if len(selected) >= max_tools:
            selected[-1] = library_tools[0]
        else:
            selected.append(library_tools[0])

    # Fill remaining slots (include all categories as fallback)
    remaining = max_tools - len(selected)
    if remaining > 0:
        fallback = (
            structure_tools
            + analysis_tools
            + context_tools
            + highlight_tools
            + other_tools
            + search_tools
            + entity_tools
            + compare_tools
        )
        if is_multi_video:
            # In multi-video mode, include library tools in the fallback pool
            fallback = library_tools + fallback
        for tool in fallback:
            if tool not in selected:
                selected.append(tool)
                if len(selected) >= max_tools:
                    break

    return selected[:max_tools]
