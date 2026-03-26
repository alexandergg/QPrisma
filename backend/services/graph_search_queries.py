"""
Graph Search Query Building
============================

Query execution helpers used by :class:`GraphSearchService`:
vector index queries, full-text search, and result merging.
Extracted as a mixin to keep the main service file focused.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from models.graph_models import NodeType

if TYPE_CHECKING:
    pass  # GraphSearchService types resolved at runtime

logger = logging.getLogger(__name__)

# Compiled regex for Lucene special character escaping (Neo4j fulltext uses Lucene 9.x).
# Characters: + - && || ! ( ) { } [ ] ^ " ~ * ? : \ /
_LUCENE_SPECIAL_RE = re.compile(r'([+\-&|!(){}\[\]^"~*?:\\/])')
_WHITESPACE_ONLY_RE = re.compile(r"^\s*$")


def sanitize_fulltext_query(query: str, *, max_length: int = 1000) -> str | None:
    """Escape Lucene special characters and validate the query.

    Returns the sanitised query string, or ``None`` when the input is
    empty, whitespace-only, or exceeds *max_length* (after stripping).
    """
    if not query or _WHITESPACE_ONLY_RE.match(query):
        return None
    text = query.strip()[:max_length]
    return _LUCENE_SPECIAL_RE.sub(r"\\\1", text) or None


# ---------------------------------------------------------------------------
# ScoredNode dataclass (shared across query + scoring modules)
# ---------------------------------------------------------------------------


@dataclass
class ScoredNode:
    """Node with scores from different sources."""

    node_id: str
    node_type: NodeType
    content: dict

    # Individual scores
    vector_score: float = 0.0
    fulltext_score: float = 0.0
    graph_score: float = 0.0
    temporal_score: float = 0.0

    # Combined score
    combined_score: float = 0.0

    # Expanded context
    related_nodes: list = field(default_factory=list)
    path_to_video: list = field(default_factory=list)

    # Metadata
    timestamp: float | None = None
    video_id: str | None = None


# ---------------------------------------------------------------------------
# Mixin
# ---------------------------------------------------------------------------


class GraphSearchQueryMixin:
    """Query building and execution helpers for :class:`GraphSearchService`."""

    # --- Vector search orchestrator ---

    def vector_search(
        self,
        query_embedding: list[float],
        node_type: NodeType,
        limit: int = 20,
        video_id: str | None = None,
        video_ids: list[str] | None = None,
        min_score: float = 0.5,
    ) -> list[ScoredNode]:
        """
        Two-pass Matryoshka vector search: coarse 512d filtering then full 3072d ranking.

        Pass 1: Query coarse (512d) index with wider limit for fast candidate retrieval.
        Pass 2: Re-rank candidates using full (3072d) embeddings for precise scoring.
        Falls back to single-pass full index if coarse index is unavailable.
        """
        label = node_type.value

        # --- Pass 1: Coarse search (512d, fast, wide net) ---
        coarse_embedding = query_embedding[:512]
        coarse_index = f"{label.lower()}_embedding_coarse"
        coarse_limit = limit * 5  # Wide net for coarse filtering

        coarse_candidates = self._run_vector_query(
            index_name=coarse_index,
            embedding=coarse_embedding,
            limit=coarse_limit,
            node_type=node_type,
            video_id=video_id,
            video_ids=video_ids,
            min_score=max(min_score - 0.15, 0.1),  # Lower threshold for coarse
        )

        if coarse_candidates:
            # --- Pass 2: Re-rank with full embeddings ---
            full_index = f"{label.lower()}_embedding"
            candidate_ids = [c.node_id for c in coarse_candidates]

            reranked = self._rerank_with_full_embeddings(
                candidate_ids=candidate_ids,
                query_embedding=query_embedding,
                node_type=node_type,
                limit=limit,
                min_score=min_score,
                full_index=full_index,
            )

            if reranked:
                return reranked
            # If re-ranking fails, use coarse scores as-is
            coarse_candidates.sort(key=lambda x: x.vector_score, reverse=True)
            return coarse_candidates[:limit]

        # --- Fallback: Direct full-precision search ---
        full_index = f"{label.lower()}_embedding"
        results = self._run_vector_query(
            index_name=full_index,
            embedding=query_embedding,
            limit=limit,
            node_type=node_type,
            video_id=video_id,
            video_ids=video_ids,
            min_score=min_score,
        )

        if not results:
            results = self._fallback_vector_search(
                query_embedding, node_type, limit, video_id, min_score, video_ids
            )

        return results

    # --- Low-level vector query ---

    def _run_vector_query(
        self,
        index_name: str,
        embedding: list[float],
        limit: int,
        node_type: NodeType,
        video_id: str | None = None,
        video_ids: list[str] | None = None,
        min_score: float = 0.5,
    ) -> list[ScoredNode]:
        """Execute a vector index query and return scored nodes."""
        if video_ids:
            query = """
                CALL db.index.vector.queryNodes($index_name, $limit * 2, $embedding)
                YIELD node, score
                WHERE node.video_id IN $video_ids AND score >= $min_score
                RETURN node, score
                ORDER BY score DESC LIMIT $limit
            """
            params = {
                "index_name": index_name,
                "embedding": embedding,
                "limit": limit,
                "video_ids": video_ids,
                "min_score": min_score,
            }
        elif video_id:
            query = """
                CALL db.index.vector.queryNodes($index_name, $limit * 2, $embedding)
                YIELD node, score
                WHERE node.video_id = $video_id AND score >= $min_score
                RETURN node, score
                ORDER BY score DESC LIMIT $limit
            """
            params = {
                "index_name": index_name,
                "embedding": embedding,
                "limit": limit,
                "video_id": video_id,
                "min_score": min_score,
            }
        else:
            query = """
                CALL db.index.vector.queryNodes($index_name, $limit, $embedding)
                YIELD node, score
                WHERE score >= $min_score
                RETURN node, score
                ORDER BY score DESC LIMIT $limit
            """
            params = {
                "index_name": index_name,
                "embedding": embedding,
                "limit": limit,
                "min_score": min_score,
            }

        results = []
        try:
            with self.graph_service.get_session() as session:
                result = session.run(query, **params)
                for record in result:
                    node_data = dict(record["node"])
                    node_data.pop("embedding", None)
                    node_data.pop("embedding_coarse", None)

                    results.append(
                        ScoredNode(
                            node_id=node_data.get("id"),
                            node_type=node_type,
                            content=node_data,
                            vector_score=record["score"],
                            timestamp=node_data.get("timestamp") or node_data.get("start_time"),
                            video_id=node_data.get("video_id"),
                        )
                    )
        except Exception as e:
            logger.warning(f"Vector query on {index_name} failed: {e}")

        return results

    # --- Re-ranking with full embeddings ---

    def _rerank_with_full_embeddings(
        self,
        candidate_ids: list[str],
        query_embedding: list[float],
        node_type: NodeType,
        limit: int,
        min_score: float,
        full_index: str,
    ) -> list[ScoredNode]:
        """Re-rank coarse candidates using full 3072d embeddings."""
        label = node_type.value
        query = f"""
            MATCH (n:{label})
            WHERE n.id IN $ids AND n.embedding IS NOT NULL
            WITH n,
                 gds.similarity.cosine(n.embedding, $embedding) AS score
            WHERE score >= $min_score
            RETURN n AS node, score
            ORDER BY score DESC
            LIMIT $limit
        """

        results = []
        try:
            with self.graph_service.get_session() as session:
                result = session.run(
                    query,
                    ids=candidate_ids,
                    embedding=query_embedding,
                    min_score=min_score,
                    limit=limit,
                )
                for record in result:
                    node_data = dict(record["node"])
                    node_data.pop("embedding", None)
                    node_data.pop("embedding_coarse", None)

                    results.append(
                        ScoredNode(
                            node_id=node_data.get("id"),
                            node_type=node_type,
                            content=node_data,
                            vector_score=record["score"],
                            timestamp=node_data.get("timestamp") or node_data.get("start_time"),
                            video_id=node_data.get("video_id"),
                        )
                    )
        except Exception as e:
            # gds.similarity.cosine may not be available — fall back gracefully
            logger.debug(f"Full embedding re-rank failed (GDS may not be installed): {e}")

        return results

    # --- Fallback manual vector search ---

    def _fallback_vector_search(
        self,
        query_embedding: list[float],
        node_type: NodeType,
        limit: int,
        video_id: str | None,
        min_score: float,
        video_ids: list[str] | None = None,
    ) -> list[ScoredNode]:
        """
        Manual vector search used when the index is unavailable.
        Less efficient but functional.
        """
        label = node_type.value

        if video_ids:
            query = f"""
                MATCH (n:{label})
                WHERE n.video_id IN $video_ids
                    AND n.embedding IS NOT NULL
                RETURN n
            """
            params: dict = {"video_ids": video_ids}
        elif video_id:
            query = f"""
                MATCH (n:{label})
                WHERE n.video_id = $video_id AND n.embedding IS NOT NULL
                RETURN n
            """
            params = {"video_id": video_id}
        else:
            query = f"""
                MATCH (n:{label})
                WHERE n.embedding IS NOT NULL
                RETURN n
                LIMIT 1000
            """
            params = {}

        results = []

        with self.graph_service.get_session() as session:
            result = session.run(query, **params)

            for record in result:
                node_data = dict(record["n"])
                node_embedding = node_data.pop("embedding", None)
                node_data.pop("embedding_coarse", None)

                if node_embedding:
                    score = self.embedding_service.compute_similarity(
                        query_embedding, node_embedding
                    )

                    if score >= min_score:
                        scored = ScoredNode(
                            node_id=node_data.get("id"),
                            node_type=node_type,
                            content=node_data,
                            vector_score=score,
                            timestamp=node_data.get("timestamp") or node_data.get("start_time"),
                            video_id=node_data.get("video_id"),
                        )
                        results.append(scored)

        # Sort by score and limit
        results.sort(key=lambda x: x.vector_score, reverse=True)
        return results[:limit]

    # --- Full-text search ---

    _INDEX_BY_TYPE: dict[NodeType, str] = {
        NodeType.FRAME: "frame_search",
        NodeType.ENTITY: "entity_search",
        NodeType.AUDIO_SEGMENT: "audio_search",
        NodeType.COMMUNITY: "community_search",
    }

    def _fulltext_search(
        self,
        query_text: str,
        node_type: NodeType,
        limit: int,
        video_id: str | None,
        video_ids: list[str] | None = None,
    ) -> list[tuple[str, float]]:
        """Full-text search with Lucene escaping; returns [(node_id, score)]."""
        index_name = self._INDEX_BY_TYPE.get(node_type)
        if index_name is None:
            return []

        safe_query = sanitize_fulltext_query(query_text)
        if safe_query is None:
            logger.debug("Fulltext query empty after sanitisation — skipping")
            return []

        label = node_type.value

        # Build optional video filter
        video_filter = ""
        params: dict = {
            "index_name": index_name,
            "query_text": safe_query,
            "limit": limit,
        }
        if video_ids:
            video_filter = "AND node.video_id IN $video_ids"
            params["video_ids"] = video_ids
        elif video_id:
            video_filter = "AND node.video_id = $video_id"
            params["video_id"] = video_id

        query = f"""
            CALL db.index.fulltext.queryNodes($index_name, $query_text)
            YIELD node, score
            WHERE node:{label} {video_filter}
            RETURN node.id AS id, score
            LIMIT $limit
        """

        try:
            with self.graph_service.get_session() as session:
                result = session.run(query, **params)
                return [(r["id"], r["score"]) for r in result]
        except Exception as e:
            logger.warning("Full-text search failed for %s: %s", index_name, e)
            return []

    # --- Merge full-text scores into candidates ---

    def _merge_fulltext_scores(
        self,
        candidates: list[ScoredNode],
        fulltext_results: list[tuple[str, float]],
        node_type: NodeType,
        video_id: str | None = None,
    ) -> None:
        """
        Merge full-text scores into existing candidates.
        Also adds new candidates that were found only by full-text search.
        """
        fulltext_map = dict(fulltext_results)

        # Normalizar scores full-text
        if fulltext_map:
            max_score = max(fulltext_map.values())
            if max_score > 0:
                fulltext_map = {k: v / max_score for k, v in fulltext_map.items()}

        # Update existing candidates
        existing_ids = set()
        for candidate in candidates:
            existing_ids.add(candidate.node_id)
            if candidate.node_id in fulltext_map:
                candidate.fulltext_score = fulltext_map[candidate.node_id]

        # Add new candidates from fulltext that weren't in vector results
        new_node_ids = set(fulltext_map.keys()) - existing_ids
        if new_node_ids:
            # Fetch node data for new fulltext matches
            for node_id in list(new_node_ids)[:20]:  # Limit to avoid too many queries
                try:
                    node_data = self._get_node_by_id(node_id, node_type)
                    if node_data:
                        scored = ScoredNode(
                            node_id=node_id,
                            node_type=node_type,
                            content=node_data,
                            vector_score=0.0,  # No vector match
                            fulltext_score=fulltext_map[node_id],
                            timestamp=node_data.get("timestamp") or node_data.get("start_time"),
                            video_id=node_data.get("video_id"),
                        )
                        candidates.append(scored)
                except Exception as e:
                    logger.warning(f"Failed to fetch node {node_id}: {e}")

    # --- Fetch a single node ---

    def _get_node_by_id(self, node_id: str, node_type: NodeType) -> dict | None:
        """Fetch a single node by ID."""
        label = node_type.value
        query = f"""
            MATCH (n:{label} {{id: $node_id}})
            RETURN n
        """
        try:
            with self.graph_service.get_session() as session:
                result = session.run(query, node_id=node_id)
                record = result.single()
                if record:
                    node_data = dict(record["n"])
                    node_data.pop("embedding", None)  # Remove large embedding
                    return node_data
        except Exception as e:
            logger.warning(f"Failed to get node {node_id}: {e}")
        return None
