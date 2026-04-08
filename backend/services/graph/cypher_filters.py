"""Shared Cypher filter builders for Neo4j queries.

Centralizes keyword sanitization and filter clause generation used by
knowledge_graph.py and other graph query modules.
"""

import re

MAX_KEYWORDS = 5
MIN_KEYWORD_LENGTH = 3


def sanitize_keywords(
    query_text: str,
    *,
    max_keywords: int = MAX_KEYWORDS,
    min_length: int = MIN_KEYWORD_LENGTH,
) -> list[str]:
    """Split query into sanitized keywords safe for Cypher parameterization.

    - Strips non-word characters (keeps letters, digits, underscores, spaces)
    - Filters keywords shorter than *min_length*
    - Caps at *max_keywords* to prevent query bloat

    Returns:
        List of safe keyword strings (may be empty).
    """
    keywords = [
        re.sub(r"[^\w\s]", "", w.strip())
        for w in query_text.split()
        if len(w.strip()) >= min_length
    ][:max_keywords]
    return [kw for kw in keywords if kw]


def build_keyword_filter(
    property_expr: str,
    safe_keywords: list[str],
    *,
    fallback_param: str = "$query_text",
) -> str:
    """Return a Cypher WHERE clause fragment for keyword matching.

    When *safe_keywords* is non-empty, produces an ``ANY()`` predicate that
    checks each keyword against the property via ``CONTAINS``.  When empty,
    falls back to a simple ``CONTAINS`` on *fallback_param*.

    Args:
        property_expr: The Cypher property access, e.g. ``"f.description"``
            or ``"a.text"``.
        safe_keywords: Pre-sanitized keyword list (from :func:`sanitize_keywords`).
        fallback_param: Cypher parameter name for the raw query text.

    Returns:
        A Cypher expression string (no leading ``WHERE`` / ``AND``).
    """
    if safe_keywords:
        return f"ANY(kw IN $keywords WHERE toLower({property_expr}) CONTAINS toLower(kw))"
    return f"toLower({property_expr}) CONTAINS toLower({fallback_param})"
