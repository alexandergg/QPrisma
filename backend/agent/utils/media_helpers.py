"""
Media-selection and benchmark helpers (formerly in agent.context_envelopes).

The QPrisma context envelope (``[QPRISMA_CONTEXT:...]``) used by the deprecated
preview hosting protocol has been removed. The frontend and the
``foundry_agent_client`` now pass media metadata via the refreshed Foundry
``responses.create(metadata=...)`` field, and the hosted runtime exposes it
through ``request.metadata``.

These two helpers are kept because they are still used by both the agent
nodes (``restore_media_context``) and the request-side metadata builder.
"""

from __future__ import annotations

from typing import Any


def normalize_media_selection(
    media_id: Any,
    media_ids: Any,
) -> tuple[str | None, list[str]]:
    """Normalize explicit and list-shaped media selection fields."""
    normalized_media_id = media_id if isinstance(media_id, str) and media_id else None
    normalized_media_ids = (
        [item for item in media_ids if isinstance(item, str) and item]
        if isinstance(media_ids, list)
        else []
    )

    if normalized_media_id is None and len(normalized_media_ids) == 1:
        normalized_media_id = normalized_media_ids[0]

    return normalized_media_id, normalized_media_ids


def is_letter_only_benchmark(benchmark_context: Any) -> bool:
    """Return True for Video-MME-style MCQ letter-only evaluation requests."""
    if not isinstance(benchmark_context, dict):
        return False

    eval_mode = str(benchmark_context.get("eval_mode") or "").lower()
    response_format = str(benchmark_context.get("format") or "").lower()
    return eval_mode == "mcq" and response_format == "letter_only"
