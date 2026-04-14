"""
Tool Response Metadata
======================

Lightweight helpers that attach quality metadata to agent tool responses,
so the LLM can distinguish complete data from truncated/fallback/partial
results and adapt its language accordingly.
"""


def tool_meta(
    *,
    source: str = "graph",
    is_complete: bool = True,
    truncated_fields: list[str] | None = None,
    result_count: int | None = None,
    total_available: int | None = None,
    detail_hint: str | None = None,
) -> dict:
    """Build a ``_meta`` dict for a tool response.

    Parameters
    ----------
    detail_hint
        Navigational cue telling the LLM how to retrieve deeper detail.
        Example: ``"Use get_scene_context(timestamp=120) for frame-level
        descriptions, detected objects, and audio for any scene."``
    """
    meta: dict = {"source": source, "is_complete": is_complete}
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
) -> dict:
    """Build a structured error response for a tool."""
    err: dict = {
        "error": {"type": error_type, "message": message},
        "_meta": {"source": source, "is_complete": False, "result_count": 0},
    }
    if recovery:
        err["error"]["recovery"] = recovery
    if partial_data:
        err["partial_data"] = partial_data
    return err
