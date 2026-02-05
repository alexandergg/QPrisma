"""
Graph-Enhanced Search Service for QPrisma

Implementa búsqueda híbrida combinando:
- Vector search (embeddings)
- Graph traversal (relaciones)
- Full-text search
- Temporal awareness
- Re-ranking con contexto expandido

Inspirado en VideoRAG para retrieval inteligente de contenido multimedia.
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime

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
    """Nodo con scores de diferentes fuentes."""

    node_id: str
    node_type: NodeType
    content: dict

    # Scores individuales
    vector_score: float = 0.0
    fulltext_score: float = 0.0
    graph_score: float = 0.0
    temporal_score: float = 0.0

    # Score combinado
    combined_score: float = 0.0

    # Contexto expandido
    related_nodes: list = field(default_factory=list)
    path_to_video: list = field(default_factory=list)

    # Metadata
    timestamp: float | None = None
    video_id: str | None = None


class GraphSearchService:
    """
    Servicio de búsqueda híbrida para el Knowledge Graph.

    Combina múltiples señales de relevancia:
    1. **Vector similarity**: Similitud semántica via embeddings
    2. **Graph proximity**: Cercanía en el grafo (hops)
    3. **Full-text match**: Coincidencia de términos
    4. **Temporal relevance**: Cercanía temporal en el video
    5. **Co-occurrence**: Entidades que aparecen juntas

    El scoring final combina estas señales con pesos configurables.
    """

    # Pesos por defecto para scoring híbrido
    DEFAULT_WEIGHTS = {
        "vector": 0.4,
        "fulltext": 0.2,
        "graph": 0.25,
        "temporal": 0.15,
    }

    # Dimensiones del embedding (text-embedding-3-large)
    EMBEDDING_DIM = 3072

    def __init__(
        self,
        graph_service: KnowledgeGraphService | None = None,
        embedding_service: EmbeddingService | None = None,
        weights: dict | None = None,
    ):
        """
        Inicializa el servicio de búsqueda.

        Args:
            graph_service: Servicio del Knowledge Graph
            embedding_service: Servicio de embeddings
            weights: Pesos personalizados para scoring
        """
        self.graph_service = graph_service or get_knowledge_graph_service()
        self.embedding_service = embedding_service or get_embedding_service()
        self.weights = weights or self.DEFAULT_WEIGHTS

        # Asegurar que los pesos suman 1
        total = sum(self.weights.values())
        if total != 1.0:
            self.weights = {k: v / total for k, v in self.weights.items()}

    # =========================================================================
    # Vector Index Management
    # =========================================================================

    def initialize_vector_indexes(self):
        """
        Crea índices vectoriales en Neo4j para búsqueda por similitud.

        Requiere Neo4j 5.11+ con soporte de vector indexes.
        """
        with self.graph_service.get_session() as session:
            # Índice vectorial para Frame embeddings
            try:
                session.run(
                    """
                    CREATE VECTOR INDEX frame_embedding IF NOT EXISTS
                    FOR (f:Frame)
                    ON f.embedding
                    OPTIONS {
                        indexConfig: {
                            `vector.dimensions`: 3072,
                            `vector.similarity_function`: 'cosine'
                        }
                    }
                """
                )
                logger.info("Created vector index for Frame embeddings")
            except Exception as e:
                logger.debug(f"Frame vector index may already exist: {e}")

            # Índice vectorial para Entity embeddings
            try:
                session.run(
                    """
                    CREATE VECTOR INDEX entity_embedding IF NOT EXISTS
                    FOR (e:Entity)
                    ON e.embedding
                    OPTIONS {
                        indexConfig: {
                            `vector.dimensions`: 3072,
                            `vector.similarity_function`: 'cosine'
                        }
                    }
                """
                )
                logger.info("Created vector index for Entity embeddings")
            except Exception as e:
                logger.debug(f"Entity vector index may already exist: {e}")

            # Índice vectorial para Scene embeddings
            try:
                session.run(
                    """
                    CREATE VECTOR INDEX scene_embedding IF NOT EXISTS
                    FOR (s:Scene)
                    ON s.embedding
                    OPTIONS {
                        indexConfig: {
                            `vector.dimensions`: 3072,
                            `vector.similarity_function`: 'cosine'
                        }
                    }
                """
                )
                logger.info("Created vector index for Scene embeddings")
            except Exception as e:
                logger.debug(f"Scene vector index may already exist: {e}")

            # Índice vectorial para AudioSegment embeddings (VideoRAG-style)
            try:
                session.run(
                    """
                    CREATE VECTOR INDEX audiosegment_embedding IF NOT EXISTS
                    FOR (a:AudioSegment)
                    ON a.embedding
                    OPTIONS {
                        indexConfig: {
                            `vector.dimensions`: 3072,
                            `vector.similarity_function`: 'cosine'
                        }
                    }
                """
                )
                logger.info("Created vector index for AudioSegment embeddings")
            except Exception as e:
                logger.debug(f"AudioSegment vector index may already exist: {e}")

    def store_embedding(
        self,
        node_id: str,
        embedding: list[float],
        node_type: NodeType | None = None,
    ):
        """
        Almacena un embedding en un nodo existente.

        Args:
            node_id: ID del nodo
            embedding: Vector de embedding (3072 dims)
            node_type: Tipo de nodo (para query más eficiente)
        """
        if node_type:
            label = node_type.value
            query = f"""
                MATCH (n:{label} {{id: $node_id}})
                SET n.embedding = $embedding,
                    n.embedding_updated_at = datetime()
                RETURN n.id
            """
        else:
            query = """
                MATCH (n {id: $node_id})
                SET n.embedding = $embedding,
                    n.embedding_updated_at = datetime()
                RETURN n.id
            """

        with self.graph_service.get_session() as session:
            session.run(query, node_id=node_id, embedding=embedding)

    def generate_and_store_embedding(
        self,
        node_id: str,
        text: str,
        node_type: NodeType | None = None,
    ) -> list[float]:
        """
        Genera embedding para texto y lo almacena en el nodo.

        Args:
            node_id: ID del nodo
            text: Texto a embedear
            node_type: Tipo de nodo

        Returns:
            El embedding generado
        """
        embedding = self.embedding_service.generate_embedding(text)
        self.store_embedding(node_id, embedding, node_type)
        return embedding

    def bulk_generate_embeddings(
        self,
        node_type: NodeType,
        text_field: str = "description",
        batch_size: int = 50,
        video_id: str | None = None,
    ) -> int:
        """
        Genera embeddings en bulk para todos los nodos de un tipo.

        Args:
            node_type: Tipo de nodo (Frame, Entity, Scene)
            text_field: Campo de texto a embedear
            batch_size: Tamaño del batch
            video_id: Filtrar por video (opcional)

        Returns:
            Número de embeddings generados
        """
        label = node_type.value

        # Query para obtener nodos sin embedding
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
            embeddings = self.embedding_service.generate_embeddings_batch(texts)

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
        min_score: float = 0.5,
    ) -> list[ScoredNode]:
        """
        Búsqueda por similitud vectorial usando índice de Neo4j.

        Args:
            query_embedding: Embedding de la query
            node_type: Tipo de nodo a buscar
            limit: Máximo de resultados
            video_id: Filtrar por video
            min_score: Score mínimo

        Returns:
            Lista de ScoredNode ordenados por similitud
        """
        label = node_type.value
        index_name = f"{label.lower()}_embedding"

        # Query usando el índice vectorial de Neo4j
        if video_id:
            query = """
                CALL db.index.vector.queryNodes($index_name, $limit * 2, $embedding)
                YIELD node, score
                WHERE node.video_id = $video_id AND score >= $min_score
                RETURN node, score
                ORDER BY score DESC
                LIMIT $limit
            """
            params = {
                "index_name": index_name,
                "embedding": query_embedding,
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
                ORDER BY score DESC
                LIMIT $limit
            """
            params = {
                "index_name": index_name,
                "embedding": query_embedding,
                "limit": limit,
                "min_score": min_score,
            }

        results = []

        try:
            with self.graph_service.get_session() as session:
                result = session.run(query, **params)

                for record in result:
                    node_data = dict(record["node"])
                    # Remover embedding del resultado (muy grande)
                    node_data.pop("embedding", None)

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
            logger.warning(f"Vector search failed (index may not exist): {e}")
            # Fallback a búsqueda manual si el índice no existe
            results = self._fallback_vector_search(
                query_embedding, node_type, limit, video_id, min_score
            )

        return results

    def _fallback_vector_search(
        self,
        query_embedding: list[float],
        node_type: NodeType,
        limit: int,
        video_id: str | None,
        min_score: float,
    ) -> list[ScoredNode]:
        """
        Búsqueda vectorial manual cuando el índice no está disponible.
        Menos eficiente pero funcional.
        """
        label = node_type.value

        if video_id:
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

        # Ordenar por score y limitar
        results.sort(key=lambda x: x.vector_score, reverse=True)
        return results[:limit]

    # =========================================================================
    # Hybrid Search
    # =========================================================================

    def hybrid_search(
        self,
        query_text: str,
        node_types: list[NodeType] | None = None,
        video_id: str | None = None,
        time_range: tuple[float, float] | None = None,
        limit: int = 20,
        expansion_hops: int = 2,
        use_reranking: bool = True,
    ) -> GraphSearchResponse:
        """
        Búsqueda híbrida combinando vector, full-text y graph.

        Args:
            query_text: Texto de búsqueda
            node_types: Tipos de nodos a buscar (default: Frame, Entity)
            video_id: Filtrar por video
            time_range: Rango temporal (start, end) en segundos
            limit: Máximo de resultados
            expansion_hops: Hops para expansión de contexto
            use_reranking: Si aplicar re-ranking con contexto

        Returns:
            GraphSearchResponse con resultados ordenados
        """
        start_time = datetime.utcnow()

        if node_types is None:
            node_types = [NodeType.FRAME, NodeType.ENTITY, NodeType.AUDIO_SEGMENT]

        # 1. Generar embedding de la query
        query_embedding = self.embedding_service.generate_embedding(query_text)
        (datetime.utcnow() - start_time).total_seconds() * 1000

        # 2. Buscar en cada tipo de nodo
        all_candidates: list[ScoredNode] = []

        vector_start = datetime.utcnow()
        for node_type in node_types:
            # Vector search
            vector_results = self.vector_search(
                query_embedding=query_embedding,
                node_type=node_type,
                limit=limit * 2,  # Obtener más para re-ranking
                video_id=video_id,
                min_score=0.3,
            )
            all_candidates.extend(vector_results)

            # Full-text search
            fulltext_results = self._fulltext_search(
                query_text=query_text,
                node_type=node_type,
                limit=limit,
                video_id=video_id,
            )

            # Merge full-text scores con candidatos existentes y añadir nuevos
            self._merge_fulltext_scores(all_candidates, fulltext_results, node_type, video_id)

        vector_search_time = (datetime.utcnow() - vector_start).total_seconds() * 1000

        # 3. Aplicar filtro temporal si se especificó
        if time_range:
            all_candidates = self._filter_by_time_range(all_candidates, time_range)

        # 4. Calcular graph scores
        graph_start = datetime.utcnow()
        self._calculate_graph_scores(all_candidates, expansion_hops)
        graph_time = (datetime.utcnow() - graph_start).total_seconds() * 1000

        # 5. Calcular temporal scores
        self._calculate_temporal_scores(all_candidates, time_range)

        # 6. Calcular score combinado
        for candidate in all_candidates:
            candidate.combined_score = (
                self.weights["vector"] * candidate.vector_score
                + self.weights["fulltext"] * candidate.fulltext_score
                + self.weights["graph"] * candidate.graph_score
                + self.weights["temporal"] * candidate.temporal_score
            )

        # 7. Re-ranking con contexto expandido
        if use_reranking and all_candidates:
            all_candidates = self._rerank_with_context(all_candidates, query_text, query_embedding)

        # 8. Ordenar y limitar
        all_candidates.sort(key=lambda x: x.combined_score, reverse=True)
        final_results = all_candidates[:limit]

        # 9. Construir respuesta
        total_time = (datetime.utcnow() - start_time).total_seconds() * 1000

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
    ) -> list[tuple[str, float]]:
        """Búsqueda full-text y retorna [(node_id, score)]."""
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
            # Filter by video_id if provided
            if video_id:
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
        Merge full-text scores con candidatos existentes.
        También añade nuevos candidatos que solo fueron encontrados por full-text.
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
        """Filtra candidatos por rango temporal."""
        start, end = time_range
        return [c for c in candidates if c.timestamp is None or (start <= c.timestamp <= end)]

    def _calculate_graph_scores(
        self,
        candidates: list[ScoredNode],
        expansion_hops: int,
    ):
        """
        Calcula graph scores basados en conectividad y expansión.

        Nodos más conectados y cercanos al centro del grafo obtienen scores más altos.
        """
        if not candidates:
            return

        for candidate in candidates:
            try:
                # Expandir contexto
                expansion = self.graph_service.expand_context(
                    node_id=candidate.node_id,
                    hops=expansion_hops,
                    max_nodes=30,
                )

                # Graph score basado en número de conexiones
                total_related = expansion.get("total_nodes", 0)
                candidate.graph_score = min(1.0, total_related / 50)  # Normalizar a 50

                # Guardar nodos relacionados
                nodes_by_distance = expansion.get("nodes_by_distance", {})
                for distance, nodes in nodes_by_distance.items():
                    for node in nodes[:5]:  # Limitar por distancia
                        candidate.related_nodes.append(
                            {
                                "node": node,
                                "distance": distance,
                            }
                        )

                # Calcular path to video
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
        Calcula temporal scores basados en posición temporal.

        Si hay un rango de tiempo especificado, nodos más cercanos al centro obtienen
        scores más altos. Si no, se basa en densidad de eventos cercanos.
        """
        if not candidates:
            return

        # Si hay rango temporal, calcular cercanía al centro
        if time_range:
            center = (time_range[0] + time_range[1]) / 2
            range_width = time_range[1] - time_range[0]

            for candidate in candidates:
                if candidate.timestamp is not None:
                    distance = abs(candidate.timestamp - center)
                    # Score gaussiano
                    candidate.temporal_score = math.exp(-0.5 * (distance / (range_width / 2)) ** 2)
                else:
                    candidate.temporal_score = 0.5  # Score neutral
        else:
            # Sin rango, dar score basado en si tiene timestamp
            for candidate in candidates:
                candidate.temporal_score = 0.7 if candidate.timestamp is not None else 0.3

    def _rerank_with_context(
        self,
        candidates: list[ScoredNode],
        query_text: str,
        query_embedding: list[float],
    ) -> list[ScoredNode]:
        """
        Re-ranking usando contexto expandido.

        Para cada candidato, considera también la relevancia de sus nodos relacionados.
        """
        for candidate in candidates:
            if not candidate.related_nodes:
                continue

            # Calcular boost basado en relevancia de nodos relacionados
            context_boost = 0.0
            related_count = 0

            for related in candidate.related_nodes[:10]:
                node_data = related.get("node", {})
                distance = related.get("distance", 1)

                # Texto del nodo relacionado
                related_text = node_data.get("description") or node_data.get("name", "")

                if related_text:
                    # Bonus por coincidencia de términos
                    query_terms = set(query_text.lower().split())
                    related_terms = set(related_text.lower().split())
                    overlap = len(query_terms & related_terms)

                    if overlap > 0:
                        # Boost decae con la distancia
                        term_boost = (overlap / len(query_terms)) / (distance + 1)
                        context_boost += term_boost
                        related_count += 1

            # Aplicar boost (máximo 20% de incremento)
            if related_count > 0:
                avg_boost = context_boost / related_count
                candidate.combined_score *= 1 + min(0.2, avg_boost)

        return candidates

    def _get_path_to_video(self, node_id: str) -> list[str]:
        """Obtiene el path desde un nodo hasta el Video raíz."""
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
        """Cuenta resultados por tipo de nodo."""
        counts = {}
        for r in results:
            type_name = r.node_type.value
            counts[type_name] = counts.get(type_name, 0) + 1
        return counts

    def _count_by_video(self, results: list[ScoredNode]) -> dict[str, int]:
        """Cuenta resultados por video."""
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
        Encuentra nodos similares en otros videos.

        Args:
            reference_node_id: ID del nodo de referencia
            limit: Máximo de resultados
            min_similarity: Similitud mínima

        Returns:
            Lista de nodos similares de otros videos
        """
        # Obtener embedding del nodo de referencia
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

        # Buscar similares excluyendo el video de referencia
        try:
            node_type = NodeType(ref_label)
        except ValueError:
            return []

        # Vector search excluyendo el video actual
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
    """Obtiene la instancia singleton del GraphSearchService."""
    global _graph_search_service
    if _graph_search_service is None:
        _graph_search_service = GraphSearchService()
        try:
            _graph_search_service.initialize_vector_indexes()
        except Exception as e:
            logger.warning(f"Vector index initialization failed: {e}")
    return _graph_search_service
