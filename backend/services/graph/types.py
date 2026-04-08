"""Shared type definitions for the Knowledge Graph service layer.

These TypedDicts describe the shapes returned by KnowledgeGraphService methods
and graph_expander queries.  Using explicit types instead of bare ``dict``
improves IDE autocomplete, static analysis, and documentation.
"""

from __future__ import annotations

from typing import Any, TypedDict

# ---------------------------------------------------------------------------
# Multimodal search
# ---------------------------------------------------------------------------


class MultimodalSearchResult(TypedDict):
    """Return shape of ``KnowledgeGraphService.search_multimodal``."""

    query: str
    visual_results: list[dict[str, Any]]
    audio_results: list[dict[str, Any]]
    combined_timeline: list[dict[str, Any]]
    total_visual: int
    total_audio: int


# ---------------------------------------------------------------------------
# Graph expansion / subgraph
# ---------------------------------------------------------------------------


class SubgraphResult(TypedDict):
    """Return shape of ``get_video_subgraph`` and ``expand_node_subgraph``."""

    nodes: list[dict[str, Any]]
    relationships: list[dict[str, Any]]


# expand_context returns a plain dict keyed by hop distance.
# A TypedDict cannot represent int keys, so we use a type alias instead.
ExpandContextNodes = dict[int, list[dict[str, Any]]]
