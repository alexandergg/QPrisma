"""
Tool Response Metadata
======================

Canonical LangGraph tool payload helpers.

QPrisma agent tools return JSON-serializable dictionaries and never raise
runtime exceptions for expected failures. Successful payloads are domain
specific but MUST include ``_meta`` from :func:`tool_meta`; error payloads
MUST use :func:`tool_error` and include:

* ``error``: structured ``{"type": str, "message": str, ...}``
* ``results``: an empty list for ToolNode/API consumers expecting list results
* ``count``: ``0`` for ToolNode/API consumers expecting count results
* ``_meta``: incomplete metadata with ``result_count=0``

The compatibility ``results``/``count`` fields are intentionally present on
all errors even when the corresponding success payload uses a different
domain key such as ``occurrences`` or ``timeline``.
"""

from typing import Any, NotRequired, TypedDict


class ToolMeta(TypedDict, total=False):
    """Canonical ``_meta`` payload attached to LangGraph tool responses."""

    source: str
    is_complete: bool
    truncated_fields: list[str]
    result_count: int
    total_available: int
    detail_hint: str


class ToolErrorDetail(TypedDict):
    """Canonical structured tool error detail."""

    type: str
    message: str
    recovery: NotRequired[str]


class ToolErrorPayload(TypedDict):
    """Canonical LangGraph tool error payload."""

    error: ToolErrorDetail
    results: list[Any]
    count: int
    _meta: ToolMeta
    partial_data: NotRequired[dict[str, Any]]


class ToolSuccessPayload(TypedDict, total=False):
    """Base contract for successful LangGraph tool payloads."""

    _meta: ToolMeta


def tool_meta(
    *,
    source: str = "graph",
    is_complete: bool = True,
    truncated_fields: list[str] | None = None,
    result_count: int | None = None,
    total_available: int | None = None,
    detail_hint: str | None = None,
) -> ToolMeta:
    """Build a ``_meta`` dict for a tool response.

    Parameters
    ----------
    detail_hint
        Navigational cue telling the LLM how to retrieve deeper detail.
        Example: ``"Use get_scene_context(timestamp=120) for frame-level
        descriptions, detected objects, and audio for any scene."``
    """
    meta: ToolMeta = {"source": source, "is_complete": is_complete}
    if truncated_fields:
        meta["truncated_fields"] = truncated_fields
    if result_count is not None:
        meta["result_count"] = result_count
    if total_available is not None and total_available != result_count:
        meta["total_available"] = total_available
    if detail_hint:
        meta["detail_hint"] = detail_hint
    return meta


def truncate_with_notice(text: str, limit: int) -> tuple[str, bool]:
    """Truncate *text* to *limit* chars, appending an ellipsis notice.

    Returns ``(text, was_truncated)``.
    """
    if not text or len(text) <= limit:
        return text, False
    return text[:limit] + f" […{len(text) - limit} chars omitted]", True


def tool_error(
    error_type: str,
    message: str,
    recovery: str | None = None,
    partial_data: dict | None = None,
    source: str = "error",
) -> ToolErrorPayload:
    """Build a structured error response for a tool."""
    err: ToolErrorPayload = {
        "error": {"type": error_type, "message": message},
        "results": [],
        "count": 0,
        "_meta": {"source": source, "is_complete": False, "result_count": 0},
    }
    if recovery:
        err["error"]["recovery"] = recovery
    if partial_data:
        err["partial_data"] = partial_data
    return err


def is_tool_error_payload(payload: object) -> bool:
    """Return whether *payload* follows the canonical tool error contract."""
    return (
        isinstance(payload, dict)
        and isinstance(payload.get("error"), dict)
        and payload.get("results") == []
        and payload.get("count") == 0
        and isinstance(payload.get("_meta"), dict)
        and payload["_meta"].get("is_complete") is False
    )
