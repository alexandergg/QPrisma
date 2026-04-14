"""
Graph-Enhanced Search Service for QPrisma

Implements hybrid search combining:
- Vector search (embeddings)
- Graph traversal (relations)
- Full-text search
- Temporal awareness
- Re-ranking with expanded context

Inspired by VideoRAG for intelligent multimedia content retrieval.
"""

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime

from models.graph_models import (
    GraphSearchResponse,
    GraphSearchResult,
    NodeType,
)
from services.embedding_service import EmbeddingService, get_embedding_service
from services.graph_search_queries import GraphSearchQueryMixin, ScoredNode  # noqa: F401
from services.graph_search_scoring import GraphSearchScoringMixin
from services.knowledge_graph import KnowledgeGraphService, get_knowledge_graph_service

logger = logging.getLogger(__name__)


class GraphSearchService(GraphSearchQueryMixin, GraphSearchScoringMixin):
    """
    Hybrid search service for the Knowledge Graph.

    Combines multiple relevance signals:
    1. **Vector similarity**: Semantic similarity via embeddings
    2. **Graph proximity**: Closeness in the graph (hops)
    3. **Full-text match**: Term matching
    4. **Temporal relevance**: Temporal closeness within the video
    5. **Co-occurrence**: Entities that appear together

    The final score combines these signals with configurable weights.
    """

    # Default weights for hybrid scoring
    DEFAULT_WEIGHTS = {
        "vector": 0.35,
        "fulltext": 0.25,
        "graph": 0.25,
        "temporal": 0.15,
    }

    # Intent-adaptive weight profiles (override defaults per query intent)
    INTENT_WEIGHT_PROFILES: dict[str, dict[str, float]] = {
        "time-based": {"vector": 0.25, "fulltext": 0.15, "graph": 0.20, "temporal": 0.40},
        "object": {"vector": 0.30, "fulltext": 0.20, "graph": 0.35, "temporal": 0.15},
        "person": {"vector": 0.30, "fulltext": 0.20, "graph": 0.35, "temporal": 0.15},
        "text": {"vector": 0.25, "fulltext": 0.40, "graph": 0.20, "temporal": 0.15},
        "action": {"vector": 0.40, "fulltext": 0.20, "graph": 0.20, "temporal": 0.20},
        "scene": {"vector": 0.40, "fulltext": 0.20, "graph": 0.20, "temporal": 0.20},
        "event": {"vector": 0.35, "fulltext": 0.20, "graph": 0.20, "temporal": 0.25},
    }

    # Embedding dimensions (text-embedding-3-large)
    EMBEDDING_DIM = 3072

    def __init__(
        self,
        graph_service: KnowledgeGraphService | None = None,
        embedding_service: EmbeddingService | None = None,
        weights: dict | None = None,
    ) -> None:
        """
        Initialize the search service.

        Args:
            graph_service: Knowledge Graph service
            embedding_service: Embeddings service
            weights: Custom weights for scoring
        """
        self.graph_service = graph_service or get_knowledge_graph_service()
        self.embedding_service = embedding_service or get_embedding_service()
        self.weights = weights or self.DEFAULT_WEIGHTS

        # Ensure weights sum to 1
        total = sum(self.weights.values())
        if total != 1.0:
            self.weights = {k: v / total for k, v in self.weights.items()}

    def get_weights_for_intent(self, intent: str | None) -> dict[str, float]:
        """Return fusion weights adapted to the query intent.

        Falls back to the instance default weights for unknown or None intents.
        """
        if intent and intent in self.INTENT_WEIGHT_PROFILES:
            weights = self.INTENT_WEIGHT_PROFILES[intent].copy()
            total = sum(weights.values())
            if total != 1.0:
                weights = {k: v / total for k, v in weights.items()}
            return weights
        return self.weights

    @staticmethod
    def _build_search_cache_key(
        query_text: str,
        node_types: list[NodeType],
        video_id: str | None,
        video_ids: list[str] | None,
        user_id: str | None,
        time_range: tuple[float, float] | None,
        limit: int,
        expansion_hops: int,
        use_reranking: bool,
        query_intent: str | None,
    ) -> str:
        """Build a deterministic cache key from all result-affecting params."""
        parts = {
            "q": query_text,
            "nt": sorted(t.value for t in node_types),
            "vid": video_id or "",
            "vids": sorted(video_ids) if video_ids else [],
            "uid": user_id or "",
            "tr": list(time_range) if time_range else None,
            "lim": limit,
            "eh": expansion_hops,
            "rr": use_reranking,
            "qi": query_intent or "",
        }
        raw = json.dumps(parts, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    # =========================================================================
    # Vector Index Management
    # =========================================================================

    def initialize_vector_indexes(self) -> None:
        """
        Create vector indexes in Neo4j for similarity search.

        Creates both full (3072d) and coarse (512d) Matryoshka indexes
        for two-pass search: fast filtering then precise ranking.
        Requires Neo4j 5.11+ with vector index support.
        """
        from core.config import get_settings

        search_cfg = get_settings().search

        index_configs = [
            # Full precision indexes (3072d)
            ("frame_embedding", "Frame", "embedding", 3072),
            ("entity_embedding", "Entity", "embedding", 3072),
            ("scene_embedding", "Scene", "embedding", 3072),
            ("audiosegment_embedding", "AudioSegment", "embedding", 3072),
            # Community indexes
            ("community_embedding", "Community", "embedding", 3072),
            ("community_embedding_coarse", "Community", "embedding_coarse", 512),
            # Coarse Matryoshka indexes (512d) for fast initial filtering
            ("frame_embedding_coarse", "Frame", "embedding_coarse", 512),
            ("entity_embedding_coarse", "Entity", "embedding_coarse", 512),
            ("scene_embedding_coarse", "Scene", "embedding_coarse", 512),
            ("audiosegment_embedding_coarse", "AudioSegment", "embedding_coarse", 512),
        ]

        with self.graph_service.get_session() as session:
            for index_name, label, prop, dims in index_configs:
                try:
                    session.run(
                        f"""
                        CREATE VECTOR INDEX {index_name} IF NOT EXISTS
                        FOR (n:{label})
                        ON n.{prop}
                        OPTIONS {{
                            indexConfig: {{
                                `vector.dimensions`: {dims},
                                `vector.similarity_function`: 'cosine',
                                `vector.hnsw.m`: {search_cfg.hnsw_m},
                                `vector.hnsw.ef_construction`: {search_cfg.hnsw_ef_construction}
                            }}
                        }}
                        """
                    )
                    logger.info(
                        f"Created vector index {index_name} ({dims}d, M={search_cfg.hnsw_m}, ef={search_cfg.hnsw_ef_construction})"
                    )
                except Exception as e:
                    logger.debug(f"Vector index {index_name} may already exist: {e}")

    def store_embedding(
        self,
        node_id: str,
        embedding: list[float],
        node_type: NodeType | None = None,
    ) -> None:
        """
        Store both full and coarse (Matryoshka) embeddings on a node.

        Args:
            node_id: Node ID
            embedding: Embedding vector (3072 dims)
            node_type: Node type (for more efficient queries)
        """
        coarse = embedding[:512] if len(embedding) >= 512 else embedding

        if node_type:
            label = node_type.value
            query = f"""
                MATCH (n:{label} {{id: $node_id}})
                SET n.embedding = $embedding,
                    n.embedding_coarse = $coarse,
                    n.embedding_updated_at = datetime()
                RETURN n.id
            """
        else:
            query = """
                MATCH (n {id: $node_id})
                SET n.embedding = $embedding,
                    n.embedding_coarse = $coarse,
                    n.embedding_updated_at = datetime()
                RETURN n.id
            """

        with self.graph_service.get_session() as session:
            session.run(query, node_id=node_id, embedding=embedding, coarse=coarse)

    async def generate_and_store_embedding(
        self,
        node_id: str,
        text: str,
        node_type: NodeType | None = None,
    ) -> list[float]:
        """
        Generate an embedding for the given text and store it on the node.

        Args:
            node_id: Node ID
            text: Text to embed
            node_type: Node type

        Returns:
            The generated embedding
        """
        embedding = await self.embedding_service.generate_embedding(text)
        await asyncio.to_thread(self.store_embedding, node_id, embedding, node_type)
        return embedding

    async def bulk_generate_embeddings(
        self,
        node_type: NodeType,
        text_field: str = "description",
        batch_size: int = 50,
        video_id: str | None = None,
    ) -> int:
        """
        Generate embeddings in bulk for all nodes of a given type.

        Args:
            node_type: Node type (Frame, Entity, Scene)
            text_field: Text field to embed
            batch_size: Batch size
            video_id: Filter by video (optional)

        Returns:
            Number of embeddings generated
        """
        label = node_type.value

        # Query to fetch nodes without an embedding
        if video_id:
            query = f"""
                MATCH (n:{label})
                WHERE n.video_id = $video_id AND n.embedding IS NULL AND n.{text_field} IS NOT NULL
                RETURN n.id as id, n.{text_field} as text
                LIMIT $batch_size
            """
            params = {"video_id": video_id, "batch_size": batch_size}
        else:
            query = f"""
                MATCH (n:{label})
                WHERE n.embedding IS NULL AND n.{text_field} IS NOT NULL
                RETURN n.id as id, n.{text_field} as text
                LIMIT $batch_size
            """
            params = {"batch_size": batch_size}

        total_processed = 0

        while True:

            def _fetch_batch():
                with self.graph_service.get_session() as session:
                    result = session.run(query, **params)
                    return [(r["id"], r["text"]) for r in result]

            nodes = await asyncio.to_thread(_fetch_batch)

            if not nodes:
                break

            # Generar embeddings en batch
            texts = [text for _, text in nodes]
            embeddings = await self.embedding_service.generate_embeddings_batch(texts)

            # Almacenar embeddings
            for (node_id, _), embedding in zip(nodes, embeddings):
                await asyncio.to_thread(self.store_embedding, node_id, embedding, node_type)

            total_processed += len(nodes)
            logger.info(f"Generated {total_processed} embeddings for {label}")

        return total_processed

    # =========================================================================
    # Hybrid Search
    # =========================================================================

    async def hybrid_search(
        self,
        query_text: str,
        node_types: list[NodeType] | None = None,
        video_id: str | None = None,
        video_ids: list[str] | None = None,
        user_id: str | None = None,
        time_range: tuple[float, float] | None = None,
        limit: int = 20,
        expansion_hops: int = 2,
        use_reranking: bool = True,
        query_intent: str | None = None,
    ) -> GraphSearchResponse:
        """
        Hybrid search combining vector, full-text, and graph signals.

        Args:
            query_text: Search text
            node_types: Node types to search (default: Frame, Entity)
            video_id: Filter by a single video
            video_ids: Filter by multiple videos (IN clause)
            time_range: Temporal range (start, end) in seconds
            limit: Maximum number of results
            expansion_hops: Hops for context expansion
            use_reranking: Whether to apply context-based re-ranking
            query_intent: Query intent from query understanding (e.g. 'time-based', 'object')
                          used to adapt fusion weights

        Returns:
            GraphSearchResponse with sorted results
        """
        start_time = datetime.now(UTC)

        # Resolve video_id vs video_ids
        effective_video_id = video_id
        effective_video_ids = video_ids
        if video_ids and len(video_ids) == 1:
            effective_video_id = video_ids[0]
            effective_video_ids = None

        if node_types is None:
            node_types = [
                NodeType.FRAME,
                NodeType.ENTITY,
                NodeType.AUDIO_SEGMENT,
                NodeType.COMMUNITY,
            ]

        logger.info(
            "hybrid_search: START | query_len=%d node_type_count=%d "
            "has_video_id=%s limit=%d expansion_hops=%d reranking=%s",
            len(query_text),
            len(node_types),
            bool(effective_video_id or effective_video_ids),
            int(limit),
            int(expansion_hops),
            bool(use_reranking),
        )

        # --- Cache lookup (before embedding to save OpenAI API cost) ---
        cache_key = self._build_search_cache_key(
            query_text=query_text,
            node_types=node_types,
            video_id=effective_video_id,
            video_ids=effective_video_ids,
            user_id=user_id,
            time_range=time_range,
            limit=limit,
            expansion_hops=expansion_hops,
            use_reranking=use_reranking,
            query_intent=query_intent,
        )
        cache = None
        try:
            from services.cache_service import get_cache_service

            cache = await get_cache_service()
            cached = await cache.get_search_result(cache_key)
            if cached:
                logger.info("hybrid_search: cache HIT | key=%s", cache_key[:12])
                return GraphSearchResponse(**cached)
        except Exception:
            logger.debug("hybrid_search: cache unavailable, skipping", exc_info=True)
            cache = None

        logger.info("hybrid_search: cache MISS | proceeding to embedding")

        # 1. Generate query embedding
        embedding_start = datetime.now(UTC)
        query_embedding = await self.embedding_service.generate_embedding(query_text)
        embedding_time = (datetime.now(UTC) - embedding_start).total_seconds() * 1000
        logger.info("hybrid_search: embedding done | %.0f ms", embedding_time)

        # 2-7. Sync search pipeline — run in thread pool to avoid blocking event loop.
        # All Neo4j calls (vector_search, _fulltext_search, _calculate_graph_scores, etc.)
        # are sync and would block the event loop if called directly from this async method.
        _PIPELINE_BUDGET_S = 25.0  # total time budget for the sync pipeline

        def _sync_search_pipeline() -> tuple:
            _pipeline_start = datetime.now(UTC)
            _all: list[ScoredNode] = []
            _v_start = datetime.now(UTC)
            _ft_acc = 0.0

            def _elapsed_s() -> float:
                return (datetime.now(UTC) - _pipeline_start).total_seconds()

            def _remaining_s() -> float:
                return max(1.0, _PIPELINE_BUDGET_S - _elapsed_s())

            for nt in node_types:
                if _elapsed_s() > _PIPELINE_BUDGET_S - 2.0:
                    logger.warning(
                        "pipeline: budget nearly exhausted, skipping remaining node types "
                        "| elapsed_s=%.1f candidates=%d",
                        _elapsed_s(),
                        len(_all),
                    )
                    break

                _nt_start = datetime.now(UTC)
                _all.extend(
                    self.vector_search(
                        query_embedding=query_embedding,
                        node_type=nt,
                        limit=limit * 2,
                        video_id=effective_video_id,
                        video_ids=effective_video_ids,
                        user_id=user_id,
                        min_score=0.3,
                        timeout_s=_remaining_s(),
                    )
                )
                _nt_vec_ms = (datetime.now(UTC) - _nt_start).total_seconds() * 1000
                logger.info(
                    "pipeline: vector done | node_type=%s candidates=%d ms=%.0f",
                    nt.value,
                    len(_all),
                    _nt_vec_ms,
                )

                _ft_start = datetime.now(UTC)
                ft_results = self._fulltext_search(
                    query_text=query_text,
                    node_type=nt,
                    limit=limit,
                    video_id=effective_video_id,
                    video_ids=effective_video_ids,
                    user_id=user_id,
                    timeout_s=_remaining_s(),
                )
                _ft_ms = (datetime.now(UTC) - _ft_start).total_seconds() * 1000
                _ft_acc += _ft_ms
                logger.info(
                    "pipeline: fulltext done | node_type=%s ft_results=%d ms=%.0f",
                    nt.value,
                    len(ft_results),
                    _ft_ms,
                )

                self._merge_fulltext_scores(
                    _all,
                    ft_results,
                    nt,
                    video_id=effective_video_id,
                    video_ids=effective_video_ids,
                    user_id=user_id,
                    timeout_s=_remaining_s(),
                )

            _v_time = (datetime.now(UTC) - _v_start).total_seconds() * 1000 - _ft_acc
            logger.info(
                "pipeline: retrieval complete | total_candidates=%d "
                "vector_ms=%.0f fulltext_ms=%.0f elapsed_s=%.1f",
                len(_all),
                _v_time,
                _ft_acc,
                _elapsed_s(),
            )

            # --- candidate cap (after all node types merged) ---
            _cap = int(limit) * 6
            if len(_all) > _cap:
                _pre_cap_count = len(_all)
                # Use provisional blended score to preserve strong fulltext-only hits
                for c in _all:
                    c.combined_score = 0.5 * c.vector_score + 0.5 * c.fulltext_score
                _all.sort(key=lambda x: x.combined_score, reverse=True)
                _all = _all[: int(limit) * 4]
                logger.info(
                    "pipeline: capped candidates | from=%d to=%d",
                    _pre_cap_count,
                    len(_all),
                )
                # Reset combined_score for proper weighted calculation below
                for c in _all:
                    c.combined_score = 0.0

            if time_range:
                _all = self._filter_by_time_range(_all, time_range)

            # --- graph scoring (skip if budget nearly exhausted) ---
            _g_start = datetime.now(UTC)
            if _elapsed_s() > _PIPELINE_BUDGET_S - 3.0:
                logger.warning(
                    "pipeline: skipping graph expansion (budget) | " "elapsed_s=%.1f candidates=%d",
                    _elapsed_s(),
                    len(_all),
                )
                for c in _all:
                    c.graph_score = 0.0
                    c.related_nodes = []
                    c.path_to_video = []
                _g_time = 0.0
            else:
                self._calculate_graph_scores(
                    _all, expansion_hops, user_id=user_id, timeout_s=_remaining_s()
                )
                _g_time = (datetime.now(UTC) - _g_start).total_seconds() * 1000
            logger.info(
                "pipeline: graph scoring done | candidates=%d ms=%.0f",
                len(_all),
                _g_time,
            )

            _t_start = datetime.now(UTC)
            self._calculate_temporal_scores(_all, time_range)
            _t_time = (datetime.now(UTC) - _t_start).total_seconds() * 1000

            weights = self.get_weights_for_intent(query_intent)
            for c in _all:
                c.combined_score = (
                    weights["vector"] * c.vector_score
                    + weights["fulltext"] * c.fulltext_score
                    + weights["graph"] * c.graph_score
                    + weights["temporal"] * c.temporal_score
                )

            _r_start = datetime.now(UTC)
            if use_reranking and _all:
                _all = self._rerank_with_context(_all, query_text, query_embedding)
            _r_time = (datetime.now(UTC) - _r_start).total_seconds() * 1000

            _all.sort(key=lambda x: x.combined_score, reverse=True)
            logger.info(
                "pipeline: COMPLETE | results=%d total_elapsed_s=%.1f",
                min(len(_all), int(limit)),
                _elapsed_s(),
            )
            return _all[:limit], _v_time, _ft_acc, _g_time, _t_time, _r_time

        (
            final_results,
            vector_search_time,
            fulltext_time_acc,
            graph_time,
            temporal_time,
            reranking_time,
        ) = await asyncio.to_thread(_sync_search_pipeline)

        logger.info(
            "hybrid_search: pipeline done | results=%d "
            "vector_ms=%.0f fulltext_ms=%.0f graph_ms=%.0f "
            "temporal_ms=%.0f reranking_ms=%.0f",
            len(final_results),
            vector_search_time,
            fulltext_time_acc,
            graph_time,
            temporal_time,
            reranking_time,
        )

        # 8. Build response
        total_time = (datetime.now(UTC) - start_time).total_seconds() * 1000

        search_results = [
            GraphSearchResult(
                node_id=r.node_id,
                node_type=r.node_type,
                vector_score=r.vector_score,
                graph_score=r.graph_score,
                combined_score=r.combined_score,
                content=r.content,
                related_nodes=r.related_nodes,
                path_to_root=r.path_to_video,
            )
            for r in final_results
        ]

        response = GraphSearchResponse(
            query=query_text,
            total_results=len(search_results),
            results=search_results,
            search_time_ms=total_time,
            embedding_time_ms=embedding_time,
            vector_search_time_ms=vector_search_time,
            fulltext_search_time_ms=fulltext_time_acc,
            graph_expansion_time_ms=graph_time,
            temporal_scoring_time_ms=temporal_time,
            reranking_time_ms=reranking_time,
            facets={
                "node_types": self._count_by_type(final_results),
                "videos": self._count_by_video(final_results),
            },
        )

        logger.info(
            "hybrid_search: DONE | total_results=%d total_ms=%.0f",
            len(search_results),
            total_time,
        )

        # --- Cache store (awaited so the result is persisted before return) ---
        if cache is not None:
            try:
                await cache.set_search_result(cache_key, response.model_dump(mode="json"))
            except Exception:
                logger.debug("Failed to cache search result", exc_info=True)

        return response

    # =========================================================================
    # Cross-Video Search
    # =========================================================================

    async def find_similar_across_videos(
        self,
        reference_node_id: str,
        limit: int = 10,
        min_similarity: float = 0.7,
        allowed_video_ids: list[str] | None = None,
        user_id: str | None = None,
    ) -> list[ScoredNode]:
        """
        Find similar nodes across other videos.

        Args:
            reference_node_id: Reference node ID
            limit: Maximum number of results
            min_similarity: Minimum similarity threshold
            allowed_video_ids: Optional explicit video scope for callers that need it
            user_id: Optional tenant scope applied directly in Neo4j

        Returns:
            List of similar nodes from other videos
        """
        # Retrieve the embedding of the reference node
        query = """
            MATCH (n {id: $node_id})
            RETURN n.embedding as embedding, n.video_id as video_id, labels(n)[0] as label
        """

        def _fetch_ref():
            with self.graph_service.get_session() as session:
                result = session.run(query, node_id=reference_node_id)
                record = result.single()
                if not record or not record["embedding"]:
                    return None
                return {
                    "embedding": record["embedding"],
                    "video_id": record["video_id"],
                    "label": record["label"],
                }

        ref = await asyncio.to_thread(_fetch_ref)

        if ref is None:
            return []

        ref_embedding = ref["embedding"]
        ref_video_id = ref["video_id"]
        ref_label = ref["label"]

        # Search for similar nodes excluding the reference video
        try:
            node_type = NodeType(ref_label)
        except ValueError:
            return []

        # Vector search excluding the current video
        tenant_scope = "AND node.user_id = $user_id" if user_id else ""
        allowed_scope = (
            "AND node.video_id IN $allowed_video_ids" if allowed_video_ids is not None else ""
        )
        search_query = f"""
            CALL db.index.vector.queryNodes($index_name, $limit * 2, $embedding)
            YIELD node, score
            WHERE node.video_id <> $exclude_video AND score >= $min_score
            {tenant_scope}
            {allowed_scope}
            RETURN node, score
            ORDER BY score DESC
            LIMIT $limit
        """

        results = []
        index_name = f"{ref_label.lower()}_embedding"

        try:
            params = {
                "index_name": index_name,
                "embedding": ref_embedding,
                "exclude_video": ref_video_id,
                "limit": limit,
                "min_score": min_similarity,
            }
            if user_id:
                params["user_id"] = user_id
            if allowed_video_ids is not None:
                params["allowed_video_ids"] = allowed_video_ids

            def _run_cross_search():
                _results = []
                with self.graph_service.get_session() as session:
                    result = session.run(search_query, **params)

                    for record in result:
                        node_data = dict(record["node"])
                        node_data.pop("embedding", None)
                        node_data.pop("embedding_coarse", None)

                        scored = ScoredNode(
                            node_id=node_data.get("id"),
                            node_type=node_type,
                            content=node_data,
                            vector_score=record["score"],
                            timestamp=node_data.get("timestamp") or node_data.get("start_time"),
                            video_id=node_data.get("video_id"),
                        )
                        _results.append(scored)
                return _results

            results = await asyncio.to_thread(_run_cross_search)

        except Exception as e:
            logger.warning(f"Cross-video search failed: {e}")

        return results


# =============================================================================
# Singleton
# =============================================================================

_graph_search_service: GraphSearchService | None = None


def get_graph_search_service() -> GraphSearchService:
    """Return the singleton instance of GraphSearchService."""
    global _graph_search_service
    if _graph_search_service is None:
        _graph_search_service = GraphSearchService()
        try:
            _graph_search_service.initialize_vector_indexes()
        except Exception as e:
            logger.warning(f"Vector index initialization failed: {e}")
    return _graph_search_service
