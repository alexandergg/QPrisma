"""
Graph Search Scoring & Result Assembly
========================================

Scoring helpers used by :class:`GraphSearchService`:
temporal scoring, graph connectivity scoring, context-based re-ranking,
and utility counters.  Extracted as a mixin.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.graph_search_queries import ScoredNode

logger = logging.getLogger(__name__)


class GraphSearchScoringMixin:
    """Scoring and result assembly helpers for :class:`GraphSearchService`."""

    # --- Temporal filter ---

    def _filter_by_time_range(
        self,
        candidates: list[ScoredNode],
        time_range: tuple[float, float],
    ) -> list[ScoredNode]:
        """Filter candidates by temporal range."""
        start, end = time_range
        return [c for c in candidates if c.timestamp is None or (start <= c.timestamp <= end)]

    # --- Graph connectivity scoring ---

    def _calculate_graph_scores(
        self,
        candidates: list[ScoredNode],
        expansion_hops: int,
        user_id: str | None = None,
        timeout_s: float | None = None,
    ) -> None:
        """
        Calculate graph scores based on connectivity and expansion.

        More connected nodes that are closer to the centre of the graph receive higher scores.
        """
        if not candidates:
            return

        # Reduce expansion set for large candidate counts
        if len(candidates) > 50:
            expansion_hops = min(expansion_hops, 1)
            logger.info(
                "graph_scores: reduced hops to 1 for %d candidates",
                len(candidates),
            )

        candidate_ids = [candidate.node_id for candidate in candidates]
        expansions_by_node = self._batch_expand_context(
            candidate_ids,
            expansion_hops=expansion_hops,
            user_id=user_id,
            timeout_s=timeout_s,
        )
        paths_by_node = self._batch_get_paths_to_video(
            candidate_ids, user_id=user_id, timeout_s=timeout_s
        )

        for candidate in candidates:
            expansion = expansions_by_node.get(candidate.node_id) if expansions_by_node else None
            path_to_video = paths_by_node.get(candidate.node_id, []) if paths_by_node else []

            if expansions_by_node is None:
                candidate.graph_score = 0.0
                candidate.related_nodes = []
            else:
                total_related = expansion.get("total_related", 0) if expansion else 0
                candidate.graph_score = min(1.0, (1 + total_related) / 50)
                candidate.related_nodes = expansion.get("related_nodes", []) if expansion else []

            candidate.path_to_video = path_to_video

    # --- Temporal scoring ---

    def _calculate_temporal_scores(
        self,
        candidates: list[ScoredNode],
        time_range: tuple[float, float] | None,
    ) -> None:
        """
        Calculate temporal scores based on temporal position.

        When a time range is specified, nodes closer to the centre receive higher scores.
        Otherwise, the score is based on whether a timestamp is present.
        """
        if not candidates:
            return

        # If a temporal range is provided, calculate proximity to the centre
        if time_range:
            center = (time_range[0] + time_range[1]) / 2
            range_width = time_range[1] - time_range[0]

            for candidate in candidates:
                if candidate.timestamp is not None:
                    distance = abs(candidate.timestamp - center)
                    # Gaussian score
                    candidate.temporal_score = math.exp(-0.5 * (distance / (range_width / 2)) ** 2)
                else:
                    candidate.temporal_score = 0.5  # Neutral score
        else:
            # No range provided — score based on whether a timestamp is present
            for candidate in candidates:
                candidate.temporal_score = 0.7 if candidate.timestamp is not None else 0.3

        # Boost candidates that are temporally adjacent to other high-scoring candidates
        self._boost_temporal_adjacency(candidates)

    def _boost_temporal_adjacency(self, candidates: list[ScoredNode]) -> None:
        """Boost temporal scores for candidates adjacent via NEXT_* chains.

        If two candidates are within a small timestamp gap, apply a mutual boost
        proportional to the other candidate's vector score.
        """
        if len(candidates) < 2:
            return

        # Build a lookup of timestamped candidates for fast neighbour detection
        timestamped = [(i, c) for i, c in enumerate(candidates) if c.timestamp is not None]

        if len(timestamped) < 2:
            return

        # Sort by timestamp
        timestamped.sort(key=lambda x: x[1].timestamp)

        # Boost adjacent candidates (within 15s gap)
        adjacency_threshold = 15.0
        max_boost = 0.15

        for idx in range(len(timestamped) - 1):
            i, curr = timestamped[idx]
            j, nxt = timestamped[idx + 1]

            gap = abs(nxt.timestamp - curr.timestamp)
            if gap <= adjacency_threshold:
                proximity = 1.0 - (gap / adjacency_threshold)
                boost = proximity * max_boost
                candidates[i].temporal_score = min(
                    1.0, candidates[i].temporal_score + boost * nxt.vector_score
                )
                candidates[j].temporal_score = min(
                    1.0, candidates[j].temporal_score + boost * curr.vector_score
                )

    # --- Context-based re-ranking ---

    def _rerank_with_context(
        self,
        candidates: list[ScoredNode],
        query_text: str,
        query_embedding: list[float],
    ) -> list[ScoredNode]:
        """
        Re-ranking using expanded context.

        For each candidate, also considers the relevance of its related nodes.
        """
        for candidate in candidates:
            if not candidate.related_nodes:
                continue

            # Calculate boost based on relevance of related nodes
            context_boost = 0.0
            related_count = 0

            for related in candidate.related_nodes[:10]:
                node_data = related.get("node", {})
                distance = related.get("distance", 1)

                # Text of the related node
                related_text = node_data.get("description") or node_data.get("name", "")

                if related_text:
                    # Bonus for term overlap
                    query_terms = set(query_text.lower().split())
                    related_terms = set(related_text.lower().split())
                    overlap = len(query_terms & related_terms)

                    if overlap > 0:
                        # Boost decays with distance
                        term_boost = (overlap / len(query_terms)) / (distance + 1)
                        context_boost += term_boost
                        related_count += 1

            # Apply boost (maximum 20% increase)
            if related_count > 0:
                avg_boost = context_boost / related_count
                candidate.combined_score *= 1 + min(0.2, avg_boost)

        return candidates

    # --- Path & counting helpers ---

    def _batch_expand_context(
        self,
        node_ids: list[str],
        expansion_hops: int,
        user_id: str | None = None,
        max_nodes: int = 30,
        timeout_s: float | None = None,
    ) -> dict[str, dict] | None:
        """Batch graph expansion for a set of node IDs."""
        from neo4j import Query

        unique_node_ids = list(dict.fromkeys(node_ids))
        if not unique_node_ids:
            return {}

        hops = max(1, int(expansion_hops))
        start_filter = "WHERE start.user_id = $user_id" if user_id else ""
        related_filters = ["related <> start"]
        if user_id:
            related_filters.append("related.user_id = $user_id")
            related_filters.append(
                "all(path_node IN nodes(path) WHERE path_node.user_id = $user_id)"
            )

        cypher = f"""
            UNWIND $node_ids AS node_id
            MATCH (start {{id: node_id}})
            {start_filter}
            MATCH path = (start)-[*1..{hops}]-(related)
            WHERE {' AND '.join(related_filters)}
            WITH node_id, related, min(length(path)) AS distance
            ORDER BY node_id, distance, related.id
            WITH node_id,
                 collect({{node: related, distance: distance}})[0..$max_nodes] AS expansions,
                 count(related) AS total_related
            RETURN node_id, expansions, total_related
        """

        params = {"node_ids": unique_node_ids, "max_nodes": max_nodes}
        if user_id:
            params["user_id"] = user_id

        try:
            with self.graph_service.get_session() as session:
                q = Query(cypher, timeout=timeout_s) if timeout_s else cypher
                result = session.run(q, **params)
                expansions_by_node: dict[str, dict] = {}
                for record in result:
                    related_nodes: list[dict] = []
                    nodes_per_distance: dict[int, int] = {}

                    for item in record["expansions"]:
                        distance = item["distance"]
                        if nodes_per_distance.get(distance, 0) >= 5:
                            continue
                        nodes_per_distance[distance] = nodes_per_distance.get(distance, 0) + 1
                        related_nodes.append(
                            {
                                "node": dict(item["node"]),
                                "distance": distance,
                            }
                        )

                    expansions_by_node[record["node_id"]] = {
                        "total_related": record["total_related"],
                        "related_nodes": related_nodes,
                    }

                return expansions_by_node
        except Exception as e:
            logger.warning("Batch graph expansion failed: %s", e)
            return None

    # Maximum CONTAINS hops between any node and its Video ancestor.
    # Schema: Video -> Chapter -> Scene -> Frame -> Entity (~4 hops).
    # Bound at 6 for headroom; rare deeper structures are accepted as
    # missing-path (graceful degradation), never an unbounded scan.
    _PATH_LOOKUP_MAX_HOPS = 6

    # Chunk size for batched path lookups: keeps each Neo4j transaction
    # well under the configured timeout and isolates failures so a single
    # bad chunk cannot poison the rest of the batch.
    _PATH_LOOKUP_CHUNK_SIZE = 25

    def _batch_get_paths_to_video(
        self,
        node_ids: list[str],
        user_id: str | None = None,
        timeout_s: float | None = None,
    ) -> dict[str, list[str]] | None:
        """Batch fetch the shortest path from each node up to a Video node.

        Uses a bounded ``shortestPath`` (``[:CONTAINS*0..6]``) so Neo4j can
        short-circuit instead of enumerating every path before sorting.
        Candidate ids are processed in fixed-size chunks; per-chunk errors
        are isolated so a single timeout does not discard prior results.
        """
        from neo4j import Query

        unique_node_ids = list(dict.fromkeys(node_ids))
        if not unique_node_ids:
            return {}

        node_filter = "WHERE n.user_id = $user_id" if user_id else ""
        # `*0..6` allows the path when ``n`` is itself a ``Video`` (preserves
        # behavior of the previous unbounded ``[:CONTAINS*]`` match).
        if user_id:
            cypher = f"""
                UNWIND $node_ids AS node_id
                MATCH (n {{id: node_id}})
                {node_filter}
                MATCH p = shortestPath(
                    (n)<-[:CONTAINS*0..{self._PATH_LOOKUP_MAX_HOPS}]-(v:Video {{user_id: $user_id}})
                )
                WHERE all(x IN nodes(p) WHERE x.user_id = $user_id)
                RETURN node_id, [x IN nodes(p) | x.id] AS path
            """
        else:
            cypher = f"""
                UNWIND $node_ids AS node_id
                MATCH (n {{id: node_id}})
                MATCH p = shortestPath(
                    (n)<-[:CONTAINS*0..{self._PATH_LOOKUP_MAX_HOPS}]-(v:Video)
                )
                RETURN node_id, [x IN nodes(p) | x.id] AS path
            """

        chunk_size = max(1, self._PATH_LOOKUP_CHUNK_SIZE)
        chunks = [
            unique_node_ids[i : i + chunk_size]
            for i in range(0, len(unique_node_ids), chunk_size)
        ]

        paths_by_node: dict[str, list[str]] = {}
        failed_chunks = 0

        for chunk in chunks:
            params: dict[str, object] = {"node_ids": chunk}
            if user_id:
                params["user_id"] = user_id

            try:
                with self.graph_service.get_session() as session:
                    q = Query(cypher, timeout=timeout_s) if timeout_s else cypher
                    result = session.run(q, **params)
                    for record in result:
                        paths_by_node[record["node_id"]] = record["path"]
            except Exception as e:
                failed_chunks += 1
                logger.warning(
                    "Batch path lookup chunk failed (size=%d): %s — %s",
                    len(chunk),
                    type(e).__name__,
                    str(e),
                )
                logger.debug("Batch path lookup chunk traceback", exc_info=True)
                continue

        # Preserve the legacy contract: return ``None`` when *every* chunk
        # failed so the caller can short-circuit graph scoring entirely.
        if failed_chunks and not paths_by_node:
            return None
        return paths_by_node

    def _count_by_type(self, results: list[ScoredNode]) -> dict[str, int]:
        """Count results by node type."""
        counts = {}
        for r in results:
            type_name = r.node_type.value
            counts[type_name] = counts.get(type_name, 0) + 1
        return counts

    def _count_by_video(self, results: list[ScoredNode]) -> dict[str, int]:
        """Count results by video."""
        counts = {}
        for r in results:
            if r.video_id:
                counts[r.video_id] = counts.get(r.video_id, 0) + 1
        return counts
