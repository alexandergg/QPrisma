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
                                `vector.similarity_function`: 'cosine'
                            }}
                        }}
                        """
                    )
                    logger.info(f"Created vector index {index_name} ({dims}d)")
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
            node_types = [
                NodeType.FRAME,
                NodeType.ENTITY,
                NodeType.AUDIO_SEGMENT,
                NodeType.COMMUNITY,
            ]

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
