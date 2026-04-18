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

from models.graph_models import NodeType

logger = logging.getLogger(__name__)

# Compiled regex for Lucene special character escaping (Neo4j fulltext uses Lucene 9.x).
# Neo4j fulltext indexes delegate query parsing to Apache Lucene, which
# treats these characters as syntax: + - && || ! ( ) { } [ ] ^ " ~ * ? : \ /
# Unescaped user input containing these characters causes ParseException or
# alters query semantics (e.g. "*" triggers wildcard expansion).
# We escape each occurrence with a leading backslash so the character is
# matched literally.  Reference:
#   https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/full-text-indexes/
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

    # Node types that have vector indexes provisioned by
    # ``GraphSearchService._create_vector_indexes``. Calling
    # ``db.index.vector.queryNodes`` for any other type raises
    # ``ProcedureCallFailed`` on every request — pure log noise.
    # Topic embeddings are not generated anywhere in the pipeline; add the
    # type here once topic embeddings are introduced.
    _VECTOR_SUPPORTED_TYPES: frozenset[NodeType] = frozenset(
        {
            NodeType.FRAME,
            NodeType.ENTITY,
            NodeType.AUDIO_SEGMENT,
            NodeType.COMMUNITY,
        }
    )

    # --- Vector search orchestrator ---

    def vector_search(
        self,
        query_embedding: list[float],
        node_type: NodeType,
        limit: int = 20,
        video_id: str | None = None,
        video_ids: list[str] | None = None,
        user_id: str | None = None,
        min_score: float = 0.5,
        timeout_s: float | None = None,
    ) -> list[ScoredNode]:
        """
        Two-pass Matryoshka vector search: coarse 512d filtering then full 3072d ranking.

        Pass 1: Query coarse (512d) index with wider limit for fast candidate retrieval.
        Pass 2: Re-rank candidates using full (3072d) embeddings for precise scoring.
        Falls back to single-pass full index if coarse index is unavailable.
        """
        if node_type not in self._VECTOR_SUPPORTED_TYPES:
            logger.debug(
                "vector_search: skipping %s — no vector index provisioned for this type",
                node_type.value,
            )
            return []

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
            user_id=user_id,
            min_score=max(min_score - 0.15, 0.1),  # Lower threshold for coarse
            timeout_s=timeout_s,
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
                user_id=user_id,
                timeout_s=timeout_s,
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
            user_id=user_id,
            min_score=min_score,
            timeout_s=timeout_s,
        )

        # No further fallback — if neither index exists, fulltext search
        # carries the pipeline. The old _fallback_vector_search did a full
        # table scan pulling all 3072-dim embeddings which was catastrophic.
        if not results:
            logger.info(
                "vector_search: no results for %s (indexes may not exist) — "
                "fulltext search will cover this node type",
                label,
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
        user_id: str | None = None,
        min_score: float = 0.5,
        timeout_s: float | None = None,
    ) -> list[ScoredNode]:
        """Execute a vector index query and return scored nodes."""
        from neo4j import Query

        filters = ["score >= $min_score"]
        params = {
            "index_name": index_name,
            "embedding": embedding,
            "limit": limit,
            "query_limit": limit * 2 if (video_ids or video_id or user_id) else limit,
            "min_score": min_score,
        }

        if video_ids:
            filters.append("node.video_id IN $video_ids")
            params["video_ids"] = video_ids
        elif video_id:
            filters.append("node.video_id = $video_id")
            params["video_id"] = video_id

        if user_id:
            filters.append("node.user_id = $user_id")
            params["user_id"] = user_id

        cypher = f"""
            CALL db.index.vector.queryNodes($index_name, $query_limit, $embedding)
            YIELD node, score
            WHERE {' AND '.join(filters)}
            RETURN node, score
            ORDER BY score DESC LIMIT $limit
        """

        results = []
        try:
            with self.graph_service.get_session() as session:
                q = Query(cypher, timeout=timeout_s) if timeout_s else cypher
                result = session.run(q, **params)
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
            err_str = str(e).lower()
            if (
                "no such index" in err_str
                or "index not found" in err_str
                or "no such vector schema index" in err_str
            ):
                logger.info("Vector index '%s' does not exist — skipping", index_name)
            else:
                logger.warning(
                    "Vector query on %s failed: %s — %s", index_name, type(e).__name__, str(e)
                )
                logger.debug("Vector query on %s traceback", index_name, exc_info=True)

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
        user_id: str | None = None,
        timeout_s: float | None = None,
    ) -> list[ScoredNode]:
        """Re-rank coarse candidates using full 3072d embeddings."""
        from neo4j import Query

        label = node_type.value
        filters = ["n.id IN $ids", "n.embedding IS NOT NULL"]
        params = {
            "ids": candidate_ids,
            "embedding": query_embedding,
            "min_score": min_score,
            "limit": limit,
        }
        if user_id:
            filters.append("n.user_id = $user_id")
            params["user_id"] = user_id

        cypher = f"""
            MATCH (n:{label})
            WHERE {' AND '.join(filters)}
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
                q = Query(cypher, timeout=timeout_s) if timeout_s else cypher
                result = session.run(q, **params)
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
            logger.debug(
                "Full embedding re-rank failed (GDS may not be installed): %s", type(e).__name__
            )

        return results

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
        user_id: str | None = None,
        timeout_s: float | None = None,
    ) -> list[tuple[str, float]]:
        """Full-text search with Lucene escaping; returns [(node_id, score)]."""
        from neo4j import Query

        index_name = self._INDEX_BY_TYPE.get(node_type)
        if index_name is None:
            return []

        safe_query = sanitize_fulltext_query(query_text)
        if safe_query is None:
            logger.debug("Fulltext query empty after sanitisation — skipping")
            return []

        label = node_type.value

        filters = [f"node:{label}"]
        params: dict = {
            "index_name": index_name,
            "query_text": safe_query,
            "limit": limit,
        }
        if video_ids:
            filters.append("node.video_id IN $video_ids")
            params["video_ids"] = video_ids
        elif video_id:
            filters.append("node.video_id = $video_id")
            params["video_id"] = video_id
        if user_id:
            filters.append("node.user_id = $user_id")
            params["user_id"] = user_id

        cypher = f"""
            CALL db.index.fulltext.queryNodes($index_name, $query_text)
            YIELD node, score
            WHERE {' AND '.join(filters)}
            RETURN node.id AS id, score
            LIMIT $limit
        """

        try:
            with self.graph_service.get_session() as session:
                q = Query(cypher, timeout=timeout_s) if timeout_s else cypher
                result = session.run(q, **params)
                return [(r["id"], r["score"]) for r in result]
        except Exception as e:
            logger.warning("Full-text search failed for %s: %s", index_name, type(e).__name__)
            return []

    # --- Merge full-text scores into candidates ---

    def _merge_fulltext_scores(
        self,
        candidates: list[ScoredNode],
        fulltext_results: list[tuple[str, float]],
        node_type: NodeType,
        video_id: str | None = None,
        video_ids: list[str] | None = None,
        user_id: str | None = None,
        timeout_s: float | None = None,
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
        new_node_ids: list[str] = []
        for node_id, _score in fulltext_results:
            if node_id not in existing_ids and node_id not in new_node_ids:
                new_node_ids.append(node_id)

        if new_node_ids:
            # Fetch node data for new fulltext matches
            limited_node_ids = new_node_ids[:20]
            node_data_by_id = self._get_nodes_by_ids(
                limited_node_ids,
                node_type=node_type,
                video_id=video_id,
                video_ids=video_ids,
                user_id=user_id,
                timeout_s=timeout_s,
            )
            for node_id in limited_node_ids:
                node_data = node_data_by_id.get(node_id)
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

    def _get_nodes_by_ids(
        self,
        node_ids: list[str],
        node_type: NodeType,
        video_id: str | None = None,
        video_ids: list[str] | None = None,
        user_id: str | None = None,
        timeout_s: float | None = None,
    ) -> dict[str, dict]:
        """Fetch multiple nodes of the same type in a single Cypher query."""
        from neo4j import Query

        unique_node_ids = list(dict.fromkeys(node_ids))
        if not unique_node_ids:
            return {}

        label = node_type.value
        filters = []
        params: dict = {"node_ids": unique_node_ids}

        if video_ids:
            filters.append("n.video_id IN $video_ids")
            params["video_ids"] = video_ids
        elif video_id:
            filters.append("n.video_id = $video_id")
            params["video_id"] = video_id

        if user_id:
            filters.append("n.user_id = $user_id")
            params["user_id"] = user_id

        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        cypher = f"""
            UNWIND $node_ids AS node_id
            MATCH (n:{label} {{id: node_id}})
            {where_clause}
            RETURN n
        """

        try:
            with self.graph_service.get_session() as session:
                q = Query(cypher, timeout=timeout_s) if timeout_s else cypher
                result = session.run(q, **params)
                nodes_by_id: dict[str, dict] = {}
                for record in result:
                    node_data = dict(record["n"])
                    node_data.pop("embedding", None)
                    nodes_by_id[node_data["id"]] = node_data
                return nodes_by_id
        except Exception as e:
            preview_ids = ", ".join(unique_node_ids[:5])
            logger.warning("Failed to batch fetch nodes [%s]: %s", preview_ids, e)
            return {}

    # --- Fetch a single node ---

    def _get_node_by_id(
        self, node_id: str, node_type: NodeType, user_id: str | None = None
    ) -> dict | None:
        """Fetch a single node by ID.

        Args:
            user_id: When provided, verify ownership before returning.
        """
        label = node_type.value
        user_filter = " AND n.user_id = $user_id" if user_id else ""
        query = f"""
            MATCH (n:{label} {{id: $node_id}})
            WHERE true{user_filter}
            RETURN n
        """
        params: dict = {"node_id": node_id}
        if user_id:
            params["user_id"] = user_id
        try:
            with self.graph_service.get_session() as session:
                result = session.run(query, **params)
                record = result.single()
                if record:
                    node_data = dict(record["n"])
                    node_data.pop("embedding", None)
                    return node_data
        except Exception as e:
            logger.warning(f"Failed to get node {node_id}: {e}")
        return None
