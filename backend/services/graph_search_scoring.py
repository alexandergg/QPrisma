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
    ) -> None:
        """
        Calculate graph scores based on connectivity and expansion.

        More connected nodes that are closer to the centre of the graph receive higher scores.
        """
        if not candidates:
            return

        for candidate in candidates:
            try:
                # Expand context
                expansion = self.graph_service.expand_context(
                    node_id=candidate.node_id,
                    hops=expansion_hops,
                    max_nodes=30,
                )

                # Graph score based on number of connections
                total_related = expansion.get("total_nodes", 0)
                candidate.graph_score = min(1.0, total_related / 50)  # Normalise to 50

                # Store related nodes
                nodes_by_distance = expansion.get("nodes_by_distance", {})
                for distance, nodes in nodes_by_distance.items():
                    for node in nodes[:5]:  # Limit per distance
                        candidate.related_nodes.append(
                            {
                                "node": node,
                                "distance": distance,
                            }
                        )

                # Calculate path to video
                candidate.path_to_video = self._get_path_to_video(candidate.node_id)

            except Exception as e:
                logger.debug(f"Graph expansion failed for {candidate.node_id}: {e}")
                candidate.graph_score = 0.0

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

    def _get_path_to_video(self, node_id: str) -> list[str]:
        """Return the path from a node up to the root Video node."""
        query = """
            MATCH path = (n {id: $node_id})<-[:CONTAINS*]-(v:Video)
            RETURN [node in nodes(path) | node.id] as path
            LIMIT 1
        """

        try:
            with self.graph_service.get_session() as session:
                result = session.run(query, node_id=node_id)
                record = result.single()
                if record:
                    return record["path"]
        except (KeyError, AttributeError) as e:
            logger.warning(f"Could not retrieve path for node {node_id}: {e}")

        return []

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
