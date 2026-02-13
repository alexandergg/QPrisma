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

import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime

from models.graph_models import (
    GraphSearchResponse,
    GraphSearchResult,
    NodeType,
)
from services.embedding_service import EmbeddingService, get_embedding_service
from services.knowledge_graph import KnowledgeGraphService, get_knowledge_graph_service

logger = logging.getLogger(__name__)


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


class GraphSearchService:
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

    # Embedding dimensions (text-embedding-3-large)
    EMBEDDING_DIM = 3072

    def __init__(
        self,
        graph_service: KnowledgeGraphService | None = None,
        embedding_service: EmbeddingService | None = None,
        weights: dict | None = None,
    ):
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

    # =========================================================================
    # Vector Index Management
    # =========================================================================

    def initialize_vector_indexes(self):
        """
        Create vector indexes in Neo4j for similarity search.

        Creates both full (3072d) and coarse (512d) Matryoshka indexes
        for two-pass search: fast filtering then precise ranking.
        Requires Neo4j 5.11+ with vector index support.
        """
        index_configs = [
            # Full precision indexes (3072d)
            ("frame_embedding", "Frame", "embedding", 3072),
            ("entity_embedding", "Entity", "embedding", 3072),
            ("scene_embedding", "Scene", "embedding", 3072),
            ("audiosegment_embedding", "AudioSegment", "embedding", 3072),
            # Coarse Matryoshka indexes (512d) for fast initial filtering
            ("frame_embedding_coarse", "Frame", "embedding_coarse", 512),
            ("entity_embedding_coarse", "Entity", "embedding_coarse", 512),
            ("scene_embedding_coarse", "Scene", "embedding_coarse", 512),
            ("audiosegment_embedding_coarse", "AudioSegment", "embedding_coarse", 512),
        ]

        with self.graph_service.get_session() as session:
            for index_name, label, prop, dims in index_configs:
                try:
                    session.run(f"""
                        CREATE VECTOR INDEX {index_name} IF NOT EXISTS
                        FOR (n:{label})
                        ON n.{prop}
                        OPTIONS {{
                            indexConfig: {{
                                `vector.dimensions`: {dims},
                                `vector.similarity_function`: 'cosine'
                            }}
                        }}
                        """)
                    logger.info(f"Created vector index {index_name} ({dims}d)")
                except Exception as e:
                    logger.debug(f"Vector index {index_name} may already exist: {e}")

    def store_embedding(
        self,
        node_id: str,
        embedding: list[float],
        node_type: NodeType | None = None,
    ):
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
        self.store_embedding(node_id, embedding, node_type)
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
            with self.graph_service.get_session() as session:
                result = session.run(query, **params)
                nodes = [(r["id"], r["text"]) for r in result]

            if not nodes:
                break

            # Generar embeddings en batch
            texts = [text for _, text in nodes]
            embeddings = await self.embedding_service.generate_embeddings_batch(texts)

            # Almacenar embeddings
            for (node_id, _), embedding in zip(nodes, embeddings):
                self.store_embedding(node_id, embedding, node_type)

            total_processed += len(nodes)
            logger.info(f"Generated {total_processed} embeddings for {label}")

        return total_processed

    # =========================================================================
    # Vector Search
    # =========================================================================

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
            logger.debug(f"Vector query on {index_name} failed: {e}")

        return results

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

    # =========================================================================
    # Hybrid Search
    # =========================================================================

    async def hybrid_search(
        self,
        query_text: str,
        node_types: list[NodeType] | None = None,
        video_id: str | None = None,
        video_ids: list[str] | None = None,
        time_range: tuple[float, float] | None = None,
        limit: int = 20,
        expansion_hops: int = 2,
        use_reranking: bool = True,
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
            node_types = [NodeType.FRAME, NodeType.ENTITY, NodeType.AUDIO_SEGMENT]

        # 1. Generate query embedding
        query_embedding = await self.embedding_service.generate_embedding(query_text)
        (datetime.now(UTC) - start_time).total_seconds() * 1000

        # 2. Search each node type
        all_candidates: list[ScoredNode] = []

        vector_start = datetime.now(UTC)
        for node_type in node_types:
            # Vector search
            vector_results = self.vector_search(
                query_embedding=query_embedding,
                node_type=node_type,
                limit=limit * 2,
                video_id=effective_video_id,
                video_ids=effective_video_ids,
                min_score=0.3,
            )
            all_candidates.extend(vector_results)

            # Full-text search
            fulltext_results = self._fulltext_search(
                query_text=query_text,
                node_type=node_type,
                limit=limit,
                video_id=effective_video_id,
                video_ids=effective_video_ids,
            )

            # Merge full-text scores
            vid = effective_video_id or (effective_video_ids[0] if effective_video_ids else None)
            self._merge_fulltext_scores(all_candidates, fulltext_results, node_type, vid)

        vector_search_time = (datetime.now(UTC) - vector_start).total_seconds() * 1000

        # 3. Apply temporal filter if specified
        if time_range:
            all_candidates = self._filter_by_time_range(all_candidates, time_range)

        # 4. Calculate graph scores
        graph_start = datetime.now(UTC)
        self._calculate_graph_scores(all_candidates, expansion_hops)
        graph_time = (datetime.now(UTC) - graph_start).total_seconds() * 1000

        # 5. Calculate temporal scores
        self._calculate_temporal_scores(all_candidates, time_range)

        # 6. Calculate combined score
        for candidate in all_candidates:
            candidate.combined_score = (
                self.weights["vector"] * candidate.vector_score
                + self.weights["fulltext"] * candidate.fulltext_score
                + self.weights["graph"] * candidate.graph_score
                + self.weights["temporal"] * candidate.temporal_score
            )

        # 7. Re-ranking with expanded context
        if use_reranking and all_candidates:
            all_candidates = self._rerank_with_context(all_candidates, query_text, query_embedding)

        # 8. Ordenar y limitar
        all_candidates.sort(key=lambda x: x.combined_score, reverse=True)
        final_results = all_candidates[:limit]

        # 9. Construir respuesta
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

        return GraphSearchResponse(
            query=query_text,
            total_results=len(search_results),
            results=search_results,
            search_time_ms=total_time,
            vector_search_time_ms=vector_search_time,
            graph_expansion_time_ms=graph_time,
            facets={
                "node_types": self._count_by_type(final_results),
                "videos": self._count_by_video(final_results),
            },
        )

    def _fulltext_search(
        self,
        query_text: str,
        node_type: NodeType,
        limit: int,
        video_id: str | None,
        video_ids: list[str] | None = None,
    ) -> list[tuple[str, float]]:
        """Full-text search; returns [(node_id, score)]."""
        label = node_type.value

        if node_type == NodeType.FRAME:
            index_name = "frame_search"
        elif node_type == NodeType.ENTITY:
            index_name = "entity_search"
        elif node_type == NodeType.AUDIO_SEGMENT:
            index_name = "audio_search"
        else:
            return []

        try:
            if video_ids:
                query = f"""
                    CALL db.index.fulltext.queryNodes(
                        $index_name, $query_text
                    )
                    YIELD node, score
                    WHERE node:{label}
                        AND node.video_id IN $video_ids
                    RETURN node.id as id, score
                    LIMIT $limit
                """
                params: dict = {
                    "index_name": index_name,
                    "query_text": query_text,
                    "video_ids": video_ids,
                    "limit": limit,
                }
            elif video_id:
                query = f"""
                    CALL db.index.fulltext.queryNodes($index_name, $query_text)
                    YIELD node, score
                    WHERE node:{label} AND node.video_id = $video_id
                    RETURN node.id as id, score
                    LIMIT $limit
                """
                params = {
                    "index_name": index_name,
                    "query_text": query_text,
                    "video_id": video_id,
                    "limit": limit,
                }
            else:
                query = f"""
                    CALL db.index.fulltext.queryNodes($index_name, $query_text)
                    YIELD node, score
                    WHERE node:{label}
                    RETURN node.id as id, score
                    LIMIT $limit
                """
                params = {
                    "index_name": index_name,
                    "query_text": query_text,
                    "limit": limit,
                }

            with self.graph_service.get_session() as session:
                result = session.run(query, **params)
                return [(r["id"], r["score"]) for r in result]

        except Exception as e:
            logger.debug(f"Full-text search failed: {e}")
            return []

    def _merge_fulltext_scores(
        self,
        candidates: list[ScoredNode],
        fulltext_results: list[tuple[str, float]],
        node_type: NodeType,
        video_id: str | None = None,
    ):
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
                    logger.debug(f"Failed to fetch node {node_id}: {e}")

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
            logger.debug(f"Failed to get node {node_id}: {e}")
        return None

    def _filter_by_time_range(
        self,
        candidates: list[ScoredNode],
        time_range: tuple[float, float],
    ) -> list[ScoredNode]:
        """Filter candidates by temporal range."""
        start, end = time_range
        return [c for c in candidates if c.timestamp is None or (start <= c.timestamp <= end)]

    def _calculate_graph_scores(
        self,
        candidates: list[ScoredNode],
        expansion_hops: int,
    ):
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

    def _calculate_temporal_scores(
        self,
        candidates: list[ScoredNode],
        time_range: tuple[float, float] | None,
    ):
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

    # =========================================================================
    # Cross-Video Search
    # =========================================================================

    def find_similar_across_videos(
        self,
        reference_node_id: str,
        limit: int = 10,
        min_similarity: float = 0.7,
    ) -> list[ScoredNode]:
        """
        Find similar nodes across other videos.

        Args:
            reference_node_id: Reference node ID
            limit: Maximum number of results
            min_similarity: Minimum similarity threshold

        Returns:
            List of similar nodes from other videos
        """
        # Retrieve the embedding of the reference node
        query = """
            MATCH (n {id: $node_id})
            RETURN n.embedding as embedding, n.video_id as video_id, labels(n)[0] as label
        """

        with self.graph_service.get_session() as session:
            result = session.run(query, node_id=reference_node_id)
            record = result.single()

            if not record or not record["embedding"]:
                return []

            ref_embedding = record["embedding"]
            ref_video_id = record["video_id"]
            ref_label = record["label"]

        # Search for similar nodes excluding the reference video
        try:
            node_type = NodeType(ref_label)
        except ValueError:
            return []

        # Vector search excluding the current video
        search_query = """
            CALL db.index.vector.queryNodes($index_name, $limit * 2, $embedding)
            YIELD node, score
            WHERE node.video_id <> $exclude_video AND score >= $min_score
            RETURN node, score
            ORDER BY score DESC
            LIMIT $limit
        """

        results = []
        index_name = f"{ref_label.lower()}_embedding"

        try:
            with self.graph_service.get_session() as session:
                result = session.run(
                    search_query,
                    index_name=index_name,
                    embedding=ref_embedding,
                    exclude_video=ref_video_id,
                    limit=limit,
                    min_score=min_similarity,
                )

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
                    results.append(scored)

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
